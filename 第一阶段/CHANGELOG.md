# DeepTrader jq_lite.py — 开发日志

**当前阶段：第一阶段 ✅ 完工**

---

## 一、架构决策（第二阶段不得推翻）

### 1.1 三层结构已定
```
用户策略代码（RQAlpha/JQAlpha 方言）
        ↓ API 接口层
Backtrader（Cerebro 引擎）
        ↓ 数据层
本地 Parquet（/mnt/d/A股全数据260320/） + Tushare 兜底
```

### 1.2 RQAlpha 方言路线确认
- 选择继承 RQAlpha API 风格，不自创、不用 Backtrader 原生
- 原因：A股用户生态最接近，方便移植聚宽现有策略
- 局限性：换电脑需改 token 和数据路径（第一阶段不做通用性）

### 1.3 单文件结构
- 第一阶段：`jq_lite.py`（~1300行）
- 第二阶段：重构为 `jq_trader/` 模块化（见 PRD 第二阶段）
- 过渡原则：第二阶段重构时，API 接口名和签名不得改变

---

## 二、第一阶段交付物

### 2.1 P0 API 清单（已验收 ✅）

| API | 调用方式 | 说明 |
|-----|---------|------|
| `initialize(context)` | 用户定义 | 策略初始化 |
| `handle_data(context, data)` | 用户定义 | 每日交易逻辑 |
| `history(count, fields, df)` | `self.history(...)` | 返回 ndarray/dict/DataFrame |
| `order(security, amount)` | `self.order(...)` | 市价单，正=买负=卖 |
| `order_target(security, amount)` | `self.order_target(...)` | 调仓到目标股数 |
| `context.current_dt` | `context._current_dt` | 当前日期 |
| `context.portfolio.available_cash` | `context._available_cash` | 可用资金 |
| `context.portfolio.positions` | `context._positions` | 持仓 |
| `self.g` | `self.g.xxx` | 全局变量 |
| `set_benchmark(security)` | `self.set_benchmark(...)` | 设置基准（占位） |
| `set_order_cost(commission, tax)` | `self.set_order_cost(...)` | 设置佣金+印花税 |
| `get_position(security)` | `self.get_position(...)` | 返回持仓 dict |
| `get_price(...)` | 模块级函数 | 数据加载 |
| `get_all_securities(type_)` | `self.get_all_securities(...)` | 股票列表 |
| `get_trade_days(...)` | `self.get_trade_days(...)` | 交易日列表 |
| `get_index_stocks(index)` | `self.get_index_stocks(...)` | 指数成分股 |
| `sma(period, field)` | `self.sma(...)` | 当前 bar 的 SMA |

### 2.2 关键 Bug 修复记录

| 日期 | 问题 | 修复 |
|------|------|------|
| 2026-04-28 | `order(100)` 只买1股 | `self.buy(size=amount)` 传入 size 参数 |

### 2.3 文件结构
```
DeepTrader/
├── jq_lite.py              # 核心兼容层（第一阶段交付物）
├── examples/
│   └── ma_cross_strategy.py # 均线策略示例（已验收）
├── README.md               # 使用说明
├── CHANGELOG.md            # 本文件
└── doc_第一阶段PRD...docx   # PRD 原始文档
```

---

## 三、已知限制（第一阶段故意不做）

以下内容在第一阶段故意留空，第二阶段再补：

| 缺失项 | 说明 |
|--------|------|
| `run_daily` / `before_trading_start` | 定时调度函数 |
| `order_value` / `order_target_value` | 按金额下单（非股数） |
| 多标的支持 | 目前只支持单只股票 |
| 分钟线 | 目前只支持日线 `1d` |
| `get_bars` | 非标准周期合成 |
| 科创板保护价 / 平今仓 | 简化处理 |
| 对象模型（Portfolio/Order/Trade）| 仅 `get_position` 返回 dict |
| `g` 对象持久化 | 重启不恢复 |
| 回测图表 | 仅打印文本统计 |

---

## 四、数据路径与配置（第二阶段继续用）

```
本地 Parquet: /mnt/d/A股全数据260320/个股日线/
文件格式:     {ts_code}_{start}_{end}.parquet（如 000001.SZ_20200101_20260320.parquet）
Tushare URL:  http://121.40.135.59:8010/
Token:        zVqthiTTyQpJhOzfCdKfgRZTFHCEbMRKtdUUnDUTqBAKrzXwPAdOskmccOGLDQfb
复权方式:     前复权（默认）
```

---

## 五、Backtrader 关键经验（避坑）

1. **datetime 用 float，不是 YYYYMMDD**
   - `bt.num2date(lines[6][-i])` 转换，不要强转字符串

2. **`buy()/sell()` 必须传 `size`**
   - 不传默认 1 股，不是全仓

3. **history buffer 索引顺序**
   - `lines[-1]` = 当前 bar，`lines[-2]` = 上一个 bar
   - 获取前 N 条：`[lines[-i] for i in range(N, 0, -1)]`

4. **`order_dict` 需手动初始化**
   - 在 `JQStrategy.__init__` 中初始化 `self.order_dict = {}`

5. **context 的 `_` 前缀属性**
   - `context._current_dt` / `context._available_cash` / `context._positions`
   - 用户代码访问 `context.current_dt` 实际走的是 `__getattr__`

---

## 六、第二阶段入口（下一步）

根据 PRD 第二阶段，下一步是：

1. **模块化重构**：`jq_lite.py` → `jq_trader/env.py + data.py + trade.py + objects.py + adapter.py`
2. **运行环境层**：`run_daily` / `before_trading_start` / `after_trading_end` / `g` 持久化
3. **补全交易 API**：`order_value` / `order_target_value` / `cancel_order` / `get_orders` / `get_trades`
4. **对象模型**：Portfolio / SubPortfolio / Position / Order / Trade 对象
5. **数据 API**：`get_bars` / `attribute_history` / `get_current_data`

**第二阶段 PRD 文件：`doc_a431b9d1dcb4_第二阶段 PRD：接口级兼容层（全部翻译）.docx`**
