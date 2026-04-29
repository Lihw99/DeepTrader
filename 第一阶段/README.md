# DeepTrader

聚宽(JQ)策略本地回测工具 — 轻量复刻版。

## 目标

让你把聚宽上写好的策略（.py文件）直接搬到本地运行，不需要学 Backtrader 的 Cerebro/DataFeed 那一套。

## 项目结构

```
DeepTrader/
├── jq_lite.py                # 核心兼容层（P0 API）
├── examples/
│   └── ma_cross_strategy.py  # 均线交叉策略示例
└── PRD/                      # 产品需求文档
    └── 第一阶段 PRD：快速上手（轻量复刻）.docx
```

## 快速开始

### 1. 安装依赖

```bash
pip install backtrader pandas numpy tushare
```

### 2. 配置数据（可选）

- **方式一（推荐）**：将本地 Parquet 数据放在 `/mnt/d/A股全数据260320/`
- **方式二**：配置 Tushare token，在 `jq_lite.py` 同目录下创建 `token.txt`

### 3. 运行示例策略

```bash
cd /home/lihw/DeepTrader
python examples/ma_cross_strategy.py
```

## P0 支持的 API

| 函数 | 说明 | 状态 |
|------|------|------|
| `get_price(security, count, ...)` | 获取K线数据 | ✅ |
| `history(count, unit, field)` | 获取历史序列 | ✅ |
| `order(security, amount)` | 市价单（正=买，负=卖） | ✅ |
| `order_target(security, amount)` | 调仓到目标股数 | ✅ |
| `context.current_dt` | 当前日期 | ✅ |
| `context.portfolio.available_cash` | 可用资金 | ✅ |
| `context.portfolio.positions` | 持仓信息 | ✅ |
| `self.g` | 全局变量 | ✅ |
| `initialize(context)` | 初始化 | ✅ |
| `handle_data(context, data)` | 每日交易逻辑 | ✅ |
| `set_benchmark()` | 设置基准 | 🚧 |
| `set_order_cost()` | 设置佣金 | 🚧 |

## 策略写法

```python
from jq_lite import JQStrategy, Backtester

class MyStrategy(JQStrategy):

    def initialize(self, context):
        context.stock = "000001.SZ"

    def handle_data(self, context, data):
        # 获取均线
        ma5 = self.history(5, "1d", "close")
        ma20 = self.history(20, "1d", "close")

        if not self.position:
            if ma5[-1] > ma20[-1]:
                self.buy(size=100)
        else:
            if ma5[-1] < ma20[-1]:
                self.close()

# 运行
bt = Backtester(
    strategy=MyStrategy,
    stock="000001.SZ",
    start_date="20200101",
    end_date="20231231",
)
bt.run()
```

## 与聚宽的差异

| 功能 | 聚宽 | jq_lite |
|------|------|---------|
| 多标的 | ✅ | ❌ 暂不支持 |
| 分钟线 | ✅ | 🚧 暂不支持 |
| 实时交易 | ✅ | ❌ 仅回测 |
| 财务数据 | ✅ | ❌ 暂不支持 |
| 因子函数 | ✅ | ❌ 暂不支持 |

## 参考项目

- [RQAlpha](https://github.com/ricequant/rqalpha) — 米筐开源回测引擎，API 设计参考
- [cn-trader](https://github.com/codfish-zz/cn-trader) — Backtrader A股封装参考
- [jqdatasdk](https://github.com/JoinQuant/jqdatasdk) — 聚宽官方数据结构参考
