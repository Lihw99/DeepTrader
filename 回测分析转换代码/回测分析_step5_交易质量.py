# -*- coding: utf-8 -*-
"""
回测结果分析 Step5 — 交易质量分析（胜率/盈亏比/卡尔马）
输入: smallcap_v2_result.csv + smallcap_v2_trades.csv
输出: step5_trade_quality.csv
"""

import json, warnings
from pathlib import Path
import pandas as pd
import numpy as np
warnings.filterwarnings('ignore')

EXP_DIR = Path('/home/lihw/stock_selector_exp/backtest')
OUT_DIR = Path('/home/lihw/stock_selector_exp/backtest')
REF_RATE = 0.03

# ── 读取 ─────────────────────────────────────────
result_df = pd.read_csv(EXP_DIR / 'smallcap_v2_result.csv', encoding='utf-8-sig')
result_df['trade_date'] = pd.to_datetime(result_df['trade_date'], format='%Y%m%d')
result_df = result_df.sort_values('trade_date').reset_index(drop=True)
result_df['nav'] = result_df['equity_wan'] / result_df['equity_wan'].iloc[0]
result_df['d_ret'] = result_df['nav'].pct_change()

trades_df = pd.read_csv(EXP_DIR / 'smallcap_v2_trades.csv', encoding='utf-8-sig')
with open(EXP_DIR / 'smallcap_v2_stats.json') as f:
    stats = json.load(f)

# ── 卖出记录统计 ──────────────────────────────────
sells = trades_df[trades_df['action'].str.startswith('sell')].copy()
sells['return_pct'] = pd.to_numeric(sells['return_pct'], errors='coerce')
sells = sells.dropna(subset=['return_pct'])
sells['return_decimal'] = sells['return_pct'] / 100

total = len(sells)
wins   = (sells['return_decimal'] > 0).sum()
losses = (sells['return_decimal'] <= 0).sum()
win_rate = wins / max(total, 1)
avg_win  = sells[sells['return_decimal'] > 0]['return_decimal'].mean() if wins > 0 else 0
avg_loss = abs(sells[sells['return_decimal'] < 0]['return_decimal'].mean()) if losses > 0 else 0.001
pnl_ratio = avg_win / avg_loss

# 卡尔马比率
days = len(result_df)
tot_ret = result_df['nav'].iloc[-1] / result_df['nav'].iloc[0] - 1
ann_ret = (1 + tot_ret) ** (252 / days) - 1 if days > 0 else 0
nav_series = result_df['nav']
rolling_max = nav_series.cummax()
drawdowns = (nav_series - rolling_max) / rolling_max
mdd = drawdowns.min()
calmar = ann_ret / abs(mdd) if mdd != 0 else 0

rows = [
    {'指标': '卖出总笔数',             '值': total,          '说明': '所有卖出操作'},
    {'指标': '盈利笔数',               '值': int(wins),       '说明': '收益>0'},
    {'指标': '亏损笔数',               '值': int(losses),     '说明': '收益<=0'},
    {'指标': '卖出胜率',               '值': f"{win_rate*100:.2f}%",  '说明': '盈利笔数/总笔数'},
    {'指标': '平均盈利',               '值': f"{avg_win*100:.2f}%",   '说明': '盈利交易的平均收益率'},
    {'指标': '平均亏损',               '值': f"{avg_loss*100:.2f}%",  '说明': '亏损交易的平均亏损率'},
    {'指标': '盈亏比',                 '值': f"{pnl_ratio:.2f}",       '说明': '平均盈利/平均亏损绝对值'},
    {'指标': '单笔期望收益',           '值': f"{win_rate*avg_win - (1-win_rate)*avg_loss:.4f}", '说明': '每笔交易期望值'},
    {'指标': '卡尔马比率',             '值': f"{calmar:.2f}",          '说明': '年化收益/最大回撤'},
    {'指标': '总费用(万)',             '值': f"{stats.get('total_fees_wan', 0):.4f}", '说明': '佣金+印花税合计'},
]

out = pd.DataFrame(rows)
out.to_csv(OUT_DIR / 'step5_trade_quality.csv', index=False, encoding='utf-8-sig', quoting=1)
print("=== Step5 交易质量分析 ===")
print(out.to_string(index=False))
print(f"\n已保存: {OUT_DIR / 'step5_trade_quality.csv'}")
