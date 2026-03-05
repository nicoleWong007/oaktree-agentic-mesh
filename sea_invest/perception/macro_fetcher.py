"""
宏观数据获取器 (Macro Data Fetcher)
====================================

功能：
1. 统一的宏观数据获取接口
2. 支持多市场（美股、A股）
3. 自动缓存管理
4. 批量获取
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from sea_invest.perception.macro_cache import (
    MacroDataCache, 
    get_macro_cache, 
    Market, 
    MACRO_CONFIG
)
from sea_invest.perception.macro_driver import MacroDriver
from sea_invest.config import get_settings


# ─────────────────────────────────────────────
# 美股宏观数据获取器（FRED）
# ─────────────────────────────────────────────

class USMacroFetcher:
    """美股宏观数据获取器（使用 FRED API）"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_settings().fred_api_key
        self.driver = MacroDriver(timeout=15.0, api_key=self.api_key)
    
    async def fetch_batch(self, indicators: List[str]) -> Dict[str, float]:
        """
        批量获取美股宏观数据
        
        Args:
            indicators: 指标列表（如 ["FEDFUNDS", "CPIAUCSL"]）
        
        Returns:
            {"FEDFUNDS": 5.25, "CPIAUCSL": 3.2, ...}
        """
        results = {}
        
        # 并行获取所有指标
        tasks = [self.driver.process(indicator) for indicator in indicators]
        
        try:
            moments = await asyncio.gather(*tasks, return_exceptions=True)
            
            for indicator, moment in zip(indicators, moments):
                if isinstance(moment, Exception):
                    logger.error(f"[USMacro] Failed to fetch {indicator}: {moment}")
                    continue
                
                value = moment.payload.get("value")
                if value is not None:
                    results[indicator] = float(value)
        
        except Exception as e:
            logger.error(f"[USMacro] Batch fetch error: {e}")
        
        return results


# ─────────────────────────────────────────────
# A股宏观数据获取器（中国）
# ─────────────────────────────────────────────

class CNAMacroFetcher:
    """A股宏观数据获取器（使用中国官方数据源）"""
    
    def __init__(self):
        # 可以扩展支持多个数据源（人民银行、统计局等）
        pass
    
    async def fetch_batch(self, indicators: List[str]) -> Dict[str, float]:
        """
        批量获取A股宏观数据
        
        Args:
            indicators: 指标列表（如 ["SHIBOR", "M2", "PMI"]）
        
        Returns:
            {"SHIBOR": 2.5, "M2": 12.3, ...}
        """
        results = {}
        
        # 并行获取所有指标
        tasks = [self._fetch_single(indicator) for indicator in indicators]
        
        try:
            values = await asyncio.gather(*tasks, return_exceptions=True)
            
            for indicator, value in zip(indicators, values):
                if isinstance(value, Exception):
                    logger.error(f"[CNAMacro] Failed to fetch {indicator}: {value}")
                    continue
                
                if value is not None:
                    results[indicator] = float(value)
        
        except Exception as e:
            logger.error(f"[CNAMacro] Batch fetch error: {e}")
        
        return results
    
    async def _fetch_single(self, indicator: str) -> Optional[float]:
        """
        获取单个指标（模拟实现，实际应调用真实 API）
        
        数据源：
        - SHIBOR: http://www.shibor.org/
        - M2/PMI/CPI/PPI: http://www.stats.gov.cn/
        - LPR: http://www.pbc.gov.cn/
        """
        # 模拟数据（实际应调用真实 API）
        mock_data = {
            "SHIBOR": 2.45,
            "LPR_1Y": 3.45,
            "LPR_5Y": 4.20,
            "M2": 12.5,
            "PMI": 49.2,
            "CPI_CN": 0.2,
            "PPI": -2.5,
        }
        
        # 模拟网络延迟
        await asyncio.sleep(0.1)
        
        value = mock_data.get(indicator)
        if value is None:
            logger.warning(f"[CNAMacro] No mock data for {indicator}")
            return None
        
        logger.debug(f"[CNAMacro] Fetched {indicator}: {value}")
        return value


# ─────────────────────────────────────────────
# 统一宏观数据管理器
# ─────────────────────────────────────────────

