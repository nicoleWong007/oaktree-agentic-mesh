"""
宏观数据缓存管理器 (Macro Data Cache Manager)
==============================================

功能：
1. 本地缓存宏观数据（避免重复 API 调用）
2. 根据更新频次自动刷新（每日/月度）
3. 支持多市场（美股、A股）
4. 线程安全

设计原则：
- 宏观数据同一市场只获取一次
- 根据指标类型判断是否需要刷新
- 提供统一的获取接口
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Literal
from enum import Enum

from loguru import logger


class Market(str, Enum):
    """市场类型"""
    US = "us"      # 美股
    CN_A = "cn_a"  # A股
    HK = "hk"      # 港股


class UpdateFrequency(str, Enum):
    """更新频次"""
    DAILY = "daily"      # 每日更新
    MONTHLY = "monthly"  # 月度更新


# ─────────────────────────────────────────────
# 宏观数据配置
# ─────────────────────────────────────────────

MACRO_CONFIG = {
    # 美股宏观指标（FRED）
    Market.US: {
        "FEDFUNDS": {
            "name": "联邦基金利率",
            "frequency": UpdateFrequency.DAILY,
            "source": "FRED",
            "description": "Federal Funds Effective Rate"
        },
        "GS10": {
            "name": "10年期国债收益率",
            "frequency": UpdateFrequency.DAILY,
            "source": "FRED",
            "description": "10-Year Treasury Constant Maturity Rate"
        },
        "T10Y2Y": {
            "name": "2年期-10年期国债利差",
            "frequency": UpdateFrequency.DAILY,
            "source": "FRED",
            "description": "10-Year Treasury Minus 2-Year Treasury"
        },
        "BAMLH0A0HYM2": {
            "name": "高收益债利差",
            "frequency": UpdateFrequency.DAILY,
            "source": "FRED",
            "description": "ICE BofA US High Yield Index Option-Adjusted Spread"
        },
        "VIXCLS": {
            "name": "VIX波动率指数",
            "frequency": UpdateFrequency.DAILY,
            "source": "FRED",
            "description": "CBOE Volatility Index (VIX)"
        },
        "CPIAUCSL": {
            "name": "CPI消费者物价指数",
            "frequency": UpdateFrequency.MONTHLY,
            "source": "FRED",
            "description": "Consumer Price Index for All Urban Consumers",
            "release_day": 13  # 通常每月13日发布
        },
        "UNRATE": {
            "name": "失业率",
            "frequency": UpdateFrequency.MONTHLY,
            "source": "FRED",
            "description": "Unemployment Rate",
            "release_weekday": 4  # 每月第一个周五（0=周一，4=周五）
        },
    },
    
    # A股宏观指标（中国）
    Market.CN_A: {
        "SHIBOR": {
            "name": "上海银行间同业拆借利率",
            "frequency": UpdateFrequency.DAILY,
            "source": "PBOC",
            "description": "Shanghai Interbank Offered Rate"
        },
        "LPR": {
            "name": "贷款市场报价利率",
            "frequency": UpdateFrequency.MONTHLY,
            "source": "PBOC",
            "description": "Loan Prime Rate",
            "release_day": 20  # 每月20日发布
        },
        "M2": {
            "name": "货币供应量",
            "frequency": UpdateFrequency.MONTHLY,
            "source": "PBOC",
            "description": "Money Supply M2",
            "release_day_range": (10, 15)  # 每月10-15日发布
        },
        "PMI": {
            "name": "采购经理人指数",
            "frequency": UpdateFrequency.MONTHLY,
            "source": "NBS",
            "description": "Purchasing Managers' Index",
            "release_day": 1  # 每月1日发布
        },
        "CPI_CN": {
            "name": "消费者物价指数（中国）",
            "frequency": UpdateFrequency.MONTHLY,
            "source": "NBS",
            "description": "Consumer Price Index (China)",
            "release_day_range": (9, 10)  # 每月9-10日发布
        },
        "PPI": {
            "name": "生产者物价指数",
            "frequency": UpdateFrequency.MONTHLY,
            "source": "NBS",
            "description": "Producer Price Index",
            "release_day_range": (9, 10)  # 每月9-10日发布
        },
    },
}


# ─────────────────────────────────────────────
# 宏观数据缓存类
# ─────────────────────────────────────────────

class MacroDataCache:
    """
    宏观数据缓存管理器
    
    特点：
    - 线程安全
    - 自动过期检查
    - 支持文件持久化
    - 支持多市场
    """
    
    def __init__(self, cache_dir: str = "./data/macro_cache"):
        """
        初始化缓存管理器
        
        Args:
            cache_dir: 缓存文件目录
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存缓存
        # 结构: {market: {indicator: {"value": float, "updated_at": datetime}}}
        self._cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
        
        # 线程锁
        self._lock = threading.RLock()
        
        # 从文件加载缓存
        self._load_from_disk()
        
        logger.info(f"[MacroCache] Initialized with cache_dir={cache_dir}")
    
    def _get_cache_file(self, market: Market) -> Path:
        """获取市场对应的缓存文件路径"""
        return self.cache_dir / f"macro_{market.value}.json"
    
    def _load_from_disk(self):
        """从磁盘加载缓存"""
        for market in Market:
            cache_file = self._get_cache_file(market)
            
            if not cache_file.exists():
                continue
            
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # 解析时间
                for indicator, entry in data.items():
                    if "updated_at" in entry:
                        entry["updated_at"] = datetime.fromisoformat(entry["updated_at"])
                
                self._cache[market.value] = data
                logger.info(f"[MacroCache] Loaded {len(data)} indicators for {market.value}")
            
            except Exception as e:
                logger.warning(f"[MacroCache] Failed to load cache for {market.value}: {e}")
    
    def _save_to_disk(self, market: Market):
        """保存缓存到磁盘"""
        cache_file = self._get_cache_file(market)
        
        try:
            # 序列化时间
            data = self._cache.get(market.value, {})
            serializable_data = {}
            
            for indicator, entry in data.items():
                serializable_entry = entry.copy()
                if "updated_at" in serializable_entry and isinstance(serializable_entry["updated_at"], datetime):
                    serializable_entry["updated_at"] = serializable_entry["updated_at"].isoformat()
                serializable_data[indicator] = serializable_entry
            
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(serializable_data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"[MacroCache] Saved cache for {market.value}")
        
        except Exception as e:
            logger.error(f"[MacroCache] Failed to save cache for {market.value}: {e}")
    
    def _is_stale(self, market: Market, indicator: str) -> bool:
        """
        检查数据是否过期
        
        Args:
            market: 市场类型
            indicator: 指标名称
        
        Returns:
            True=已过期需要更新，False=仍然有效
        """
        # 获取指标配置
        config = MACRO_CONFIG.get(market, {}).get(indicator)
        if not config:
            return True  # 未知指标，默认过期
        
        # 检查缓存是否存在
        cache_entry = self._cache.get(market.value, {}).get(indicator)
        if not cache_entry:
            return True  # 无缓存，需要获取
        
        updated_at = cache_entry.get("updated_at")
        if not updated_at:
            return True  # 无更新时间，需要获取
        
        # 计算过期时间
        now = datetime.now()
        frequency = config["frequency"]
        
        if frequency == UpdateFrequency.DAILY:
            # 每日更新：检查是否同一天
            # 如果是工作日，且距离上次更新超过1天，则需要更新
            # 注意：周末和节假日不发布数据
            if (now - updated_at).days >= 1:
                # 简单判断：超过1天就更新（实际应该考虑节假日）
                return True
        
        elif frequency == UpdateFrequency.MONTHLY:
            # 月度更新：检查是否同一个月
            # 如果当前月份 != 上次更新月份，则需要更新
            if now.month != updated_at.month or now.year != updated_at.year:
                return True
            
            # 额外检查：如果当前日期已过发布日期，但缓存是上个月的，需要更新
            release_day = config.get("release_day")
            release_day_range = config.get("release_day_range")
            
            if release_day and now.day >= release_day:
                # 已过发布日，如果缓存是上个月的，需要更新
                cache_month = updated_at.month
                current_month = now.month
                
                if cache_month != current_month:
                    return True
            
            elif release_day_range:
                # 发布日期范围（如10-15日）
                start_day, end_day = release_day_range
                if start_day <= now.day <= end_day:
                    # 在发布窗口期，检查缓存是否是上个月的
                    cache_month = updated_at.month
                    current_month = now.month
                    
                    if cache_month != current_month:
                        return True
        
        return False  # 未过期
    
    def get(
        self, 
        market: Market, 
        indicator: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取宏观数据（如果未过期）
        
        Args:
            market: 市场类型
            indicator: 指标名称
        
        Returns:
            {"value": float, "updated_at": datetime} 或 None
        """
        with self._lock:
            if self._is_stale(market, indicator):
                return None
            
            return self._cache.get(market.value, {}).get(indicator)
    
    def set(
        self, 
        market: Market, 
        indicator: str, 
        value: float,
        updated_at: Optional[datetime] = None
    ):
        """
        设置宏观数据
        
        Args:
            market: 市场类型
            indicator: 指标名称
            value: 指标值
            updated_at: 更新时间（默认当前时间）
        """
        with self._lock:
            if market.value not in self._cache:
                self._cache[market.value] = {}
            
            self._cache[market.value][indicator] = {
                "value": value,
                "updated_at": updated_at or datetime.now(),
                "source": MACRO_CONFIG.get(market, {}).get(indicator, {}).get("source", "Unknown")
            }
            
            # 保存到磁盘
            self._save_to_disk(market)
            
            logger.info(f"[MacroCache] Updated {market.value}/{indicator}: {value}")
    
    def get_all(self, market: Market) -> Dict[str, float]:
        """
        获取某个市场的所有宏观数据（仅返回值）
        
        Args:
            market: 市场类型
        
        Returns:
            {"FEDFUNDS": 5.25, "CPIAUCSL": 3.2, ...}
        """
        with self._lock:
            cache = self._cache.get(market.value, {})
            return {
                indicator: entry["value"]
                for indicator, entry in cache.items()
            }
    
    def refresh_if_stale(
        self, 
        market: Market, 
        indicator: str,
        fetch_func
    ) -> float:
        """
        如果数据过期，则刷新
        
        Args:
            market: 市场类型
            indicator: 指标名称
            fetch_func: 获取数据的函数（async callable）
        
        Returns:
            指标值（从缓存或新获取）
        """
        with self._lock:
            # 检查缓存
            cached = self.get(market, indicator)
            if cached is not None:
                logger.debug(f"[MacroCache] Using cached {market.value}/{indicator}")
                return cached["value"]
            
            # 需要刷新
            logger.info(f"[MacroCache] Refreshing {market.value}/{indicator}")
            
            # 调用获取函数
            value = fetch_func(indicator)
            
            # 更新缓存
            self.set(market, indicator, value)
            
            return value
    
    async def refresh_batch(
        self, 
        market: Market, 
        indicators: List[str],
        fetch_func
    ) -> Dict[str, float]:
        """
        批量刷新宏观数据（异步）
        
        Args:
            market: 市场类型
            indicators: 指标列表
            fetch_func: 批量获取数据的函数（async callable）
        
        Returns:
            {"FEDFUNDS": 5.25, "CPIAUCSL": 3.2, ...}
        """
        with self._lock:
            # 找出需要刷新的指标
            stale_indicators = [
                ind for ind in indicators
                if self._is_stale(market, ind)
            ]
            
            if not stale_indicators:
                # 全部未过期，直接返回缓存
                logger.info(f"[MacroCache] All {market.value} indicators are fresh")
                return self.get_all(market)
            
            # 需要刷新
            logger.info(f"[MacroCache] Refreshing {len(stale_indicators)} {market.value} indicators")
            
            # 调用批量获取函数
            new_data = await fetch_func(market, stale_indicators)
            
            # 更新缓存
            for indicator, value in new_data.items():
                self.set(market, indicator, value)
            
            # 返回所有数据（包括未过期的）
            return self.get_all(market)
    
    def clear(self, market: Optional[Market] = None):
        """
        清空缓存
        
        Args:
            market: 市场类型（None=清空所有）
        """
        with self._lock:
            if market:
                self._cache.pop(market.value, None)
                cache_file = self._get_cache_file(market)
                if cache_file.exists():
                    cache_file.unlink()
                logger.info(f"[MacroCache] Cleared cache for {market.value}")
            else:
                self._cache.clear()
                for m in Market:
                    cache_file = self._get_cache_file(m)
                    if cache_file.exists():
                        cache_file.unlink()
                logger.info("[MacroCache] Cleared all cache")


# ─────────────────────────────────────────────
# 全局单例
# ─────────────────────────────────────────────

_macro_cache: Optional[MacroDataCache] = None
_macro_cache_lock = threading.Lock()


def get_macro_cache() -> MacroDataCache:
    """获取全局宏观数据缓存实例"""
    global _macro_cache
    
    if _macro_cache is None:
        with _macro_cache_lock:
            if _macro_cache is None:
                _macro_cache = MacroDataCache()
    
    return _macro_cache
