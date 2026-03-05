"""
RAG Engine — Knowledge Base Injection (Rule B)

PDF Ingestion Pipeline:
  1. Scan sea_invest/rag/knowledge_files/ for all *.pdf files
  2. Extract text page-by-page via pypdf
  3. Split into overlapping chunks (RecursiveCharacterTextSplitter)
  4. Persist chunks + embeddings into Chroma (or FAISS) vector store
  5. Skip re-ingestion for PDFs whose content hasn't changed (SHA-256 fingerprint)

Supports:
  - settings.vector_store_type = "chroma" | "faiss"
  - Graceful fallback to hardcoded excerpts when vector store is unavailable

Configuration (via Settings):
  - rag_chunk_size: characters per chunk (default: 800)
  - rag_chunk_overlap: overlap between chunks (default: 150)
  - rag_min_chunk_size: minimum chunk size to keep (default: 80)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from sea_invest.config import get_settings

if TYPE_CHECKING:
    from langchain_core.vectorstores import VectorStore

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────
# Chunking defaults (can be overridden via Settings)
# ─────────────────────────────────────────────
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 150
DEFAULT_MIN_CHUNK_SIZE = 80

# ─────────────────────────────────────────────
# Lazy Initialization Helpers
# ─────────────────────────────────────────────

_settings = None
_fingerprint_file: Path | None = None
_knowledge_files_dir: Path | None = None


def _get_settings():
    """Lazily initialize and return settings singleton."""
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


def _get_fingerprint_file() -> Path:
    """Lazily compute fingerprint file path."""
    global _fingerprint_file
    if _fingerprint_file is None:
        settings = _get_settings()
        _fingerprint_file = Path(settings.chroma_persist_dir) / "ingested_sources.json"
    return _fingerprint_file


def _get_knowledge_files_dir() -> Path:
    """Return knowledge files directory (prefers config over default)."""
    global _knowledge_files_dir
    if _knowledge_files_dir is None:
        settings = _get_settings()
        # Use config if set, otherwise default to sibling directory
        if settings.knowledge_base_dir:
            custom_path = Path(settings.knowledge_base_dir)
            # Try to create custom directory if it doesn't exist
            try:
                custom_path.mkdir(parents=True, exist_ok=True)
                _knowledge_files_dir = custom_path
                logger.info("knowledge_files_dir_created", path=str(custom_path))
            except Exception as e:
                # If creation fails, fall back to default directory
                logger.warning(
                    "knowledge_files_custom_creation_failed",
                    custom_path=str(custom_path),
                    error=str(e),
                    fallback=str(custom_path)
                )
                _knowledge_files_dir = Path(__file__).parent / "knowledge_files"
        else:
            default_path = Path(__file__).parent / "knowledge_files"
            # Create default directory if it doesn't exist
            try:
                default_path.mkdir(parents=True, exist_ok=True)
                _knowledge_files_dir = default_path
                logger.info("knowledge_files_default_dir_checked", path=str(default_path))
            except Exception as e:
                logger.warning(
                    "knowledge_files_default_creation_failed",
                    default_path=str(default_path),
                    error=str(e)
                )
                _knowledge_files_dir = default_path
    return _knowledge_files_dir


def _get_chunk_config() -> tuple[int, int, int]:
    """Return (chunk_size, chunk_overlap, min_chunk_size) from settings or defaults."""
    settings = _get_settings()
    chunk_size = getattr(settings, "rag_chunk_size", DEFAULT_CHUNK_SIZE)
    chunk_overlap = getattr(settings, "rag_chunk_overlap", DEFAULT_CHUNK_OVERLAP)
    min_chunk_size = getattr(settings, "rag_min_chunk_size", DEFAULT_MIN_CHUNK_SIZE)
    return chunk_size, chunk_overlap, min_chunk_size


# Chroma collection name
_COLLECTION_NAME = "howard_marks_kb"


# ─────────────────────────────────────────────
# PDF Discovery
# ─────────────────────────────────────────────

def discover_pdfs() -> list[Path]:
    """
    Return a sorted list of all *.pdf files found in knowledge files directory.
    Logs a warning if the directory is missing or empty.
    """
    knowledge_dir = _get_knowledge_files_dir()
    if not knowledge_dir.exists():
        logger.warning("knowledge_files_dir_missing", path=str(knowledge_dir))
        return []
    pdfs = sorted(knowledge_dir.glob("*.pdf"))
    if not pdfs:
        logger.warning("knowledge_files_dir_empty", path=str(knowledge_dir))
    else:
        logger.info("knowledge_pdfs_discovered", count=len(pdfs),
                    files=[p.name for p in pdfs])
    return pdfs

# ─────────────────────────────────────────────
# PDF Text Extraction
# ─────────────────────────────────────────────

def _extract_text_from_pdf(pdf_path: Path) -> list[dict]:
    """
    Extract raw text from a PDF, page by page.

    Returns:
        list of {"page": int, "text": str, "source": str}
    Raises:
        ImportError  — if pypdf is not installed
        FileNotFoundError — if the PDF path doesn't exist
    """
    try:
        import pypdf
    except ImportError:
        raise ImportError(
            "pypdf is required for PDF ingestion. Install via: pip install pypdf"
        )

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pages = []
    with open(pdf_path, "rb") as f:
        reader = pypdf.PdfReader(f)
        total_pages = len(reader.pages)
        logger.info("pdf_extracting", file=pdf_path.name, total_pages=total_pages)

        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append({
                    "page": i + 1,
                    "text": text,
                    "source": pdf_path.stem,   # filename without extension
                })

    logger.info("pdf_extracted", file=pdf_path.name, pages_with_text=len(pages))
    return pages


# ─────────────────────────────────────────────
# Text Chunking
# ─────────────────────────────────────────────

def _chunk_pages(
    pages: list[dict],
) -> tuple[list[str], list[dict]]:
    """
    Split page texts into overlapping chunks.

    Returns:
        texts     — list of chunk strings
        metadatas — parallel list of metadata dicts
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    chunk_size, chunk_overlap, min_chunk_size = _get_chunk_config()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    texts: list[str] = []
    metadatas: list[dict] = []

    for page_info in pages:
        chunks = splitter.split_text(page_info["text"])
        for idx, chunk in enumerate(chunks):
            chunk = chunk.strip()
            if len(chunk) < min_chunk_size:
                continue
            texts.append(chunk)
            metadatas.append({
                "source": page_info["source"],
                "page": page_info["page"],
                "chunk_index": idx,
            })

    logger.info(
        "pdf_chunked",
        source=pages[0]["source"] if pages else "unknown",
        total_chunks=len(texts),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return texts, metadatas


# ─────────────────────────────────────────────
# Fingerprinting — Incremental Ingestion
# ─────────────────────────────────────────────

def _sha256_head(pdf_path: Path) -> str:
    """SHA-256 of the first 64 KB — fast, stable identity for the file."""
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        h.update(f.read(65_536))
    return h.hexdigest()


def _load_fingerprints() -> dict[str, str]:
    fp_file = _get_fingerprint_file()
    try:
        if fp_file.exists():
            return json.loads(fp_file.read_text())
    except Exception:
        pass
    return {}


def _save_fingerprints(fp_map: dict[str, str]) -> None:
    fp_file = _get_fingerprint_file()
    fp_file.parent.mkdir(parents=True, exist_ok=True)
    fp_file.write_text(json.dumps(fp_map, indent=2))


def _needs_ingestion(pdf_path: Path, fp_map: dict[str, str]) -> bool:
    key = str(pdf_path.resolve())
    return key not in fp_map or fp_map[key] != _sha256_head(pdf_path)


def _mark_ingested(pdf_path: Path, fp_map: dict[str, str]) -> None:
    fp_map[str(pdf_path.resolve())] = _sha256_head(pdf_path)


# ─────────────────────────────────────────────
# Ingestion Core — shared logic
# ─────────────────────────────────────────────

def _ingest_pdfs_into_store(vs, pdfs: list[Path], fp_map: dict[str, str]) -> int:
    """
    Extract, chunk, and add all given PDFs to an existing vector store `vs`.
    Updates fp_map in-place. Returns the number of chunks added.
    """
    total_added = 0
    for pdf_path in pdfs:
        try:
            pages = _extract_text_from_pdf(pdf_path)
            texts, metas = _chunk_pages(pages)
            if texts:
                vs.add_texts(texts=texts, metadatas=metas)
                _mark_ingested(pdf_path, fp_map)
                total_added += len(texts)
                logger.info("pdf_ingested", file=pdf_path.name, chunks=len(texts))
        except Exception as e:
            logger.error("pdf_ingest_error", file=pdf_path.name, error=str(e))
    return total_added


# ─────────────────────────────────────────────
# Vector Store — Chroma Backend
# ─────────────────────────────────────────────

def _build_chroma_store(embeddings, persist_dir: str, collection_name: str):
    import chromadb
    from langchain_chroma import Chroma

    Path(persist_dir).mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=persist_dir)
    existing_names = [c.name for c in client.list_collections()]
    fp_map = _load_fingerprints()

    all_pdfs = discover_pdfs()
    new_pdfs = [p for p in all_pdfs if _needs_ingestion(p, fp_map)]

    if collection_name not in existing_names:
        # ── First run: bootstrap collection from all PDFs ──
        if not all_pdfs:
            logger.warning("rag_no_pdfs_to_ingest")
            return None

        # Build initial texts from ALL pdfs
        all_texts: list[str] = []
        all_metas: list[dict] = []
        for pdf_path in all_pdfs:
            try:
                pages = _extract_text_from_pdf(pdf_path)
                texts, metas = _chunk_pages(pages)
                all_texts.extend(texts)
                all_metas.extend(metas)
                _mark_ingested(pdf_path, fp_map)
                logger.info("pdf_ingested", file=pdf_path.name, chunks=len(texts))
            except Exception as e:
                logger.error("pdf_ingest_error", file=pdf_path.name, error=str(e))

        if not all_texts:
            logger.warning("rag_no_content_extracted")
            return None

        logger.info("rag_creating_collection",
                    collection=collection_name, total_chunks=len(all_texts))
        Chroma.from_texts(
            texts=all_texts,
            embedding=embeddings,
            metadatas=all_metas,
            collection_name=collection_name,
            persist_directory=persist_dir,
        )
        _save_fingerprints(fp_map)
        logger.info("rag_collection_created", doc_count=len(all_texts))

    elif new_pdfs:
        # ── Incremental: add only new/changed PDFs ──
        vs = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=persist_dir,
        )
        added = _ingest_pdfs_into_store(vs, new_pdfs, fp_map)
        _save_fingerprints(fp_map)
        logger.info("rag_incremental_update_complete", new_chunks=added)

    else:
        logger.info("rag_kb_loaded_from_cache", collection=collection_name)

    return Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=persist_dir,
    )


