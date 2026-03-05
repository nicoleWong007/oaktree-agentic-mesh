from typing import Any, Dict

import httpx

from sea_invest.perception.base import BaseDataSource
from sea_invest.perception.schema import MarketMoment


class YahooFinanceDriver(BaseDataSource):
    """
    Yahoo Finance 数据感知驱动器实现。
    目标：获取某 Ticker 的财务及行情快照 (此处用 Chart 端点简单示意数据链路映射的过程)。
    """

    def __init__(self, **config: Any):
        # 声明此节点职责为获取基本面和盘面结合情况
        super().__init__(name="YahooFinance", category="Fundamental", **config)
        # Yahoo Finance Chart Endpoint
        self.base_url = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

    async def fetch(self, target: str) -> Dict[str, Any]:
        url = self.base_url.format(ticker=target.upper())
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "https://finance.yahoo.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site"
        }
        
        async with httpx.AsyncClient(headers=headers) as client:
            return await self.fetch_with_retry(client, url)

    def _normalize(self, target: str, raw_data: Dict[str, Any]) -> MarketMoment:
        try:
            # 钻取由于 Yahoo 接口引发的冗长 JSON
            result_block = raw_data["chart"]["result"][0]
            meta = result_block["meta"]
            
            current_price = meta.get("regularMarketPrice")
            currency = meta.get("currency")
            
            # 使用虚构的 PE mock 用于示范（真实场景需调用 Yahoo Quote 接口提取 trailingPE 等）
            dummy_pe_ratio = 15.4  

            # 结构化核心负载
            payload = {
                "ticker": target.upper(),
                "price": current_price,
                "currency": currency,
                "pe_ratio": dummy_pe_ratio
            }

            return MarketMoment(
                source_name=self.name,
                category=self.category,
                payload=payload,
                # 预留此位以用于 AI 智能评估的感知指标如“市场热度”、“过度反应等” 
                marks_indicators={"market_fever": 0.65} 
            )
        except (KeyError, IndexError) as err:
             raise ValueError(f"Abnormal Schema encountered in Yahoo API response: {str(err)}")
