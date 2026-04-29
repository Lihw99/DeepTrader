# -*- coding: utf-8 -*-
"""
回测结果分析 Step4 — 个股盈亏排行
输入: smallcap_v2_trades.csv
输出: 盈利Top + 亏损Top 各N只（CSV）
"""

import warnings
from pathlib import Path
import pandas as pd
warnings.filterwarnings('ignore')

EXP_DIR     = Path('/home/lihw/stock_selector_exp/backtest')
OUT_DIR     = Path('/home/lihw/stock_selector_exp/backtest')
STOCK_TOP_N = 20

# ── 读取交易记录 ──────────────────────────────────
trades_df = pd.read_csv(EXP_DIR / 'smallcap_v2_trades.csv', encoding='utf-8-sig')
print(f"交易记录: {len(trades_df)}行, 字段: {list(trades_df.columns)}")

# ── 筛选卖出记录 ──────────────────────────────────
sells = trades_df[trades_df['action'].str.startswith('sell')].copy()
sells['return_pct'] = pd.to_numeric(sells['return_pct'], errors='coerce')
sells = sells.dropna(subset=['return_pct'])

# ── 按股票汇总（每只股票的累计收益）──────────────────
# 用 entry_px * shares 近似买入金额，卖出时计算盈亏
if 'price' in sells.columns:
    sells['sell_value'] = sells['shares'] * sells['price']
    # 已实现盈亏（粗略）
    # 配对：同一只股票按时间排序后 FIFO
    sells['ts_code'] = sells['ts_code'].astype(str)
    sells = sells.sort_values(['ts_code', 'trade_date'])

    stock_stats = []
    for ts, grp in sells.groupby('ts_code'):
        rets = grp['return_pct'].dropna()
        if len(rets) == 0:
            continue
        # 多轮买卖：每一行是一个卖出，return_pct是相对于entry_px的收益率
        total_pnl_pct = 0.0
        for _, row in grp.iterrows():
            if pd.notna(row['return_pct']):
                total_pnl_pct += row['return_pct']
        avg_ret = rets.mean()
        n_trades = len(rets)
        wins  = (rets > 0).sum()
        losses = (rets <= 0).sum()
        stock_stats.append({
            '股票代码':     ts,
            '盈利次数':     int(wins),
            '亏损次数':     int(losses),
            '总交易次数':   n_trades,
            '胜率':        f"{wins/n_trades*100:.1f}%",
            '平均收益%':   f"{avg_ret:.2f}%",
            '累计收益%':   f"{total_pnl_pct:.2f}%",
            '最大单笔%':   f"{rets.max():.2f}%",
            '最差单笔%':   f"{rets.min():.2f}%",
        })

    stats_df = pd.DataFrame(stock_stats)
    # 盈利/亏损分开排行：
    # 盈利榜 = 累计收益最高，取前N只
    # 亏损榜 = 累计收益最低，取前N只（去除已出现在盈利榜的）
    # 转数值（去掉%转成float用于排序）
    def pct_to_float(s):
        try:
            return float(str(s).replace('%', ''))
        except:
            return 0.0

    stats_df['_sort_key'] = stats_df['累计收益%'].apply(pct_to_float)

    # 盈利榜：累计收益>0，取前N只（按累计收益降序）
    profit_df = stats_df[stats_df['_sort_key'] > 0].sort_values('_sort_key', ascending=False).head(STOCK_TOP_N).copy()
    top_profit_codes = set(profit_df['股票代码'])

    # 亏损榜：排除盈利榜 + 累计收益<=0，取前N只（按累计收益升序）
    loss_df = (stats_df[
                   (~stats_df['股票代码'].isin(top_profit_codes)) &
                   (stats_df['_sort_key'] <= 0)
               ]
               .sort_values('_sort_key', ascending=True)
               .head(STOCK_TOP_N).copy())

    profit_df.drop(columns=['_sort_key'], inplace=True)
    loss_df.drop(columns=['_sort_key'], inplace=True)
    profit_df.to_csv(OUT_DIR / 'step4_profit_top.csv', index=False, encoding='utf-8-sig', quoting=1)
    loss_df.to_csv(OUT_DIR / 'step4_loss_top.csv', index=False, encoding='utf-8-sig', quoting=1)

    print(f"\n=== 盈利 Top {STOCK_TOP_N} ===")
    print(profit_df.to_string(index=False))
    print(f"\n=== 亏损 Top {STOCK_TOP_N} ===")
    print(loss_df.to_string(index=False))
    print(f"\n已保存: step4_profit_top.csv | step4_loss_top.csv")
else:
    print("trades.csv 缺少 price 字段，无法计算个股盈亏")