# ─────────────────────────────────────────────
# Vector Store — FAISS Backend
# ─────────────────────────────────────────────

def _build_faiss_store(embeddings, persist_dir: str):
    from langchain_community.vectorstores import FAISS

    faiss_path = Path(persist_dir) / "faiss_index"
    fp_map = _load_fingerprints()
    all_pdfs = discover_pdfs()
    new_pdfs = [p for p in all_pdfs if _needs_ingestion(p, fp_map)]

    if faiss_path.exists():
        vs = FAISS.load_local(
            str(faiss_path), embeddings, allow_dangerous_deserialization=True
        )
        if new_pdfs:
            added = _ingest_pdfs_into_store(vs, new_pdfs, fp_map)
            vs.save_local(str(faiss_path))
            _save_fingerprints(fp_map)
            logger.info("rag_faiss_incremental_update", new_chunks=added)
        else:
            logger.info("rag_faiss_loaded_from_cache")
        return vs

    # Fresh build
    all_texts: list[str] = []
    all_metas: list[dict] = []
    for pdf_path in all_pdfs:
        try:
            pages = _extract_text_from_pdf(pdf_path)
            texts, metas = _chunk_pages(pages)
            all_texts.extend(texts)
            all_metas.extend(metas)
            _mark_ingested(pdf_path, fp_map)
            logger.info("pdf_ingested", file=pdf_path.name, chunks=len(texts))
        except Exception as e:
            logger.error("pdf_ingest_error", file=pdf_path.name, error=str(e))

    if not all_texts:
        logger.warning("rag_faiss_no_content")
        return None

    faiss_path.mkdir(parents=True, exist_ok=True)
    vs = FAISS.from_texts(all_texts, embeddings, metadatas=all_metas)
    vs.save_local(str(faiss_path))
    _save_fingerprints(fp_map)
    logger.info("rag_faiss_built", total_chunks=len(all_texts))
    return vs


