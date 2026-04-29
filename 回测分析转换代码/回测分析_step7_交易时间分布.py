# -*- coding: utf-8 -*-
"""
回测结果分析 Step7 — 交易时间分布（按星期/月份）
输入: smallcap_v2_trades.csv
输出: step7_trade_time_dist.csv
"""

import warnings
from pathlib import Path
import pandas as pd
warnings.filterwarnings('ignore')

EXP_DIR = Path('/home/lihw/stock_selector_exp/backtest')
OUT_DIR = Path('/home/lihw/stock_selector_exp/backtest')

# ── 读取卖出记录 ──────────────────────────────────
trades_df = pd.read_csv(EXP_DIR / 'smallcap_v2_trades.csv', encoding='utf-8-sig')
sells = trades_df[trades_df['action'].str.startswith('sell')].copy()
sells['trade_date'] = pd.to_datetime(sells['trade_date'], format='%Y%m%d')
sells['return_pct'] = pd.to_numeric(sells['return_pct'], errors='coerce')
sells = sells.dropna(subset=['return_pct'])
sells['return_decimal'] = sells['return_pct'] / 100

sells['weekday'] = sells['trade_date'].dt.weekday   # 0=周一
sells['month']   = sells['trade_date'].dt.month

weekday_names = ['周一','周二','周三','周四','周五']
wd_rows = []
for i, label in enumerate(weekday_names):
    sub = sells[sells['weekday'] == i]
    cnt  = len(sub)
    wins = (sub['return_decimal'] > 0).sum()
    wr   = wins / cnt if cnt > 0 else 0
    avg  = sub['return_decimal'].mean() if cnt > 0 else 0
    wd_rows.append({
        '星期': label, '交易笔数': cnt, '胜率': f"{wr*100:.1f}%",
        '平均收益%': f"{avg*100:.2f}%" if cnt > 0 else '-'
    })

mo_rows = []
for m in range(1, 13):
    sub = sells[sells['month'] == m]
    cnt  = len(sub)
    wins = (sub['return_decimal'] > 0).sum()
    wr   = wins / cnt if cnt > 0 else 0
    avg  = sub['return_decimal'].mean() if cnt > 0 else 0
    mo_rows.append({
        '月份': f'{m}月', '交易笔数': cnt, '胜率': f"{wr*100:.1f}%",
        '平均收益%': f"{avg*100:.2f}%" if cnt > 0 else '-'
    })

wd_df = pd.DataFrame(wd_rows)
mo_df = pd.DataFrame(mo_rows)
wd_df.to_csv(OUT_DIR / 'step7_weekday_dist.csv', index=False, encoding='utf-8-sig', quoting=1)
mo_df.to_csv(OUT_DIR / 'step7_month_dist.csv', index=False, encoding='utf-8-sig', quoting=1)

print("=== Step7 交易时间分布 ===")
print("\n按星期：")
print(wd_df.to_string(index=False))
print("\n按月份：")
print(mo_df.to_string(index=False))
print(f"\n已保存: step7_weekday_dist.csv | step7_month_dist.csv")
