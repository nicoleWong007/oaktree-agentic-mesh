# A 股专用驱动器实现总结

## 📦 新增文件

### 1. 数据驱动器

| 文件路径 | 说明 | 行数 |
|---------|------|------|
| `sea_invest/perception/eastmoney_driver.py` | 东方财富数据驱动器 | 412 |
| `sea_invest/perception/tushare_driver.py` | Tushare Pro API 驱动器 | 317 |

### 2. 文档和示例

| 文件路径 | 说明 |
|---------|------|
| `docs/A_SHARE_DRIVERS.md` | A 股驱动器使用文档 |
| `examples/test_a_share_drivers.py` | 测试和使用示例 |
| `.env.example` | 环境变量配置示例 |

### 3. 配置更新

| 文件路径 | 修改内容 |
|---------|---------|
| `sea_invest/config.py` | 添加 `tushare_api_key` 配置项 |

## 🔧 核心功能

### EastMoneyDriver

**数据类型**：
- ✅ 实时行情（价格、涨跌幅、成交量、换手率）
- ✅ 北向资金流向（沪港通、深港通）
- ✅ 融资融券数据（两融余额）
- ✅ 龙虎榜数据（机构买卖、游资动向）
- ✅ 板块资金流（行业/概念资金流）

**特点**：
- 🆓 完全免费，无需认证
- ⚡ 实时更新（盘中）
- 🎯 适合短线交易、市场情绪分析

**使用示例**：
```python
from sea_invest.perception.eastmoney_driver import EastMoneyDriver

driver = EastMoneyDriver()
result = await driver.process("000001")  # 平安银行

# 查看数据
print(result.payload["price"])  # 价格
print(result.payload["change_pct"])  # 涨跌幅
print(result.payload["turnover_rate"])  # 换手率
```

### TushareDriver

**数据类型**：
- ✅ 财务报表（资产负债表、利润表、现金流量表）
- ✅ 技术指标（PE、PB、PS、市值）
- ✅ 股东结构（股东人数、持股集中度）
- ✅ 业绩预告、分红送转
- ✅ 行业数据、指数数据

**特点**：
- 💰 免费额度 + 付费扩展
- 📊 数据全面（10年+历史数据）
- 🎯 适合基本面分析、量化研究
- ⏰ 日度/周度更新

**使用示例**：
```python
from sea_invest.perception.tushare_driver import TushareDriver

# 需要先配置 TUSHARE_API_KEY
driver = TushareDriver()
result = await driver.process("600519")  # 贵州茅台

# 查看数据
print(result.payload["pe_ttm"])  # PE(TTM)
print(result.payload["pb"])  # PB
print(result.payload["total_mv"])  # 总市值
```

## 📊 数据字段对比

| 字段 | EastMoneyDriver | TushareDriver |
|------|----------------|---------------|
| 实时价格 | ✅ | ✅ |
| 涨跌幅 | ✅ | ✅ |
| 成交量 | ✅ | ✅ |
| 换手率 | ✅ | ✅ |
| PE/PB | ❌ | ✅ |
| 市值 | ❌ | ✅ |
| 北向资金 | ✅ | ❌ |
| 龙虎榜 | ✅ | ❌ |
| 融资融券 | ✅ | ❌ |
| 财务报表 | ❌ | ✅ |
| 技术指标 | ❌ | ✅ |

## 🚀 快速开始

### 1. 安装依赖（已包含在项目中）

```bash
pip install httpx loguru pydantic
```

### 2. 配置环境变量（仅 Tushare 需要）

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env 文件
TUSHARE_API_KEY=your_token_here
```

### 3. 运行测试

```bash
# 测试 EastMoneyDriver（无需配置）
python examples/test_a_share_drivers.py

# 或单独测试
python -c "
import asyncio
from sea_invest.perception.eastmoney_driver import EastMoneyDriver

async def test():
    driver = EastMoneyDriver()
    result = await driver.process('000001')
    print(result.payload)

