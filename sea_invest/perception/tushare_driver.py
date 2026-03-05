"""
Tushare 数据驱动器 (Tushare Pro API)
======================================

数据源：
- 财务报表（资产负债表、利润表、现金流量表）
- 业绩预告
- 分红送转
- 技术指标
- 股东结构
- 行业数据
- 指数数据

API 文档：
- https://tushare.pro/document/2
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from sea_invest.perception.base import BaseDataSource
from sea_invest.perception.schema import MarketMoment
from sea_invest.config import get_settings


class TushareDriver(BaseDataSource):
    """
    Tushare Pro 数据驱动器
    
    特点：
    - 需要注册获取 API Token（https://tushare.pro/register）
    - 数据全面（财务、行情、技术指标）
    - 更新及时（日/周频次）
    - 支持积分获取
    """
    
    def __init__(self, api_key: Optional[str] = None, **config: Any):
        super().__init__(name="Tushare", category="Fundamental", **config)
        
        # 从配置获取 API Key
        self.api_key = api_key or get_settings().tushare_api_key
        self.base_url = "http://api.tushare.pro"
        self.timeout = config.get("timeout", 15.0)
        
        # 缓存（避免重复请求）
        self._cache: Dict[str, Any] = {}
        self._cache_time: Dict[str, datetime] = {}
        
        if not self.api_key:
            logger.warning("[Tushare] No API key provided. Set TUSHARE_API_KEY in .env")
    
    def _get_ts_code(self, ticker: str) -> str:
        """
        将股票代码转换为 Tushare 格式（ts_code）
        
        规则：
        - 上海: 600000.SH
        - 深圳: 000001.SZ
        - 北京: 430047.BJ
        """
        if not ticker or not ticker.isdigit():
            raise ValueError(f"Invalid ticker: {ticker}")
        
        # 根据股票代码识别交易所
        if ticker.startswith("6"):
            return f"{ticker}.SH"
        elif ticker.startswith(("1", "3")):
            return f"{ticker}.SZ"
        elif ticker.startswith(("4", "8")):
            return f"{ticker}.BJ"
        else:
            return f"{ticker}.SH"  # 默认上海
    
    async def fetch(self, target: str) -> Dict[str, Any]:
        """
        获取股票基本面数据（财务报表 + 技术指标）
        
        Args:
            target: 6位股票代码（如 "000001", "600000"）
        
        Returns:
            包含财务和技术指标的字典
        """
        ts_code = self._get_ts_code(target)
        
        # 检查缓存（1小时有效期）
        cache_key = f"{target}_basic"
        if cache_key in self._cache:
            cache_time = self._cache_time.get(cache_key)
            if cache_time and (datetime.now() - cache_time).total_seconds() < 3600:  # 1小时内有效
                logger.debug(f"[Tushare] Using cached data for {target}")
                return self._cache[cache_key]
        
        # 调用 Tushare API
        payload = {
            "api_name": "daily_basic",
            "token": self.api_key,
            "params": {
                "ts_code": ts_code,
                "trade_date": datetime.now().strftime("%Y%m%d"),
            },
            "fields": "ts_code,trade_date,close,turn,turnover_rate,volume_ratio,pe_ttm,pe,pb,ps,total_mv,circ_mv"
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        
        async with httpx.AsyncClient(headers=headers, timeout=self.timeout) as client:
            response = await client.post(
                self.base_url,
                json=payload
            )
            
            # 检查响应
            if response.status_code != 200:
                error_msg = response.json().get("msg", "Unknown error")
                logger.error(f"[Tushare] API error: {response.status_code} - {error_msg}")
                
                # 如果是 token 无效，返回错误
                if "token" in response.json().get("msg", ""):
                    raise ValueError(f"Invalid Tushare API token: {response.json()['msg']}")
                
                # 返回错误
                raise httpx.HTTPStatusError(
                    f"Tushare API request failed: {response.status_code}"
                )
            
            data = response.json()
            
            # 缓存结果
            self._cache[cache_key] = data
            self._cache_time[cache_key] = datetime.now()
            
            return data
    
    def _normalize(self, target: str, raw_data: Dict[str, Any]) -> MarketMoment:
        """
        标准化股票基本面数据
        
        Args:
            target: 股票代码
            raw_data: Tushare API 返回的原始数据
        
        Returns:
            MarketMoment 标准化对象
        """
        try:
            # 解析 Tushare API 响应
            data_list = raw_data.get("data", {}).get("items", [])
            
            if not data_list:
                logger.warning(f"[Tushare] No data found for {target}")
                return self._create_empty_moment(target)
            
            # 取第一条数据（最新交易日）
            latest_data = data_list[0] if data_list else {}
            
            # 提取关键字段（转换为浮点数）
            def safe_float(value: Any) -> Optional[float]:
                if value is None or value == "" or value == "None":
                    return None
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
            
            # 构建标准化数据
            payload = {
                "ticker": target,
                "trade_date": latest_data.get("trade_date"),
                
                # 价格相关
                "close": safe_float(latest_data.get("close")),
                "turn": safe_float(latest_data.get("turn")),
                "pct_chg": safe_float(latest_data.get("pct_chg")),
                
                # 成交量相关
                "volume": safe_float(latest_data.get("vol")),
                "amount": safe_float(latest_data.get("amount")),
                "turnover_rate": safe_float(latest_data.get("turnover_rate")),
                
                # 估值指标
                "pe_ttm": safe_float(latest_data.get("pe_ttm")),
                "pe": safe_float(latest_data.get("pe")),
                "pb": safe_float(latest_data.get("pb")),
                "ps": safe_float(latest_data.get("ps")),
                
                # 市值相关
                "total_mv": safe_float(latest_data.get("total_mv")),
                "circ_mv": safe_float(latest_data.get("circ_mv")),
            }
            
            return MarketMoment(
                source_name=self.name,
                category=self.category,
                payload=payload,
                marks_indicators={
                    "valuation_level": self._calculate_valuation_level(payload),
                    "liquidity": self._calculate_liquidity(payload)
                }
            )
        
        except Exception as e:
            logger.error(f"[Tushare] Normalization failed for {target}: {e}")
            raise
    
    def _create_empty_moment(self, target: str) -> MarketMoment:
        """创建空的 MarketMoment（数据缺失时）"""
        return MarketMoment(
            source_name=self.name,
            category=self.category,
            payload={"ticker": target, "error": "No data available"},
            marks_indicators={}
        )
    
    @staticmethod
    def _calculate_valuation_level(data: Dict) -> float:
        """计算估值水平（0-1）"""
        pe_ttm = data.get("pe_ttm")
        
        if not pe_ttm:
            return 0.5  # 默认中性
        
        # 估值评分逻辑
        if pe_ttm < 10:
            return 0.0  # 低估值
        elif pe_ttm < 20:
            return 1.5  # 合理估值
        elif pe_ttm < 30:
            return 1.0  # 偏高估值
        else:
            return 0.0  # 高估值
    
    @staticmethod
    def _calculate_liquidity(data: Dict) -> float:
        """计算流动性（0-1）"""
        turnover_rate = data.get("turnover_rate")
        
        if not turnover_rate:
            return 1.5  # 默认中性
        
        # 流动性评分逻辑
        if turnover_rate < 2:
            return 1.0  # 高流动性
        elif turnover_rate < 5:
            return 1.5  # 中等流动性
        elif turnover_rate < 10:
            return 1.0  # 低流动性
        else:
            return 1.0  # 极低流动性


# ─────────────────────────────────────────────
# 扩展：获取财务报表数据
# ─────────────────────────────────────────────
    
    async def fetch_financial_report(self, ticker: str) -> Dict[str, Any]:
        """
        获取股票财务报表数据
        
        Args:
            ticker: 6位股票代码
        
        Returns:
            包含资产负债表、利润表、现金流量的字典
        """
        ts_code = self._get_ts_code(ticker)
        
        payload = {
            "api_name": "income",
            "token": self.api_key,
            "params": {
                "ts_code": ts_code,
                "ann_type": "1",  # 1=年报，3=季报
            },
            "fields": "ts_code,ann_date,f_revenue,f_operate_profit,total_profit,n_income,cfps"
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        
        async with httpx.AsyncClient(headers=headers, timeout=self.timeout) as client:
            response = await client.post(
                self.base_url,
                json=payload
            )
            
            return response.json()
    
    @staticmethod
    def normalize_financial_report(ticker: str, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """标准化财务报表数据"""
        data_list = raw_data.get("data", {}).get("items", [])
        
        if not data_list:
            return {}
        
        latest_data = data_list[0]
        
        return {
            "ticker": ticker,
            "ann_date": latest_data.get("ann_date"),
            "revenue": latest_data.get("f_revenue"),
            "operate_profit": latest_data.get("f_operate_profit"),
            "net_profit": latest_data.get("n_income"),
            "cash_flow": latest_data.get("c_fps")
        }
