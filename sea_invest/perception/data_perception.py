"""
Data Perception Layer - Entrypoint and Testing
(Refactored into schema, base, drivers, and gateway modules)
"""
import asyncio
from loguru import logger

from sea_invest.perception.yahoo_driver import YahooFinanceDriver
from sea_invest.perception.macro_driver import MacroDriver
from sea_invest.perception.gateway import PerceptionGateway

async def main():
    # 为了直观看到请求流程，可在这里初始化并定义日志等级
    # 1. 实例化驱动程序及感知网关
    yahoo = YahooFinanceDriver(timeout=5.0)
    macro = MacroDriver(timeout=5.0, api_key="demo")
    gateway = PerceptionGateway()
    
    # 2. 将驱动器装载进插槽 (Pluggable Architecture)
    gateway.register(yahoo)
    gateway.register(macro)
    
    # 3. 指定感知抓取计划 
    scan_plan = {
        "YahooFinance": ["AAPL", "MSFT", "TSLA"],
        "FREDMacro": ["FEDFUNDS", "CPIAUCSL", "BAMLH0A0HYM2"],
    }
    
    # 4. 一键执行并发收集（并发量与限速需要依托底层的 asyncio/httpx 连接池配置）
    print("\n--- initiating Fetch Routine ---")
    data_lake_feed = await gateway.collect_all(scan_plan)
    
    # 5. 分析沉淀的数据快照
    print("\n--- Gathered and Normalized Records ---")
    for row in data_lake_feed:
        # Pydantic 提供的 model_dump_json 可以很优美地序列化为 JSON 字符串
        print(row.model_dump_json(indent=2))

if __name__ == "__main__":
    import sys
    # 重置 Loguru 日志格式，适配直观的控制台输出体验
    logger.remove()
    logger.add(sys.stderr, format="<green>{time:HH:mm:ss.SS}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>")
    
    # 通过 asyncio 事件循环运行示例
    asyncio.run(main())
