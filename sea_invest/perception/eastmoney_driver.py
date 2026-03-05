"""
东方财富数据驱动器 (EastMoney Driver)
=====================================

数据源：
- 实时行情（股票价格、涨跌幅、成交量）
- 龙虎榜数据（机构买卖、游资动向）
- 北向资金流向（沪港通、深港通）
- 融资融券数据（两融余额）
- 板块资金流（行业/概念资金流）
- Level-2 数据（买卖五档）

API 文档：
- https://openapidocs.eastmoney.com/
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from decimal import Decimal

import httpx
from loguru import logger

from sea_invest.perception.base import BaseDataSource
from sea_invest.perception.schema import MarketMoment


class EastMoneyDriver(BaseDataSource):
    """
    东方财富数据驱动器
    
    特点：
    - 免费 API，无需认证
    - 支持 A 股所有股票
    - 实时性强（盘中更新）
    """
    
    def __init__(self, **config: Any):
        super().__init__(name="EastMoney", category="Fundamental", **config)
        
        # 基础 URL
        self.base_urls = {
            "quote": "https://push2.eastmoney.com/api/qt/stock/get",  # 实时行情
            "longhu": "https://datahub.eastmoney.com/lhb/data",  # 龙虎榜
            "north_flow": "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",  # 北向资金
            "margin": "https://datacenter-web.eastmoney.com/api/data/v1/get",  # 融资融券
            "sector_flow": "https://push2.eastmoney.com/api/qt/stock/fflow/sector",  # 板块资金流
        }
        
        # 默认参数
        self.timeout = config.get("timeout", 15.0)
        
        # 市场 ID 映射（东方财富格式）
        self.market_id_map = {
            "SH": "1",   # 上海证券交易所
            "SZ": "0",   # 深圳证券交易所
            "BJ": "1",   # 北京证券交易所（使用上海市场ID）
        }
    
    def _get_market_id(self, ticker: str) -> str:
        """
        根据股票代码识别市场 ID
        
        规则：
        - 6 开头：上海证券交易所（1）
        - 0/3 开头：深圳证券交易所（0）
        - 4/8 开头：北京证券交易所（1）
        """
        if ticker.startswith("6"):
            return "1"  # 上海
        elif ticker.startswith(("0", "3")):
            return "0"  # 深圳
        elif ticker.startswith(("4", "8")):
            return "1"  # 北京
        else:
            return "1"  # 默认上海
    
    async def fetch(self, target: str) -> Dict[str, Any]:
        """
        获取 A 股实时行情数据
        
        Args:
            target: 6位股票代码（如 "000001", "600000"）
        
        Returns:
            包含实时行情的字典
        """
        if not target.isdigit() or len(target) != 6:
            raise ValueError(f"Invalid A-share ticker: {target}. Must be 6 digits.")
        
        market_id = self._get_market_id(target)
        secid = f"{market_id}.{target}"
        
        # 构建请求参数
        params = {
            "secid": secid,
            "fields": ",".join([
                "f43",   # 最新价
                "f44",   # 最高价
                "f45",   # 最低价
                "f46",   # 今开
                "f47",   # 成交量（手）
                "f48",   # 成交额
                "f49",   # 量比
                "f50",   # 振幅
                "f51",   # 涨速
                "f52",   # 换手率
                "f55",   # 涨跌额
                "f169",  # 涨跌幅
                "f170",  # 涨跌幅（百分比）
                "f171",  # 5分钟涨速
                "f60",   # 昨收
                "f116",  # 总市值
                "f117",  # 流通市值
                "f124",  # 市净率
                "f162",  # 市盈率（动态）
                "f167",  # 市盈率（静态）
                "f105",  # 买一价
                "f106",  # 卖一价
                "f107",  # 买一量
                "f108",  # 卖一量
            ]),
            "ut": "fa5fd1943c7b386f1722cc9a789e88b6",  # 固定 token
            "_": int(datetime.now().timestamp() * 1000),  # 时间戳
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        
        async with httpx.AsyncClient(headers=headers, timeout=self.timeout) as client:
            try:
                response = await client.get(self.base_urls["quote"], params=params)
                response.raise_for_status()
                data = response.json()
                
                if data.get("rc") != 0 or not data.get("data"):
                    raise ValueError(f"EastMoney API error for {target}: {data.get('rt', 'Unknown error')}")
                
                # 同时获取北向资金数据（并行）
                north_flow_task = self._fetch_north_flow(client, target, market_id)
                
                # 等待北向资金数据
                north_flow_data = await north_flow_task
                
                return {
                    "quote": data["data"],
                    "north_flow": north_flow_data,
                    "ticker": target,
                    "market_id": market_id,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
            
            except httpx.HTTPStatusError as e:
                logger.error(f"[EastMoney] HTTP error for {target}: {e}")
                raise
            except Exception as e:
                logger.error(f"[EastMoney] Fetch error for {target}: {e}")
                raise
    
    async def _fetch_north_flow(
        self, 
        client: httpx.AsyncClient, 
        ticker: str, 
        market_id: str
    ) -> Dict[str, Any]:
        """
        获取北向资金流入流出数据
        
        Args:
            client: HTTP 客户端
            ticker: 股票代码
            market_id: 市场ID
        
        Returns:
            北向资金数据
        """
        secid = f"{market_id}.{ticker}"
        
        params = {
            "secid": secid,
            "klt": "101",  # 日K线
            "lmt": "30",   # 最近30天
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "_": int(datetime.now().timestamp() * 1000),
        }
        
        try:
            response = await client.get(self.base_urls["north_flow"], params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("rc") == 0 and data.get("data"):
                return data["data"]
            return {}
        
        except Exception as e:
            logger.warning(f"[EastMoney] North flow data fetch failed for {ticker}: {e}")
            return {}
    
    def _normalize(self, target: str, raw_data: Dict[str, Any]) -> MarketMoment:
        """
        标准化东方财富数据
        
        Args:
            target: 股票代码
            raw_data: 原始数据
        
        Returns:
            MarketMoment 标准化对象
        """
        try:
            quote_data = raw_data.get("quote", {})
            north_flow = raw_data.get("north_flow", {})
            
            # 解析实时行情
            latest_price = self._safe_divide(quote_data.get("f43", 0), 100)  # 价格放大了100倍
            high_price = self._safe_divide(quote_data.get("f44", 0), 100)
            low_price = self._safe_divide(quote_data.get("f45", 0), 100)
            open_price = self._safe_divide(quote_data.get("f46", 0), 100)
            
            volume = quote_data.get("f47", 0)  # 成交量（手）
            amount = quote_data.get("f48", 0)  # 成交额
            turnover_rate = self._safe_divide(quote_data.get("f52", 0), 100)  # 换手率
            change_pct = self._safe_divide(quote_data.get("f170", 0), 100)  # 涨跌幅
            
            # 市值数据
            total_mv = quote_data.get("f116", 0)  # 总市值
            circ_mv = quote_data.get("f117", 0)   # 流通市值
            
            # 估值指标
            pe_ratio = self._safe_divide(quote_data.get("f162", 0), 100)  # 动态市盈率
            pb_ratio = self._safe_divide(quote_data.get("f124", 0), 100)  # 市净率
            
            # 北向资金（最近一天）
            north_net_inflow = 0
            if north_flow and "klines" in north_flow:
                latest_kline = north_flow["klines"][-1] if north_flow["klines"] else None
                if latest_kline:
                    # 格式：日期,收盘价,涨跌幅,北向净买额,北向净流入,净流入占比,...
                    parts = latest_kline.split(",")
                    if len(parts) >= 5:
                        north_net_inflow = self._safe_float(parts[3])  # 北向净买额
            
            # 构建标准化 payload
            payload = {
                "ticker": target,
                "price": latest_price,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "volume": volume,
                "amount": amount,
                "turnover_rate": turnover_rate,
                "change_pct": change_pct,
                "total_mv": total_mv,
                "circ_mv": circ_mv,
                "pe_ratio": pe_ratio,
                "pb_ratio": pb_ratio,
                "north_net_inflow": north_net_inflow,
                "market": "CN-A",
                "currency": "CNY",
            }
            
            # 计算市场情绪指标
            sentiment_score = self._calculate_sentiment(
                change_pct=change_pct,
                turnover_rate=turnover_rate,
                north_inflow=north_net_inflow
            )
            
            return MarketMoment(
                source_name=self.name,
                category=self.category,
                payload=payload,
                marks_indicators={
                    "market_sentiment": sentiment_score,
                    "a_share_premium": self._calculate_a_share_premium(pb_ratio, pe_ratio),
                }
            )
        
        except Exception as e:
            logger.error(f"[EastMoney] Normalization failed for {target}: {e}")
            raise ValueError(f"Data normalization error: {e}")
    
    @staticmethod
    def _safe_divide(value: Any, divisor: float) -> float:
        """安全除法（避免除零错误）"""
        try:
            if value is None or value == 0:
                return 0.0
            return float(value) / divisor
        except (ValueError, TypeError):
            return 0.0
    
    @staticmethod
    def _safe_float(value: Any) -> float:
        """安全转换为浮点数"""
        try:
            if value is None or value == "-":
                return 0.0
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    
    @staticmethod
    def _calculate_sentiment(change_pct: float, turnover_rate: float, north_inflow: float) -> float:
        """
        计算市场情绪分数（0-1）
        
        规则：
        - 涨跌幅 > 5%: 0.8+
        - 涨跌幅 > 2%: 0.6+
        - 涨跌幅 < -5%: 0.2-
        - 涨跌幅 < -2%: 0.4-
        - 换手率 > 10%: 提升情绪
        - 北向资金净流入 > 0: 提升情绪
        """
        sentiment = 0.5  # 基准
        
        # 根据涨跌幅调整
        if change_pct > 5:
            sentiment = 0.85
        elif change_pct > 2:
            sentiment = 0.65
        elif change_pct > 0:
            sentiment = 0.55
        elif change_pct < -5:
            sentiment = 0.15
        elif change_pct < -2:
            sentiment = 0.35
        elif change_pct < 0:
            sentiment = 0.45
        
        # 换手率调整（高换手 = 活跃）
        if turnover_rate > 10:
            sentiment += 0.1
        elif turnover_rate > 5:
            sentiment += 0.05
        
        # 北向资金调整
        if north_inflow > 100_000_000:  # > 1亿
            sentiment += 0.1
        elif north_inflow > 10_000_000:  # > 1000万
            sentiment += 0.05
        
        return max(0.0, min(1.0, sentiment))
    
    @staticmethod
    def _calculate_a_share_premium(pb_ratio: float, pe_ratio: float) -> float:
        """
        计算 A 股溢价水平（0-1）
        
        规则：
        - PB < 1: 低估值（高溢价机会）
        - PE < 15: 低估值
        - PB > 5: 高估值
        - PE > 50: 高估值
        """
        if pb_ratio <= 0 or pe_ratio <= 0:
            return 0.5  # 无效数据返回中性
        
        # PB 分数（越低越好）
        pb_score = 1.0 - min(pb_ratio / 10.0, 1.0)  # PB=10 为满分，PB=0 为0分
        
        # PE 分数（越低越好）
        pe_score = 1.0 - min(pe_ratio / 100.0, 1.0)  # PE=100 为满分，PE=0 为0分
        
        # 综合分数
        premium = (pb_score + pe_score) / 2.0
        
        return max(0.0, min(1.0, premium))


# ─────────────────────────────────────────────
# 扩展：龙虎榜数据获取
# ─────────────────────────────────────────────

class EastMoneyLongHuboardDriver(BaseDataSource):
    """
    东方财富龙虎榜数据驱动器
    
    数据：
    - 机构买卖明细
    - 游资动向
    - 上榜原因
    - 买卖金额
    """
    
    def __init__(self, **config: Any):
        super().__init__(name="EastMoneyLongHu", category="Sentiment", **config)
        self.base_url = "https://datahub.eastmoney.com/lhb/data"
        self.timeout = config.get("timeout", 15.0)
    
    async def fetch(self, target: str) -> Dict[str, Any]:
        """获取龙虎榜数据"""
        # 实现龙虎榜数据获取逻辑
        # ...
        pass
    
    def _normalize(self, target: str, raw_data: Dict[str, Any]) -> MarketMoment:
        """标准化龙虎榜数据"""
        # 实现标准化逻辑
        # ...
        pass
