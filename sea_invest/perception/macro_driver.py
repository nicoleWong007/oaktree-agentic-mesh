import asyncio
from datetime import datetime, timezone
from typing import Any, Dict

import httpx
from loguru import logger

from sea_invest.perception.base import BaseDataSource
from sea_invest.perception.schema import MarketMoment


class MacroDriver(BaseDataSource):
    """
    宏观经济数据感知驱动器实现。
    目标：获取美联储利率(FEDFUNDS)、CPI(CPIAUCSL)、信贷利差(BAMLH0A0HYM2)等宏观指标。
    """

    def __init__(self, **config: Any):
        # 声明此节点职责为获取宏观经济数据
        super().__init__(name="FREDMacro", category="Macro", **config)
        self.api_key = config.get("api_key")
        # 以 FRED API 为例
        self.base_url = "https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json"

    async def fetch(self, target: str) -> Dict[str, Any]:
        # 若未提供真实 API Key，则使用模拟推演数据以保障系统正常流转测试
        if not self.api_key or self.api_key == "demo":
            logger.debug(f"[{self.name}] No valid API Key, returning mock payload for {target}")
            await asyncio.sleep(0.1)  # 模拟网络延迟
            mock_data = {
                "FEDFUNDS": "5.33",
                "CPIAUCSL": "311.18",
                "BAMLH0A0HYM2": "3.15"
            }
            val = mock_data.get(target.upper(), "0.0")
            return {
                "observations": [
                    {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "value": val}
                ]
            }

        url = self.base_url.format(series_id=target.upper(), api_key=self.api_key)
        headers = {"User-Agent": "Mozilla/5.0 (SEA-Invest Perceptor; +AgenticMesh)"}
        async with httpx.AsyncClient(headers=headers) as client:
             return await self.fetch_with_retry(client, url)

    def _normalize(self, target: str, raw_data: Dict[str, Any]) -> MarketMoment:
        try:
            observations = raw_data.get("observations", [])
            if not observations:
                raise ValueError(f"No observation data found for {target}")
            
            # 获取最新的一条指标记录
            latest_record = observations[-1]
            value_str = latest_record.get("value", "0")
            date_str = latest_record.get("date", "1970-01-01")
            
            # FRED 数据中有时会将缺失值表示为 "."
            actual_value = float(value_str) if value_str != "." else 0.0
            
            payload = {
                "indicator": target.upper(),
                "release_date": date_str,
                "value": actual_value,
                "description": self._get_description(target.upper())
            }

            return MarketMoment(
                source_name=self.name,
                category=self.category,
                payload=payload,
                # 预留评价体系，例如：当前宏观风险分数等
                marks_indicators={"macro_risk_level": 0.5}
            )
        except Exception as err:
             raise ValueError(f"Abnormal Schema encountered in Macro API response: {str(err)}")

    def _get_description(self, target: str) -> str:
        descriptions = {
            "FEDFUNDS": "Federal Funds Effective Rate (美联储利率)",
            "CPIAUCSL": "Consumer Price Index for All Urban Consumers (CPI)",
            "BAMLH0A0HYM2": "ICE BofA US High Yield Index Option-Adjusted Spread (信贷利差)"
        }
        return descriptions.get(target.upper(), "Unknown Macro Indicator")