# ─────────────────────────────────────────────
# Public Entry Point — get/create vector store
# ─────────────────────────────────────────────

def _get_or_create_vectorstore():
    """Initialize or load the vector store, ingesting PDFs as needed."""
    settings = _get_settings()
    
    def _get_embeddings():
        if getattr(settings, "llm_provider", "openai") == "google":
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            return GoogleGenerativeAIEmbeddings(
                model="gemini-embedding-001",
                google_api_key=settings.google_api_key
            )
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(api_key=settings.openai_api_key)

    if settings.vector_store_type == "chroma":
        try:
            return _build_chroma_store(
                embeddings=_get_embeddings(),
                persist_dir=settings.chroma_persist_dir,
                collection_name=_COLLECTION_NAME,
            )
        except ImportError as e:
            logger.warning("chroma_not_available", error=str(e))
            return None

    elif settings.vector_store_type == "faiss":
        try:
            return _build_faiss_store(
                embeddings=_get_embeddings(),
                persist_dir=settings.chroma_persist_dir,
            )
        except ImportError as e:
            logger.warning("faiss_not_available", error=str(e))
            return None

    return None


# ─────────────────────────────────────────────
# Singleton Vector Store
# ─────────────────────────────────────────────

_vectorstore = None


def get_vectorstore():
    """Return the singleton vector store (lazy-initialized)."""
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = _get_or_create_vectorstore()
    return _vectorstore


