import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class MarketMoment(BaseModel):
    """
    MarketMoment 代表市场在特定时间点的一个“数据快照”。
    包含基础的数值或非数值信息，以及预留给后续 AI 评估和打分的指标点。
    """
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4, 
        description="全局唯一且不可变的数据快照标识符"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="数据产生或抓取的时间戳 (UTC 标准时间)"
    )
    source_name: str = Field(..., description="数据来源名称, 如 'YahooFinance', 'FredMacro'")
    category: Literal["Fundamental", "Macro", "Sentiment"] = Field(
        ..., description="数据域分类约束"
    )
    payload: Dict[str, Any] = Field(
        ..., description="核心负载字典，用于装载非标准结构的原始指标(如价格、文本报告、GDP值等)"
    )
    marks_indicators: Optional[Dict[str, float]] = Field(
        default=None,
        description="预留给 Agent/AI 评估后填入的标准化评价体系指标 (取值范围规范化)"
    )

    # 拒绝未定义的额外字段，避免脏数据流入
    model_config = ConfigDict(extra="forbid")
