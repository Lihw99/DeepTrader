# -*- coding: utf-8 -*-
"""
回测结果分析 Step2 — 月度盈亏热力图
输入: smallcap_v2_result.csv
输出: 月度盈亏热力表（HTML）
"""

import json, warnings
from pathlib import Path
import pandas as pd
import numpy as np
warnings.filterwarnings('ignore')

EXP_DIR = Path('/home/lihw/stock_selector_exp/backtest')
OUT_DIR = Path('/home/lihw/stock_selector_exp/backtest')

# ── 读取净值 ─────────────────────────────────────
result_df = pd.read_csv(EXP_DIR / 'smallcap_v2_result.csv', encoding='utf-8-sig')
with open(EXP_DIR / 'smallcap_v2_stats.json', encoding='utf-8') as f:
    stats = json.load(f)

result_df['trade_date'] = pd.to_datetime(result_df['trade_date'], format='%Y%m%d')
result_df = result_df.sort_values('trade_date').reset_index(drop=True)
result_df['nav'] = result_df['equity_wan'] / result_df['equity_wan'].iloc[0]

init_cash = stats.get('init_cash_wan', 0.8)

# ── 月度重采样：取每月最后一个交易日 ───────────────
monthly = result_df.set_index('trade_date')['nav'].resample('ME').last()

# 月初 = 上月末（shift(1)），首月用期初净值
monthly_start = monthly.shift(1)
monthly_start.iloc[0] = result_df['nav'].iloc[0]

# 月度盈亏率
monthly_rate = monthly / monthly_start - 1

# 构建 {year: {month: {'rate': ..., 'amount': ...}}}
result = {}
for ts, rate in monthly_rate.items():
    if pd.isna(rate):
        continue
    year = ts.year
    month = ts.month
    start_nav = monthly_start[ts]
    amount = init_cash * start_nav * rate
    if year not in result:
        result[year] = {}
    result[year][month] = {'rate': rate, 'amount': amount}

# 年度汇总
for year, grp in result_df.groupby(result_df['trade_date'].dt.year):
    if year not in result:
        continue
    grp_sorted = grp.sort_values('trade_date')
    yr_start = grp_sorted['nav'].iloc[0]
    yr_end   = grp_sorted['nav'].iloc[-1]
    yr_rate  = yr_end / yr_start - 1
    result[year][0] = {'rate': yr_rate, 'amount': init_cash * yr_start * yr_rate}

# ── 渲染 HTML ─────────────────────────────────────
months_label = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月','年度']
month_keys  = list(range(1, 13)) + [0]

html = """
<style>
.m-table {border-collapse:collapse;width:100%;font-size:13px;font-family:Arial;}
.m-table th,.m-table td {padding:6px 10px;border:1px solid #DDD;text-align:center;}
.m-table th {background:#F6F6F6;font-weight:bold;}
.m-th {background:#F6F6F6 !important;font-weight:bold;text-align:center !important;}
</style>
<h3>Step2 月度盈亏热力图</h3>
<table class="m-table">
<thead><tr>
<th>年份</th>"""
for m in months_label:
    html += f'<th>{m}</th>'
html += '</tr></thead><tbody>'

for year in sorted(result.keys(), reverse=True):
    html += f'<tr><td class="m-th">{year}</td>'
    for mk in month_keys:
        data = result[year].get(mk)
        if data is None:
            html += '<td style="color:#CCC;">-</td>'
            continue
        rate = data['rate']
        color = '#D32F2F' if rate >= 0 else '#388E3C'
        bg    = '#FFF5F5' if rate >= 0 else '#F5FFF5'
        if mk == 0:
            bg = '#FFF0E0' if rate >= 0 else '#F0FFF0'
        html += f'''<td style="background:{bg};color:{color};font-weight:normal;">
        {rate*100:+.1f}%</td>'''
    html += '</tr>'
html += '</tbody></table>'

# 保存HTML
html_path = OUT_DIR / 'step2_monthly_heatmap.html'
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"已保存: {html_path}")

# 同时输出CSV
rows = []
for year in sorted(result.keys(), reverse=True):
    row = {'年份': year}
    for mk, ml in zip(month_keys, months_label):
        d = result[year].get(mk)
        row[ml] = f"{d['rate']*100:+.2f}%" if d else '-'
    rows.append(row)
pd.DataFrame(rows).to_csv(OUT_DIR / 'step2_monthly.csv', index=False, encoding='utf-8-sig', quoting=1)
print(f"已保存: {OUT_DIR / 'step2_monthly.csv'}")
print("\n月度盈亏预览：")
for row in rows:
    print(row)