def reset_vectorstore() -> None:
    """Force re-initialization on the next call (useful in tests)."""
    global _vectorstore
    _vectorstore = None


# ─────────────────────────────────────────────
# RAG Injection — LangGraph Node
# ─────────────────────────────────────────────

async def inject_rag_context(state, top_k: int = 5):
    """
    LangGraph Node-compatible: retrieve relevant Howard Marks chunks
    and inject them into state.rag_context.

    Called before the Strategist and Risk Auditor nodes.
    """
    logger.info("rag_inject_start", ticker=state.ticker)
    state.current_node = "rag_injector"

    query_parts = [f"{state.ticker} {state.asset_class.value} investment cycle positioning"]
    if state.market_data and state.market_data.earnings_summary:
        query_parts.append(state.market_data.earnings_summary[:200])
    query = " ".join(query_parts)

    try:
        vs = get_vectorstore()
        if vs is None:
            state.rag_context = _fallback_rag_context()
            return state

        docs = vs.similarity_search(query, k=top_k)
        context_blocks = []
        for doc in docs:
            source = doc.metadata.get("source", "Howard Marks")
            page = doc.metadata.get("page", "")
            page_label = f", p.{page}" if page else ""
            context_blocks.append(
                f"**[{source}{page_label}]**\n{doc.page_content}"
            )

        state.rag_context = "\n\n---\n\n".join(context_blocks)
        logger.info("rag_inject_complete", chunks_retrieved=len(docs))

    except Exception as e:
        logger.warning("rag_inject_failed", error=str(e))
        state.rag_context = _fallback_rag_context()

    return state


# ─────────────────────────────────────────────
# Hardcoded Fallback
# ─────────────────────────────────────────────

def _fallback_rag_context() -> str:
    """Return hardcoded key principles when the vector store is unavailable."""
    return """\
**Howard Marks Key Principles (Fallback)**:

1. "Second-level thinking asks: what's the range of likely outcomes? What's my expectation vs \
consensus? How does price relate to intrinsic value? Is consensus psychology too bullish or bearish?"

2. "Risk is the probability of permanent loss, not short-term volatility. The best defense is \
buying when others fear and selling when others are greedy."

3. "The pendulum swings between fear and greed, undervaluation and overvaluation. Know where you \
stand in the cycle. When euphoria is rampant, maximum caution. When fear is rampant, maximum opportunity."

4. "No one knows the future. Position asymmetrically: protect when risk is high, invest aggressively \
when risk is low and price is right."
"""


# ─────────────────────────────────────────────
# CLI — Manual Ingestion
# Usage: python -m sea_invest.rag.knowledge_base
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    knowledge_dir = _get_knowledge_files_dir()
    print("=" * 60)
    print("SEA-Invest RAG — PDF Ingestion Pipeline")
    print(f"Knowledge files directory: {knowledge_dir}")
    print("=" * 60)

    pdfs = discover_pdfs()
    if not pdfs:
        print("\n[ERROR] No PDF files found. Please add PDFs to:", knowledge_dir)
        sys.exit(1)

    for p in pdfs:
        size_mb = p.stat().st_size / 1_048_576
        print(f"  ✓ {p.name}  ({size_mb:.1f} MB)")

    print("\nStarting ingestion …")
    reset_vectorstore()
    vs = get_vectorstore()

    if vs is None:
        print("\n[ERROR] Vector store initialization failed.")
        sys.exit(1)

    # Report final collection size (Chroma only)
    try:
        n = vs._collection.count()
        print(f"\n✓ Ingestion complete. Total chunks in vector store: {n}")
    except Exception:
        print("\n✓ Ingestion complete.")

    sys.exit(0)