class MacroDataManager:
    """
    统一宏观数据管理器
    
    功能：
    - 自动选择市场对应的获取器
    - 自动缓存管理
    - 批量获取
    """
    
    def __init__(self, cache: Optional[MacroDataCache] = None):
        self.cache = cache or get_macro_cache()
        
        # 初始化各市场获取器
        self._fetchers = {
            Market.US: USMacroFetcher(),
            Market.CN_A: CNAMacroFetcher(),
        }
    
    async def get_macro_data(self, market: Market) -> Dict[str, float]:
        """
        获取某个市场的所有宏观数据（自动缓存）
        
        Args:
            market: 市场类型
        
        Returns:
            {"FEDFUNDS": 5.25, "CPIAUCSL": 3.2, ...}
        """
        # 获取该市场的指标列表
        indicators = list(MACRO_CONFIG.get(market, {}).keys())
        
        if not indicators:
            logger.warning(f"[MacroManager] No indicators configured for {market}")
            return {}
        
        # 从缓存获取（如果未过期）
        # 如果有过期的，批量刷新
        return await self.cache.refresh_batch(
            market=market,
            indicators=indicators,
            fetch_func=self._fetch_batch
        )
    
    async def _fetch_batch(
        self, 
        market: Market, 
        indicators: List[str]
    ) -> Dict[str, float]:
        """
        批量获取宏观数据（内部方法）
        
        Args:
            market: 市场类型
            indicators: 指标列表
        
        Returns:
            {"FEDFUNDS": 5.25, ...}
        """
        fetcher = self._fetchers.get(market)
        
        if not fetcher:
            logger.error(f"[MacroManager] No fetcher for market: {market}")
            return {}
        
        # 调用对应市场的获取器
        logger.info(f"[MacroManager] Fetching {len(indicators)} indicators for {market}")
        
        data = await fetcher.fetch_batch(indicators)
        
        logger.info(f"[MacroManager] Fetched {len(data)}/{len(indicators)} indicators for {market}")
        
        return data
    
    async def get_single(self, market: Market, indicator: str) -> Optional[float]:
        """
        获取单个指标（自动缓存）
        
        Args:
            market: 市场类型
            indicator: 指标名称
        
        Returns:
            指标值或 None
        """
        # 检查缓存
        cached = self.cache.get(market, indicator)
        if cached is not None:
            return cached["value"]
        
        # 需要刷新
        data = await self._fetch_batch(market, [indicator])
        return data.get(indicator)


# ─────────────────────────────────────────────
# 便捷函数
# ─────────────────────────────────────────────

async def get_us_macro_data() -> Dict[str, float]:
    """获取美股宏观数据（便捷函数）"""
    manager = MacroDataManager()
    return await manager.get_macro_data(Market.US)


async def get_cna_macro_data() -> Dict[str, float]:
    """获取A股宏观数据（便捷函数）"""
    manager = MacroDataManager()
    return await manager.get_macro_data(Market.CN_A)


# ─────────────────────────────────────────────
# 测试
# ─────────────────────────────────────────────

async def test_macro_data_manager():
    """测试宏观数据管理器"""
    print("\n" + "="*60)
    print("测试宏观数据管理器")
    print("="*60)
    
    manager = MacroDataManager()
    
    # 测试 1: 获取美股宏观数据
    print("\n【测试 1】获取美股宏观数据")
    us_macro = await manager.get_macro_data(Market.US)
    print(f"获取到 {len(us_macro)} 个指标:")
    for key, value in us_macro.items():
        print(f"  {key}: {value}")
    
    # 测试 2: 再次获取（应该使用缓存）
    print("\n【测试 2】再次获取美股宏观数据（应该使用缓存）")
    us_macro_2 = await manager.get_macro_data(Market.US)
    print(f"获取到 {len(us_macro_2)} 个指标")
    
    # 测试 3: 获取A股宏观数据
    print("\n【测试 3】获取A股宏观数据")
    cna_macro = await manager.get_macro_data(Market.CN_A)
    print(f"获取到 {len(cna_macro)} 个指标:")
    for key, value in cna_macro.items():
        print(f"  {key}: {value}")
    
    print("\n✅ 测试完成")


if __name__ == "__main__":
    asyncio.run(test_macro_data_manager())