asyncio.run(test())
"
```

## 🔧 集成到现有系统

### 批量获取 A 股数据

```python
from sea_invest.perception.gateway import PerceptionGateway
from sea_invest.perception.eastmoney_driver import EastMoneyDriver
from sea_invest.perception.tushare_driver import TushareDriver

# 初始化 Gateway
gateway = PerceptionGateway()

# 注册驱动器
gateway.register(EastMoneyDriver())
gateway.register(TushareDriver())  # 需要配置 API Key

# 批量获取 A 股数据
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

### 在 Ingestor 中使用

```python
# sea_invest/agents/ingestor.py

from sea_invest.perception.eastmoney_driver import EastMoneyDriver
from sea_invest.perception.tushare_driver import TushareDriver

async def ingestor_node(state: InvestmentState) -> InvestmentState:
    gateway = PerceptionGateway()
    
    # 根据市场类型注册驱动器
    if state.asset_class == AssetClass.CN_A_SHARE:  # 新增 A 股类型
        gateway.register(EastMoneyDriver())
        gateway.register(TushareDriver())
    else:
        gateway.register(YahooFinanceDriver())
        gateway.register(MacroDriver())
    
    # ... 其他逻辑
```

## 📈 性能优化

### 缓存机制

两个驱动器都内置了缓存：
- **缓存时间**: 1 小时
- **缓存键**: `{ticker}_{data_type}`
- **自动清理**: 无限增长（生产环境建议添加 LRU 缓存）

### 并发控制

```python
# 批量获取时自动并发（Gateway 已实现）
results = await gateway.collect_all({
    "EastMoney": ["000001", "600000", "000002"]  # 并发 3 个请求
})
```

### 错误处理

```python
try:
    result = await driver.process("000001")
except ValueError as e:
    # 数据格式错误
    logger.error(f"Data format error: {e}")
except httpx.HTTPStatusError as e:
    # API 请求失败
    logger.error(f"API request failed: {e}")
except Exception as e:
    # 其他错误
    logger.error(f"Unexpected error: {e}")
```

## ⚠️ 注意事项

### EastMoneyDriver

1. **频率限制**: 虽无官方限制，但建议间隔至少 1 秒
2. **数据延迟**: 实时数据可能有 3-5 秒延迟
3. **字段缺失**: 某些股票可能没有龙虎榜/融资融券数据

### TushareDriver

1. **API 额度**: 免费账户有每日调用次数限制（根据积分等级）
2. **积分获取**: 
   - 注册送 100 积分
   - 完善资料送 100 积分
   - 每日签到送 10 积分
3. **数据更新**: 
   - 日线数据：T+1 日更新
   - 财务数据：季报/年报发布后更新

## 📚 参考资源

- **东方财富开放平台**: https://openapidocs.eastmoney.com/
- **Tushare Pro 文档**: https://tushare.pro/document/2
- **Tushare 注册**: https://tushare.pro/register
- **API 积分说明**: https://tushare.pro/document/1

## 🔄 后续优化建议

### 短期（1-2 周）

1. ✅ 添加更多数据源（聚源、Wind、Choice）
2. ✅ 优化缓存策略（LRU、Redis）
3. ✅ 添加数据验证和清洗

### 中期（1-2 月）

4. ✅ 支持港股通数据
5. ✅ 添加 Level-2 数据支持
6. ✅ 实现增量更新（只获取新数据）

### 长期（3-6 月）

7. ✅ 机器学习数据清洗
8. ✅ 异常值检测
9. ✅ 数据质量监控和报警

## 📝 TODO

- [ ] 添加单元测试
- [ ] 添加集成测试
- [ ] 优化错误提示
- [ ] 添加数据字段文档
- [ ] 支持更多 A 股数据源

---

**创建日期**: 2026-03-05
**版本**: 1.0.0
**维护者**: SEA-Invest Team
