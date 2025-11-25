说明：
这个实现完全依赖于 config.py 中的配置。
now(): 统一获取当前 ET 时间。
get_market_phase(): 核心逻辑，判断当前是盘前、盘中、盘后还是休市。

```markdown
# Market Clock 模块说明

**文件路径**: `src/bronco_trade_agents/data/schedulers/market_clock.py`

## 简介
`MarketClock` 是 Data 模块的“时间大脑”，负责基于美股市场规则（NYSE/NASDAQ）判断当前是否应该进行数据采集。它集成了 Python `zoneinfo` 时区处理与数据库日历配置，确保在夏令时、节假日和提前闭市（Early Close）等复杂场景下也能做出准确判断。

---

## 核心功能

### 1. 时区感知 (Timezone Awareness)
- 强制使用 `America/New_York` 时区（ET）。
- 自动处理夏令时（DST）切换，无需人工干预。
- 所有输入时间（若无时区）默认视为 UTC 并转换为 ET 进行判断。

### 2. 交易阶段判断 (`get_market_phase`)
将一天划分为四个互斥阶段：
- **PRE_MARKET** (盘前): 04:00 - 09:30 ET
- **REGULAR** (常规): 09:30 - 16:00 ET
- **AFTER_HOURS** (盘后): 16:00 - 20:00 ET
- **CLOSED** (休市): 周末、节假日、以及上述时间段之外的时间。

### 3. 数据库日历集成 (Database Calendar)
- **缓存机制**: 通过 `load_calendar_cache` 方法，一次性从数据库加载全年的节假日配置到内存 (`_calendar_cache`)，避免每次判断都查询数据库，保证高性能。
- **特殊日处理**:
    - **Closed**: 全天休市（如圣诞节）。
    - **Early Close**: 提前收盘（如感恩节次日，通常 13:00 收盘），自动调整当天的交易结束时间。

### 4. 辅助方法
- `is_market_open(include_extended=True)`: 返回布尔值，指示当前是否开市。支持选择是否包含盘前盘后。
- `time_until_next_open()`: 计算距离下一次开盘还有多久。用于休市期间让采集器进入长时间休眠（Sleep），减少资源消耗。

---

## 使用示例

### 初始化缓存（应用启动时）
```python
from src.bronco_trade_agents.database import session_scope
from src.bronco_trade_agents.data.schedulers.market_clock import MarketClock

# 从数据库加载当年日历
with session_scope() as session:
    MarketClock.load_calendar_cache(session)
```

### 判断当前状态
```python
if MarketClock.is_market_open():
    print("Market is open! Start collecting...")
else:
    print("Market is closed.")
    
phase = MarketClock.get_market_phase()
print(f"Current phase: {phase}")  # e.g., "regular" or "pre_market"
```

### 计算休眠时间
```python
import time

if not MarketClock.is_market_open():
    wait_time = MarketClock.time_until_next_open()
    print(f"Sleeping for {wait_time}...")
    time.sleep(wait_time.total_seconds())
```
```