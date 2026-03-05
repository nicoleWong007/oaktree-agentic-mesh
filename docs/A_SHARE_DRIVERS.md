# A 股专用驱动器使用文档

## 📋 概述

本项目新增了两个 A 股专用数据驱动器：
- **EastMoneyDriver**: 东方财富数据驱动器（免费，无需认证）
- **TushareDriver**: Tushare Pro API 驱动器（需要注册获取 API Token）

## 🎯 功能对比

| 功能 | EastMoneyDriver | TushareDriver |
|------|----------------|---------------|
| **数据源** | 东方财富网 | Tushare Pro API |
| **认证** | ❌ 无需 | ✅ 需要 API Token |
| **费用** | 🆓 免费 | 💰 免费额度 + 付费 |
| **数据范围** | 实时行情、龙虎榜、北向资金、融资融券 | 财务报表、技术指标、股东结构 |
| **更新频率** | 实时（盘中） | 日度/周度 |
| **历史数据** | ❌ 有限 | ✅ 丰富（10年+） |
| **推荐场景** | 短线交易、情绪分析 | 基本面分析、量化研究 |

## 🚀 快速开始

### 1. EastMoneyDriver（无需配置）

```python
from sea_invest.perception.eastmoney_driver import EastMoneyDriver

# 初始化驱动器
driver = EastMoneyDriver(timeout=15.0)

# 获取股票数据（平安银行）
result = await driver.process("000001")

# 查看结果
print(result.payload["price"])  # 当前价格
print(result.payload["change_pct"])  # 涨跌幅
```

### 2. TushareDriver（需要 API Key）

#### 步骤 1: 获取 API Token

1. 访问 https://tushare.pro/register
2. 注册账号并登录
3. 在"个人中心"复制 Token

#### 步骤 2: 配置 API Key

在项目根目录创建 `.env` 文件：

```bash
TUSHARE_API_KEY=your_token_here
```

#### 步骤 3: 使用驱动器

```python
from sea_invest.perception.tushare_driver import TushareDriver

# 初始化驱动器（自动从配置读取 API Key）
driver = TushareDriver()

# 获取股票数据（贵州茅台）
result = await driver.process("600519")

# 查看结果
print(result.payload["pe_ttm"])  # PE (TTM)
print(result.payload["pb"])  # PB
print(result.payload["total_mv"])  # 总市值
```

## 📊 数据字段说明

### EastMoneyDriver 返回的字段

| 字段 | 说明 | 示例 |
|------|------|------|
| `price` | 最新价格 | 12.5 |
| `change_pct` | 涨跌幅（%） | 2.5 |
| `volume` | 成交量（手） | 100000 |
| `turnover_rate` | 换手率（%） | 3.2 |
| `amount` | 成交额（元） | 50000000 |
| `north_inflow` | 北向资金净流入（元） | 1000000 |
| `margin_balance` | 融资余额（元） | 50000000 |

### TushareDriver 返回的字段

| 字段 | 说明 | 示例 |
|------|------|------|
| `close` | 收盘价 | 1800.0 |
| `pe_ttm` | PE (TTM) | 25.3 |
| `pe` | PE | 22.5 |
| `pb` | PB | 8.5 |
| `ps` | PS | 5.2 |
| `total_mv` | 总市值（万元） | 2500000 |
| `circ_mv` | 流通市值（万元） | 2000000 |
| `turnover_rate` | 换手率（%） | 1.5 |
| `volume_ratio` | 量比 | 1.2 |

## 🔧 高级用法

### 批量获取数据

```python
from sea_invest.perception.gateway import PerceptionGateway
from sea_invest.perception.eastmoney_driver import EastMoneyDriver
from sea_invest.perception.tushare_driver import TushareDriver

# 初始化 Gateway
gateway = PerceptionGateway()

# 注册驱动器
gateway.register(EastMoneyDriver())
gateway.register(TushareDriver())

# 批量获取数据
scan_plan = {
    "EastMoney": ["000001", "600000", "000002"],
    "Tushare": ["000001", "600000", "000002"]
}

# 并行获取
results = await gateway.collect_all(scan_plan)

# 处理结果
for moment in results:
    print(f"{moment.source_name}: {moment.payload['ticker']}")
```

### 获取财务报表数据（仅 Tushare）

```python
driver = TushareDriver()

# 获取利润表
financial_data = await driver.fetch_financial_report("000001")

print(financial_data["revenue"])  # 营业收入
print(financial_data["net_profit"])  # 净利润
print(financial_data["cash_flow"])  # 现金流量
```

### 获取龙虎榜数据（仅 EastMoney）

```python
driver = EastMoneyDriver()

# 获取龙虎榜数据
longhu_data = await driver.fetch_longhub("000001")

print(longhu_data)  # 机构买卖明细
```

## 📈 僵格估值指标

两个驱动器都会返回估值水平指标（`valuation_level`）：

- **0.0**: 低估值（买入机会）
- **0.5**: 合理估值
- **1.0**: 偏高估值（谨慎）
- **1.0**: 高估值（避免）

```python
result = await driver.process("000001")
valuation = result.marks_indicators["valuation_level"]

if valuation < 0.3:
    print("低估股票，值得买入")
elif valuation > 0.7:
    print("高估股票，谨慎持有")
else:
    print("估值合理，持有观望")
```

## 🧪 测试

运行测试脚本：

```bash
# 测试所有驱动器
python examples/test_a_share_drivers.py

# 仅测试 EastMoney（无需配置）
python -c "from examples.test_a_share_drivers import test_eastmoney_driver; import asyncio; asyncio.run(test_eastmoney_driver())"
```

## ⚠️ 注意事项

### EastMoneyDriver

1. **频率限制**: 无官方限制，但建议间隔至少 1 秒
2. **数据延迟**: 实时数据可能有 3-5 秒延迟
3. **字段缺失**: 某些股票可能没有龙虎榜/融资融券数据
4. **网络依赖**: 需要稳定的网络连接

### TushareDriver

1. **API 额度**: 免费账户有每日调用次数限制（根据积分等级不同）
2. **积分获取**: 
   - 注册送 100 积分
   - 完善资料送 100 积分
   - 每日签到送 10 积分
3. **数据更新**: 
   - 日线数据：T+1 日更新
   - 财务数据：季报/年报发布后更新
4. **缓存机制**: 驱动器内置 1 小时缓存，避免重复请求

## 🔒 错误处理

```python
try:
    result = await driver.process("000001")
except ValueError as e:
    print(f"数据格式错误: {e}")
except httpx.HTTPStatusError as e:
    print(f"API 请求失败: {e}")
except Exception as e:
    print(f"未知错误: {e}")
```

## 📚 相关资源

- **东方财富开放平台**: https://openapidocs.eastmoney.com/
- **Tushare Pro 文档**: https://tushare.pro/document/2
- **Tushare 注册**: https://tushare.pro/register
- **API 积分说明**: https://tushare.pro/document/1

## 🤝 贡献

欢迎贡献更多 A 股数据源驱动器！

支持的格式：
- 聚源数据驱动器 (JuyuanDriver)
- Wind 金融终端驱动器 (WindDriver)
- Choice 数据驱动器 (ChoiceDriver)

请参考 `BaseDataSource` 实现自定义驱动器。
