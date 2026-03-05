import asyncio
from typing import Dict, List

from loguru import logger

from sea_invest.perception.base import BaseDataSource
from sea_invest.perception.schema import MarketMoment


class PerceptionGateway:
    """
    感知中枢层 Gateway：
    屏蔽所有具体的 Driver 映射实现细节；通过高并发统一回收外界系统的感知信号。
    """

    def __init__(self):
        # 驱动程序注册表
        self._drivers: Dict[str, BaseDataSource] = {}

    def register(self, driver: BaseDataSource) -> None:
        """向感知网关挂载一个新的驱动器。"""
        self._drivers[driver.name] = driver
        logger.info(f"[Gateway] Plugin Registered successfully: {driver.name}")

    def unregister(self, driver_name: str) -> None:
        """从感知网关卸载或移除指定的驱动器。"""
        if driver_name in self._drivers:
            del self._drivers[driver_name]
            logger.info(f"[Gateway] Plugin Unregistered successfully: {driver_name}")
        else:
            logger.warning(f"[Gateway] Attempted to unregister a missing plugin: {driver_name}")

    async def _collect_from_driver(self, driver: BaseDataSource, targets: List[str]) -> List[MarketMoment]:
        """
        调度单一底层 Driver 去并行地吃下它该抓取的所有 Targets（比如多支股票），
        并做到容错隔离（某只股票失败不影响其他的）。
        """
        coroutines = [driver.process(t) for t in targets]
        # return_exceptions=True 保证一损不俱损
        driver_results = await asyncio.gather(*coroutines, return_exceptions=True)
        
        valid_moments = []
        for target, res in zip(targets, driver_results):
            if isinstance(res, Exception):
                logger.error(f"[Gateway] Processing Fault on {driver.name} for target '{target}': {str(res)}")
            else:
                valid_moments.append(res)
        return valid_moments

    async def collect_all(self, plan: Dict[str, List[str]]) -> List[MarketMoment]:
        """
        发起一次大宽带的并发扫描：对所有被规划到的 Driver 一起下达收集指令。
        
        Args:
            plan: { "驱动源名称": ["抓取目标1", "抓取目标2"] }
                  如 {"YahooFinance": ["AAPL", "MSFT"]}
        
        Returns:
            混合所有驱动来源抓取并映射完毕后的 MarketMoment 标准数据流集合。
        """
        gather_tasks = []
        
        for driver_name, target_list in plan.items():
            driver = self._drivers.get(driver_name)
            if not driver:
                logger.warning(f"[Gateway] Ignored unresolved Driver dependency: {driver_name}")
                continue
            
            gather_tasks.append(self._collect_from_driver(driver, target_list))

        logger.info("[Gateway] Ignition! Blasting parallel data acquisitions...")
        
        # 等待所有驱动、所有请求全部执行完毕
        bulk_results = await asyncio.gather(*gather_tasks)
        
        # 将二维的结果列表展平为一维
        flattened_feed = [moment for driver_slice in bulk_results for moment in driver_slice]
        
        logger.info(f"[Gateway] Mission accomplished. Secured {len(flattened_feed)} robust MarketMoment(s).")
        return flattened_feed
