# -*- coding: utf-8 -*-
"""
回测结果分析 Step6 — 持仓行为分析（持仓天数分布）
输入: smallcap_v2_trades.csv
输出: step6_holding_behavior.csv
"""

import warnings
from pathlib import Path
import pandas as pd
warnings.filterwarnings('ignore')

EXP_DIR = Path('/home/lihw/stock_selector_exp/backtest')
OUT_DIR = Path('/home/lihw/stock_selector_exp/backtest')

# ── 读取交易记录 ──────────────────────────────────
trades_df = pd.read_csv(EXP_DIR / 'smallcap_v2_trades.csv', encoding='utf-8-sig')
trades_df['trade_date'] = pd.to_datetime(trades_df['trade_date'], format='%Y%m%d')
trades_df = trades_df.sort_values(['ts_code', 'trade_date'])

# ── 配对买卖计算持仓天数 ───────────────────────────
# 买入记录
buys = trades_df[trades_df['action'] == 'buy'][['trade_date', 'ts_code']].copy()
buys.columns = ['buy_date', 'ts_code']
# 卖出记录
sells = trades_df[trades_df['action'].str.startswith('sell')][['trade_date', 'ts_code']].copy()
sells.columns = ['sell_date', 'ts_code']

# 按股票 FIFO 配对
hold_days = []
for ts in buys['ts_code'].unique():
    ts_buys  = buys[buys['ts_code'] == ts].sort_values('buy_date')['buy_date'].tolist()
    ts_sells = sells[sells['ts_code'] == ts].sort_values('sell_date')['sell_date'].tolist()

    queue = []
    for b in ts_buys:
        queue.append(b)
    for s in ts_sells:
        if queue:
            bt = queue.pop(0)
            days = (s - bt).days
            if days >= 0:
                hold_days.append(days)

if not hold_days:
    print("未匹配到买卖配对")
    exit()

sr = pd.Series(hold_days)
total = len(sr)
avg_d  = sr.mean()
med_d  = sr.median()
max_d  = sr.max()
min_d  = sr.min()
short_ = (sr < 5).sum()       # <5天短线
mid_   = ((sr >= 5) & (sr < 20)).sum()  # 5-20天中线
long_  = (sr >= 20).sum()      # >20天长线

rows = [
    {'指标': '配对成功笔数',   '值': total},
    {'指标': '平均持仓天数',   '值': f"{avg_d:.1f} 天"},
    {'指标': '中位持仓天数',   '值': f"{med_d:.0f} 天"},
    {'指标': '最长持仓',       '值': f"{int(max_d)} 天"},
    {'指标': '最短持仓',       '值': f"{int(min_d)} 天"},
    {'指标': '超短线(<5天)',   '值': f"{short_}笔 ({short_/total*100:.1f}%)"},
    {'指标': '短线(5~20天)',  '值': f"{mid_}笔 ({mid_/total*100:.1f}%)"},
    {'指标': '长线(>20天)',    '值': f"{long_}笔 ({long_/total*100:.1f}%)"},
]

out = pd.DataFrame(rows)
out.to_csv(OUT_DIR / 'step6_holding_behavior.csv', index=False, encoding='utf-8-sig', quoting=1)
print("=== Step6 持仓行为分析 ===")
print(out.to_string(index=False))
print(f"\n已保存: {OUT_DIR / 'step6_holding_behavior.csv'}")
