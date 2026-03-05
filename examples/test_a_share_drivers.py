"""
A股专用驱动器使用示例和测试
=====================================

展示如何使用 EastMoneyDriver 和 TushareDriver
"""
import asyncio
from datetime import datetime

from sea_invest.perception.eastmoney_driver import EastMoneyDriver
from sea_invest.perception.tushare_driver import TushareDriver
from sea_invest.perception.gateway import PerceptionGateway
from sea_invest.config import get_settings


async def test_eastmoney_driver():
    """测试东方财富驱动器"""
    print("\n" + "="*60)
    print("测试 EastMoneyDriver")
    print("="*60)
    
    # 初始化驱动器
    driver = EastMoneyDriver(timeout=10.0)
    
    # 测试股票：平安银行 (000001)
    ticker = "000001"
    
    try:
        print(f"\n获取股票数据: {ticker}")
        result = await driver.process(ticker)
        
        print("\n【标准化结果】")
        print(f"数据源: {result.source_name}")
        print(f"类别: {result.category}")
        print(f"\n核心数据:")
        print(f"  价格: {result.payload.get('price', 'N/A')}")
        print(f"  涨跌幅: {result.payload.get('change_pct', 'N/A')}%")
        print(f"  成交量: {result.payload.get('volume', 'N/A')}")
        print(f"  换手率: {result.payload.get('turnover_rate', 'N/A')}%")
        
        print(f"\n市场情绪指标:")
        for key, value in result.marks_indicators.items():
            print(f"  {key}: {value}")
        
    except Exception as e:
        print(f"❌ 错误: {e}")


async def test_tushare_driver():
    """测试 Tushare 驱动器"""
    print("\n" + "="*60)
    print("测试 TushareDriver")
    print("="*60)
    
    # 从配置获取 API Key
    settings = get_settings()
    
    if not settings.tushare_api_key:
        print("⚠️  警告: 未配置 TUSHARE_API_KEY")
        print("请在 .env 文件中设置: TUSHARE_API_KEY=your_token")
        print("获取 Token: https://tushare.pro/register")
        return
    
    # 初始化驱动器
    driver = TushareDriver(api_key=settings.tushare_api_key, timeout=10.0)
    
    # 测试股票：贵州茅台 (600519)
    ticker = "600519"
    
    try:
        print(f"\n获取股票数据: {ticker}")
        result = await driver.process(ticker)
        
        print("\n【标准化结果】")
        print(f"数据源: {result.source_name}")
        print(f"类别: {result.category}")
        print(f"\n核心数据:")
        print(f"  收盘价: {result.payload.get('close', 'N/A')}")
        print(f"  PE(TTM): {result.payload.get('pe_ttm', 'N/A')}")
        print(f"  PB: {result.payload.get('pb', 'N/A')}")
        print(f"  总市值: {result.payload.get('total_mv', 'N/A')} 亿")
        
        print(f"\n市场情绪指标:")
        for key, value in result.marks_indicators.items():
            print(f"  {key}: {value}")
        
    except Exception as e:
        print(f"❌ 错误: {e}")


async def test_batch_processing():
    """测试批量处理（使用 Gateway）"""
    print("\n" + "="*60)
    print("测试批量处理（Gateway）")
    print("="*60)
    
    # 初始化 Gateway
    gateway = PerceptionGateway()
    
    # 注册驱动器
    gateway.register(EastMoneyDriver(timeout=10.0))
    
    # 如果有 Tushare API Key，也注册
    settings = get_settings()
    if settings.tushare_api_key:
        gateway.register(TushareDriver(api_key=settings.tushare_api_key, timeout=10.0))
    
    # 批量获取多只股票
    tickers = ["000001", "600000", "000002"]  # 平安银行, 浦发银行, 万科A
    
    scan_plan = {
        "EastMoney": tickers,
    }
    
    if settings.tushare_api_key:
        scan_plan["Tushare"] = tickers
    
    print(f"\n批量获取 {len(tickers)} 只股票数据...")
    
    start_time = datetime.now()
    results = await gateway.collect_all(scan_plan)
    elapsed = (datetime.now() - start_time).total_seconds()
    
    print(f"\n✅ 完成! 耗时: {elapsed:.2f}秒")
    print(f"获取到 {len(results)} 个数据点")
    
    # 按股票分组显示
    ticker_data = {}
    for moment in results:
        ticker = moment.payload.get("ticker", "Unknown")
        if ticker not in ticker_data:
            ticker_data[ticker] = {}
        ticker_data[ticker][moment.source_name] = moment.payload
    
    print("\n【数据汇总】")
    for ticker, sources in ticker_data.items():
        print(f"\n{ticker}:")
        for source, data in sources.items():
            print(f"  {source}: 价格={data.get('price', data.get('close', 'N/A'))}")


async def test_a_share_premium_features():
    """测试 A 股特有功能（北向资金、融资融券等）"""
    print("\n" + "="*60)
    print("测试 A 股特有功能")
    print("="*60)
    
    driver = EastMoneyDriver(timeout=10.0)
    ticker = "000001"
    
    try:
        # 获取北向资金数据
        print(f"\n【北向资金】{ticker}")
        north_flow = await driver.fetch_north_flow(ticker)
        print(f"数据: {north_flow}")
        
        # 获取融资融券数据
        print(f"\n【融资融券】{ticker}")
        margin = await driver.fetch_margin(ticker)
        print(f"数据: {margin}")
        
    except Exception as e:
        print(f"❌ 错误: {e}")


async def main():
    """运行所有测试"""
    
    # 测试 1: 东方财富驱动器
    await test_eastmoney_driver()
    
    # 测试 2: Tushare 驱动器（需要 API Key）
    await test_tushare_driver()
    
    # 测试 3: 批量处理
    await test_batch_processing()
    
    # 测试 4: A 股特有功能
    # await test_a_share_premium_features()
    
    print("\n" + "="*60)
    print("✅ 所有测试完成!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
