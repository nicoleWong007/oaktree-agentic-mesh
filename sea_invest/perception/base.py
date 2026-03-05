import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, Literal

import httpx
from loguru import logger

from sea_invest.perception.schema import MarketMoment


class BaseDataSource(ABC):
    """
    定义所有底层数据抓取源的抽象基类。
    实现采集(fetch)与解析(normalize)这两层逻辑的完全解耦。
    """

    def __init__(self, name: str, category: Literal["Fundamental", "Macro", "Sentiment"], **config: Any):
        """
        初始化数据源驱动。
        
        Args:
            name: 数据源的唯一名称。
            category: 数据所属的大类领域。
            **config: 动态配置，如 api_key, timeout, base_url 等。
        """
        self.name = name
        self.category = category
        self.config = config
        self.timeout = config.get("timeout", 10.0)

    async def fetch_with_retry(self, client: httpx.AsyncClient, url: str, max_retries: int = 3) -> Dict[str, Any]:
        """
        通用的 HTTP 请求方法封装，包含防抖的 Exponential Backoff (指数退避) 策略机制。
        
        Args:
            client: 异步 HTTP 客户端。
            url: 上游的请求终点。
            max_retries: 失败之后执行的最大重试次数。
            
        Returns:
            JSON 反序列化后的数据字典。
        """
        base_delay = 1.0  # 基础间隔时间 (1 秒)
        for attempt in range(max_retries):
            try:
                response = await client.get(url, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                logger.warning(
                    f"[{self.name}] Fetch attempt {attempt + 1}/{max_retries} failed | "
                    f"URL: {url} | Error: {str(e)}"
                )
                if attempt == max_retries - 1:
                    logger.error(f"[{self.name}] Exhausted all {max_retries} fetch attempts for URL {url}.")
                    raise
                
                # 指数级退避等待: 1s, 2s, 4s...
                delay_seconds = base_delay * (2 ** attempt)
                logger.info(f"[{self.name}] Retrying in {delay_seconds} seconds...")
                await asyncio.sleep(delay_seconds)
        
        # 兜底返回结构
        return {}

    @abstractmethod
    async def fetch(self, target: str) -> Dict[str, Any]:
        """
        向目标端点异步索要数据，交由具体 Driver 实现。
        
        Args:
            target: 抓取对象标识（如股票 Ticker、宏观指标 ID 等）。
        """
        pass

    @abstractmethod
    def _normalize(self, target: str, raw_data: Dict[str, Any]) -> MarketMoment:
        """
        将杂乱无章的上游原始数据映射转换为标准领域模型 (MarketMoment)。
        """
        pass

    async def process(self, target: str) -> MarketMoment:
        """
        业务主流程控制枢纽：负责编排 "抓取(Fetch)" -> "映射(Normalize)" -> "输出(MarketMoment)"。
        任何上层模块应该仅调用本方法，即可无脑获取对应结果。
        """
        logger.debug(f"[{self.name}] Commencing data process pipeline for target: {target}")
        
        # 1. 抓取原始脏数据
        raw_data = await self.fetch(target)
        
        try:
            # 2. 映射重构并校验通过 Pydantic 
            moment = self._normalize(target, raw_data)
            logger.success(f"[{self.name}] Pipeline completed. Synthesized MarketMoment for {target}")
            return moment
        except Exception as e:
            logger.error(f"[{self.name}] Normalization logic failed for target '{target}': {str(e)}")
            raise
