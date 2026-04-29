# -*- coding: utf-8 -*-
"""
回测结果分析 Step1 — 核心统计
读取 smallcap_v2 的 result.csv + trades.csv + stats.json
输出: 核心指标表 + 年度收益表
"""

import json, warnings
from pathlib import Path
import pandas as pd
import numpy as np
warnings.filterwarnings('ignore')

# ── 路径配置 ─────────────────────────────────────
EXP_DIR   = Path('/home/lihw/stock_selector_exp/backtest')
OUT_DIR   = Path('/home/lihw/stock_selector_exp/backtest')
REF_RATE  = 0.03   # 无风险利率（3%）

# ── 读取数据 ─────────────────────────────────────
result_df = pd.read_csv(EXP_DIR / 'smallcap_v2_result.csv', encoding='utf-8-sig')
with open(EXP_DIR / 'smallcap_v2_stats.json', encoding='utf-8') as f:
    stats = json.load(f)

result_df['trade_date'] = pd.to_datetime(result_df['trade_date'], format='%Y%m%d')
result_df = result_df.sort_values('trade_date').reset_index(drop=True)
result_df['nav'] = result_df['equity_wan'] / result_df['equity_wan'].iloc[0]
result_df['d_ret'] = result_df['nav'].pct_change()
result_df.loc[0, 'd_ret'] = result_df['nav'].iloc[0] / 1 - 1  # 第一天净值增长率（已归一化到1，起始为1）

print(f"数据: {result_df['trade_date'].iloc[0].date()} → {result_df['trade_date'].iloc[-1].date()}, "
      f"共 {len(result_df)} 个交易日")

# ── 核心指标计算 ─────────────────────────────────
def calc_max_drawdown(nav):
    rolling_max = nav.cummax()
    return ((nav - rolling_max) / rolling_max).min()

days    = len(result_df)
nav_arr = result_df['nav'].values
d_ret   = result_df['d_ret'].values

total_ret  = nav_arr[-1] / nav_arr[0] - 1
ann_ret    = (1 + total_ret) ** (252 / days) - 1 if days > 0 else 0
vol        = np.std(d_ret, ddof=1) * np.sqrt(252) if len(d_ret) > 1 else 0
sharpe     = (ann_ret - REF_RATE) / vol if vol > 0 else 0
mdd        = calc_max_drawdown(result_df['nav'])
win_rate   = (d_ret > 0).sum() / days

# ── 读交易记录算胜率/盈亏比 ──────────────────────
trades_df = pd.read_csv(EXP_DIR / 'smallcap_v2_trades.csv', encoding='utf-8-sig')
sells = trades_df[trades_df['action'].str.startswith('sell')]
if 'return_pct' in sells.columns:
    sell_rets = sells['return_pct'].dropna() / 100
    wins  = (sell_rets > 0).sum()
    losses = (sell_rets <= 0).sum()
    wr    = wins / max(len(sell_rets), 1)
    avg_win  = sell_rets[sell_rets > 0].mean() if wins > 0 else 0
    avg_loss = abs(sell_rets[sell_rets < 0].mean()) if losses > 0 else 0.01
    pl_ratio = avg_win / avg_loss
else:
    wr, pl_ratio = stats.get('win_rate', 0), stats.get('profit_loss_ratio', 0)

# ── 输出核心指标表 ─────────────────────────────────
stats_rows = [
    {'指标': '策略名',                '值': stats.get('strategy', '小市值回测v2')},
    {'指标': '区间开始',              '值': str(result_df['trade_date'].iloc[0].date())},
    {'指标': '区间结束',              '值': str(result_df['trade_date'].iloc[-1].date())},
    {'指标': '交易天数',              '值': days},
    {'指标': '初始资金(万)',          '值': round(stats.get('init_cash_wan', 0.8), 2)},
    {'指标': '期末净值(万)',          '值': round(nav_arr[-1] * stats.get('init_cash_wan', 0.8), 2)},
    {'指标': '总收益',                '值': f"{total_ret*100:+.2f}%"},
    {'指标': '年化收益',              '值': f"{ann_ret*100:+.2f}%"},
    {'指标': '最大回撤',              '值': f"{mdd*100:+.2f}%"},
    {'指标': '收益波动率(年化)',       '值': f"{vol*100:+.2f}%"},
    {'指标': '夏普比率',              '值': f"{sharpe:.4f}"},
    {'指标': '日胜率',                '值': f"{win_rate*100:.2f}%"},
    {'指标': '总交易笔数',            '值': int(stats.get('n_trades', 0))},
    {'指标': '卖出胜率',              '值': f"{wr*100:.2f}%"},
    {'指标': '盈亏比',                '值': f"{pl_ratio:.2f}"},
    {'指标': '总费用(万)',            '值': f"{stats.get('total_fees_wan', 0):.4f}"},
]

stats_out = pd.DataFrame(stats_rows)
stats_out.to_csv(OUT_DIR / 'step1_stats.csv', index=False, encoding='utf-8-sig')
print("\n=== 核心指标 ===")
for _, r in stats_out.iterrows():
    print(f"  {r['指标']:<16} {r['值']}")

# ── 年度收益表 ─────────────────────────────────────
result_df['year'] = result_df['trade_date'].dt.year
annual_rows = []
for year, grp in result_df.groupby('year'):
    grp_sorted = grp.sort_values('trade_date')
    nav_start = grp_sorted['nav'].iloc[0]
    nav_end   = grp_sorted['nav'].iloc[-1]
    yr_ret    = nav_end / nav_start - 1
    yr_mdd    = calc_max_drawdown(grp_sorted['nav'])
    yr_vol    = grp_sorted['d_ret'].std(ddof=1) * np.sqrt(252) if len(grp_sorted) > 1 else 0
    yr_shp    = ((nav_end/nav_start - 1) - REF_RATE) / yr_vol if yr_vol > 0 else 0
    annual_rows.append({
        '年份':         year,
        '期初净值':     round(nav_start, 4),
        '期末净值':     round(nav_end, 4),
        '年收益':       f"{yr_ret*100:+.2f}%",
        '年化波动率':   f"{yr_vol*100:.2f}%",
        '夏普比率':     f"{yr_shp:.4f}",
        '最大回撤':     f"{yr_mdd*100:+.2f}%",
        '交易天数':     len(grp_sorted),
    })

annual_out = pd.DataFrame(annual_rows)
annual_out.to_csv(OUT_DIR / 'step1_annual.csv', index=False, encoding='utf-8-sig')
print("\n=== 年度收益 ===")
print(annual_out.to_string(index=False))

print(f"\n已保存: step1_stats.csv | step1_annual.csv → {OUT_DIR}")
