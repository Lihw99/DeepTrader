# -*- coding: utf-8 -*-
"""
回测结果分析 Step3 — 最大N次回撤
输入: smallcap_v2_result.csv
输出: TOP N次回撤详情表（CSV）
"""

import json, warnings
from pathlib import Path
import pandas as pd
import numpy as np
warnings.filterwarnings('ignore')

EXP_DIR  = Path('/home/lihw/stock_selector_exp/backtest')
OUT_DIR  = Path('/home/lihw/stock_selector_exp/backtest')
TOP_N    = 10   # 显示最惨的前N次回撤

# ── 读取 ─────────────────────────────────────────
result_df = pd.read_csv(EXP_DIR / 'smallcap_v2_result.csv', encoding='utf-8-sig')
result_df['trade_date'] = pd.to_datetime(result_df['trade_date'], format='%Y%m%d')
result_df = result_df.sort_values('trade_date').reset_index(drop=True)
result_df['nav'] = result_df['equity_wan'] / result_df['equity_wan'].iloc[0]

# ── 计算回撤序列 ──────────────────────────────────
result_df['rolling_max'] = result_df['nav'].cummax()
result_df['drawdown']    = (result_df['nav'] - result_df['rolling_max']) / result_df['rolling_max']

# 标记新高点（drawdown=0的位置）
result_df['is_high'] = (result_df['drawdown'] >= -1e-7)
result_df['period_id'] = result_df['is_high'].cumsum()

# ── 提取每段回撤（过滤建仓期前20日） ────────────────
dd_list = []
for pid, grp in result_df.groupby('period_id'):
    if len(grp) <= 1:
        continue
    # 跳过建仓期（前20个交易日）
    if grp.index[0] < 20:
        continue
    m_dd = grp['drawdown'].min()
    if m_dd < -0.001:  # 只记录超过0.1%的回撤
        s_idx  = grp.index[0]
        v_idx  = grp['drawdown'].idxmin()
        s_date = result_df.loc[s_idx, 'trade_date']
        v_date = result_df.loc[v_idx, 'trade_date']
        # 找解套日：回撤恢复的前一天
        last_idx = grp.index[-1]
        r_date = None
        r_days = None
        if last_idx + 1 < len(result_df):
            next_nav = result_df.loc[last_idx + 1, 'nav']
            peak_nav = result_df.loc[s_idx, 'rolling_max']
            # 等于或超过初始高点才算出套
            if next_nav >= peak_nav:
                r_date = result_df.loc[last_idx + 1, 'trade_date']
                r_days = (r_date - s_date).days
        dd_list.append({
            '跌落日期':   s_date.strftime('%Y-%m-%d'),
            '谷底日期':   v_date.strftime('%Y-%m-%d'),
            '最大回撤':   f"{m_dd*100:.2f}%",
            '回撤幅度':   m_dd,
            '跌落净值':   round(result_df.loc[s_idx, 'rolling_max'], 4),
            '谷底净值':   round(result_df.loc[v_idx, 'nav'], 4),
            '解套日期':   r_date.strftime('%Y-%m-%d') if r_date else '尚待解套',
            '解套天数':   r_days if r_days else '-',
        })

# 取最惨的TOP_N
top_dd = sorted(dd_list, key=lambda x: x['回撤幅度'])[:TOP_N]

# 输出
out_df = pd.DataFrame(top_dd)[['跌落日期','谷底日期','最大回撤','跌落净值','谷底净值','解套日期','解套天数']]
out_df.to_csv(OUT_DIR / 'step3_drawdown.csv', index=False, encoding='utf-8-sig', quoting=1)
print(f"已保存: {OUT_DIR / 'step3_drawdown.csv'}")
print(f"\n=== 最大{TOP_N}次回撤 ===")
print(out_df.to_string(index=False))
print(f"\n共发现 {len(dd_list)} 次回撤 > 0.1%")
