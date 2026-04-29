# -*- coding: utf-8 -*-
"""
回测结果分析 - 合并版
将 Step1~Step7 的分析功能合并为一个可执行脚本

数据文件: {PREFIX}_result.csv, {PREFIX}_trades.csv, {PREFIX}_stats.json
输出目录: 与数据目录相同
"""

import json, warnings
from pathlib import Path
import pandas as pd
import numpy as np

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════
# 配置 - 按需修改这三个参数
# ═══════════════════════════════════════════════════════════
DATA_DIR = Path('D:/share/代码备份')          # 数据文件所在目录
PREFIX   = 'zycash_v2'                         # 文件名前缀 (smallcap_v2 / zycash_v2 等)
OUT_DIR  = DATA_DIR                             # 输出目录
# ═══════════════════════════════════════════════════════════

REF_RATE = 0.03   # 无风险利率（3%）

# ── 读取数据 ─────────────────────────────────────
result_file = DATA_DIR / f'{PREFIX}_result.csv'
trades_file = DATA_DIR / f'{PREFIX}_trades.csv'
stats_file  = DATA_DIR / f'{PREFIX}_stats.json'

print(f"读取数据: {result_file}")
result_df = pd.read_csv(result_file, encoding='utf-8-sig')
with open(stats_file, encoding='utf-8') as f:
    stats = json.load(f)

result_df['trade_date'] = pd.to_datetime(result_df['trade_date'], format='%Y%m%d')
result_df = result_df.sort_values('trade_date').reset_index(drop=True)
result_df['nav'] = result_df['equity_wan'] / result_df['equity_wan'].iloc[0]
result_df['d_ret'] = result_df['nav'].pct_change()
result_df.loc[0, 'd_ret'] = result_df['nav'].iloc[0] / 1 - 1

print(f"数据: {result_df['trade_date'].iloc[0].date()} → {result_df['trade_date'].iloc[-1].date()}, "
      f"共 {len(result_df)} 个交易日\n")

trades_df = pd.read_csv(trades_file, encoding='utf-8-sig')

# ═══════════════════════════════════════════════════════════
# Step 1 — 核心统计
# ═══════════════════════════════════════════════════════════
print("=" * 60)
print("Step 1 — 核心统计")
print("=" * 60)

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

stats_rows = [
    {'指标': '策略名',                '值': stats.get('strategy', PREFIX)},
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
for _, r in stats_out.iterrows():
    print(f"  {r['指标']:<16} {r['值']}")

# 年度收益
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
        '年份': year, '期初净值': round(nav_start, 4), '期末净值': round(nav_end, 4),
        '年收益': f"{yr_ret*100:+.2f}%", '年化波动率': f"{yr_vol*100:.2f}%",
        '夏普比率': f"{yr_shp:.4f}", '最大回撤': f"{yr_mdd*100:+.2f}%", '交易天数': len(grp_sorted),
    })
annual_out = pd.DataFrame(annual_rows)
annual_out.to_csv(OUT_DIR / 'step1_annual.csv', index=False, encoding='utf-8-sig')
print(f"\n年度收益：\n{annual_out.to_string(index=False)}")

# ═══════════════════════════════════════════════════════════
# Step 2 — 月度盈亏热力图
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("Step 2 — 月度盈亏热力图")
print("=" * 60)

init_cash = stats.get('init_cash_wan', 0.8)
monthly = result_df.set_index('trade_date')['nav'].resample('ME').last()
monthly_start = monthly.shift(1)
monthly_start.iloc[0] = result_df['nav'].iloc[0]
monthly_rate = monthly / monthly_start - 1

result_map = {}
for ts, rate in monthly_rate.items():
    if pd.isna(rate):
        continue
    year = ts.year; month = ts.month
    start_nav = monthly_start[ts]
    amount = init_cash * start_nav * rate
    if year not in result_map:
        result_map[year] = {}
    result_map[year][month] = {'rate': rate, 'amount': amount}

for year, grp in result_df.groupby(result_df['trade_date'].dt.year):
    if year not in result_map:
        continue
    grp_sorted = grp.sort_values('trade_date')
    yr_start = grp_sorted['nav'].iloc[0]
    yr_end   = grp_sorted['nav'].iloc[-1]
    yr_rate  = yr_end / yr_start - 1
    result_map[year][0] = {'rate': yr_rate, 'amount': init_cash * yr_start * yr_rate}

months_label = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月','年度']
month_keys  = list(range(1, 13)) + [0]

html = """
<style>
.m-table {border-collapse:collapse;width:100%;font-size:13px;font-family:Arial;}
.m-table th,.m-table td {padding:6px 10px;border:1px solid #DDD;text-align:center;}
.m-table th {background:#F6F6F6;font-weight:bold;}
.m-th {background:#F6F6F6 !important;font-weight:bold;text-align:center !important;}
</style>
<h3>月度盈亏热力图</h3>
<table class="m-table">
<thead><tr><th>年份</th>"""
for m in months_label:
    html += f'<th>{m}</th>'
html += '</tr></thead><tbody>'

for year in sorted(result_map.keys(), reverse=True):
    html += f'<tr><td class="m-th">{year}</td>'
    for mk in month_keys:
        data = result_map[year].get(mk)
        if data is None:
            html += '<td style="color:#CCC;">-</td>'
            continue
        rate = data['rate']
        color = '#D32F2F' if rate >= 0 else '#388E3C'
        bg    = '#FFF5F5' if rate >= 0 else '#F5FFF5'
        if mk == 0:
            bg = '#FFF0E0' if rate >= 0 else '#F0FFF0'
        html += f'<td style="background:{bg};color:{color};">{rate*100:+.1f}%</td>'
    html += '</tr>'
html += '</tbody></table>'

html_path = OUT_DIR / 'step2_monthly_heatmap.html'
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"已保存: {html_path}")

rows = []
for year in sorted(result_map.keys(), reverse=True):
    row = {'年份': year}
    for mk, ml in zip(month_keys, months_label):
        d = result_map[year].get(mk)
        row[ml] = f"{d['rate']*100:+.2f}%" if d else '-'
    rows.append(row)
pd.DataFrame(rows).to_csv(OUT_DIR / 'step2_monthly.csv', index=False, encoding='utf-8-sig', quoting=1)
print(f"已保存: {OUT_DIR / 'step2_monthly.csv'}")
print("月度盈亏预览：")
for row in rows:
    print(row)

# ═══════════════════════════════════════════════════════════
# Step 3 — 最大回撤
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("Step 3 — 最大回撤")
print("=" * 60)

result_df['rolling_max'] = result_df['nav'].cummax()
result_df['drawdown']    = (result_df['nav'] - result_df['rolling_max']) / result_df['rolling_max']
result_df['is_high'] = (result_df['drawdown'] >= -1e-7)
result_df['period_id'] = result_df['is_high'].cumsum()

dd_list = []
for pid, grp in result_df.groupby('period_id'):
    if len(grp) <= 1:
        continue
    if grp.index[0] < 20:
        continue
    m_dd = grp['drawdown'].min()
    if m_dd < -0.001:
        s_idx  = grp.index[0]
        v_idx  = grp['drawdown'].idxmin()
        s_date = result_df.loc[s_idx, 'trade_date']
        v_date = result_df.loc[v_idx, 'trade_date']
        last_idx = grp.index[-1]
        r_date = None; r_days = None
        if last_idx + 1 < len(result_df):
            next_nav = result_df.loc[last_idx + 1, 'nav']
            peak_nav = result_df.loc[s_idx, 'rolling_max']
            if next_nav >= peak_nav:
                r_date = result_df.loc[last_idx + 1, 'trade_date']
                r_days = (r_date - s_date).days
        dd_list.append({
            '跌落日期': s_date.strftime('%Y-%m-%d'),
            '谷底日期': v_date.strftime('%Y-%m-%d'),
            '最大回撤': f"{m_dd*100:.2f}%",
            '回撤幅度': m_dd,
            '跌落净值': round(result_df.loc[s_idx, 'rolling_max'], 4),
            '谷底净值': round(result_df.loc[v_idx, 'nav'], 4),
            '解套日期': r_date.strftime('%Y-%m-%d') if r_date else '尚待解套',
            '解套天数': r_days if r_days else '-',
        })

top_dd = sorted(dd_list, key=lambda x: x['回撤幅度'])[:10]
out_df = pd.DataFrame(top_dd)[['跌落日期','谷底日期','最大回撤','跌落净值','谷底净值','解套日期','解套天数']]
out_df.to_csv(OUT_DIR / 'step3_drawdown.csv', index=False, encoding='utf-8-sig', quoting=1)
print(f"已保存: {OUT_DIR / 'step3_drawdown.csv'}")
print(f"\n=== 最大10次回撤 ===")
print(out_df.to_string(index=False))
print(f"\n共发现 {len(dd_list)} 次回撤 > 0.1%")

# ═══════════════════════════════════════════════════════════
# Step 4 — 个股盈亏
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("Step 4 — 个股盈亏")
print("=" * 60)

sells = trades_df[trades_df['action'].str.startswith('sell')].copy()
sells['return_pct'] = pd.to_numeric(sells['return_pct'], errors='coerce')
sells = sells.dropna(subset=['return_pct'])

if 'price' in sells.columns:
    sells['sell_value'] = sells['shares'] * sells['price']
    sells['ts_code'] = sells['ts_code'].astype(str)
    sells = sells.sort_values(['ts_code', 'trade_date'])

    stock_stats = []
    for ts, grp in sells.groupby('ts_code'):
        rets = grp['return_pct'].dropna()
        if len(rets) == 0:
            continue
        total_pnl_pct = 0.0
        for _, row in grp.iterrows():
            if pd.notna(row['return_pct']):
                total_pnl_pct += row['return_pct']
        avg_ret = rets.mean()
        n_trades = len(rets)
        wins  = (rets > 0).sum()
        losses = (rets <= 0).sum()
        stock_stats.append({
            '股票代码': ts, '盈利次数': int(wins), '亏损次数': int(losses),
            '总交易次数': n_trades, '胜率': f"{wins/n_trades*100:.1f}%",
            '平均收益%': f"{avg_ret:.2f}%", '累计收益%': f"{total_pnl_pct:.2f}%",
            '最大单笔%': f"{rets.max():.2f}%", '最差单笔%': f"{rets.min():.2f}%",
        })

    stats_df = pd.DataFrame(stock_stats)

    def pct_to_float(s):
        try:
            return float(str(s).replace('%', ''))
        except:
            return 0.0

    stats_df['_sort_key'] = stats_df['累计收益%'].apply(pct_to_float)
    profit_df = stats_df[stats_df['_sort_key'] > 0].sort_values('_sort_key', ascending=False).head(20).copy()
    top_profit_codes = set(profit_df['股票代码'])
    loss_df = (stats_df[
                   (~stats_df['股票代码'].isin(top_profit_codes)) &
                   (stats_df['_sort_key'] <= 0)
               ].sort_values('_sort_key', ascending=True).head(20).copy())

    profit_df.drop(columns=['_sort_key'], inplace=True)
    loss_df.drop(columns=['_sort_key'], inplace=True)
    profit_df.to_csv(OUT_DIR / 'step4_profit_top.csv', index=False, encoding='utf-8-sig', quoting=1)
    loss_df.to_csv(OUT_DIR / 'step4_loss_top.csv', index=False, encoding='utf-8-sig', quoting=1)
    print(f"已保存: step4_profit_top.csv | step4_loss_top.csv")
    print(f"\n=== 盈利 Top 20 ===")
    print(profit_df.to_string(index=False))
    print(f"\n=== 亏损 Top 20 ===")
    print(loss_df.to_string(index=False))
else:
    print("trades.csv 缺少 price 字段，跳过个股盈亏分析")

# ═══════════════════════════════════════════════════════════
# Step 5 — 交易质量
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("Step 5 — 交易质量")
print("=" * 60)

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

nav_series = result_df['nav']
rolling_max = nav_series.cummax()
drawdowns = (nav_series - rolling_max) / rolling_max
mdd = drawdowns.min()
calmar = ann_ret / abs(mdd) if mdd != 0 else 0

rows5 = [
    {'指标': '卖出总笔数',       '值': total,           '说明': '所有卖出操作'},
    {'指标': '盈利笔数',         '值': int(wins),        '说明': '收益>0'},
    {'指标': '亏损笔数',         '值': int(losses),      '说明': '收益<=0'},
    {'指标': '卖出胜率',         '值': f"{win_rate*100:.2f}%", '说明': '盈利笔数/总笔数'},
    {'指标': '平均盈利',         '值': f"{avg_win*100:.2f}%",  '说明': '盈利交易平均收益率'},
    {'指标': '平均亏损',         '值': f"{avg_loss*100:.2f}%", '说明': '亏损交易平均亏损率'},
    {'指标': '盈亏比',           '值': f"{pnl_ratio:.2f}",      '说明': '平均盈利/平均亏损绝对值'},
    {'指标': '单笔期望收益',     '值': f"{win_rate*avg_win - (1-win_rate)*avg_loss:.4f}", '说明': '每笔交易期望值'},
    {'指标': '卡尔马比率',       '值': f"{calmar:.2f}",         '说明': '年化收益/最大回撤'},
    {'指标': '总费用(万)',       '值': f"{stats.get('total_fees_wan', 0):.4f}", '说明': '佣金+印花税合计'},
]
out5 = pd.DataFrame(rows5)
out5.to_csv(OUT_DIR / 'step5_trade_quality.csv', index=False, encoding='utf-8-sig', quoting=1)
print(f"已保存: {OUT_DIR / 'step5_trade_quality.csv'}")
print(out5.to_string(index=False))

# ═══════════════════════════════════════════════════════════
# Step 6 — 持仓行为
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("Step 6 — 持仓行为")
print("=" * 60)

trades_df['trade_date'] = pd.to_datetime(trades_df['trade_date'], format='%Y%m%d')
trades_df = trades_df.sort_values(['ts_code', 'trade_date'])

buys = trades_df[trades_df['action'] == 'buy'][['trade_date', 'ts_code']].copy()
buys.columns = ['buy_date', 'ts_code']
sells6 = trades_df[trades_df['action'].str.startswith('sell')][['trade_date', 'ts_code']].copy()
sells6.columns = ['sell_date', 'ts_code']

hold_days = []
for ts in buys['ts_code'].unique():
    ts_buys  = buys[buys['ts_code'] == ts].sort_values('buy_date')['buy_date'].tolist()
    ts_sells = sells6[sells6['ts_code'] == ts].sort_values('sell_date')['sell_date'].tolist()
    queue = []
    for b in ts_buys:
        queue.append(b)
    for s in ts_sells:
        if queue:
            bt = queue.pop(0)
            days = (s - bt).days
            if days >= 0:
                hold_days.append(days)

if hold_days:
    sr = pd.Series(hold_days)
    total = len(sr)
    avg_d  = sr.mean(); med_d  = sr.median()
    max_d  = sr.max(); min_d  = sr.min()
    short_ = (sr < 5).sum()
    mid_   = ((sr >= 5) & (sr < 20)).sum()
    long_  = (sr >= 20).sum()

    rows6 = [
        {'指标': '配对成功笔数',   '值': total},
        {'指标': '平均持仓天数',   '值': f"{avg_d:.1f} 天"},
        {'指标': '中位持仓天数',   '值': f"{med_d:.0f} 天"},
        {'指标': '最长持仓',       '值': f"{int(max_d)} 天"},
        {'指标': '最短持仓',       '值': f"{int(min_d)} 天"},
        {'指标': '超短线(<5天)',   '值': f"{short_}笔 ({short_/total*100:.1f}%)"},
        {'指标': '短线(5~20天)',   '值': f"{mid_}笔 ({mid_/total*100:.1f}%)"},
        {'指标': '长线(>20天)',    '值': f"{long_}笔 ({long_/total*100:.1f}%)"},
    ]
    out6 = pd.DataFrame(rows6)
    out6.to_csv(OUT_DIR / 'step6_holding_behavior.csv', index=False, encoding='utf-8-sig', quoting=1)
    print(f"已保存: {OUT_DIR / 'step6_holding_behavior.csv'}")
    print(out6.to_string(index=False))
else:
    print("未匹配到买卖配对，跳过持仓行为分析")

# ═══════════════════════════════════════════════════════════
# Step 7 — 交易时间分布
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("Step 7 — 交易时间分布")
print("=" * 60)

sells7 = trades_df[trades_df['action'].str.startswith('sell')].copy()
sells7['trade_date'] = pd.to_datetime(sells7['trade_date'], format='%Y%m%d')
sells7['return_pct'] = pd.to_numeric(sells7['return_pct'], errors='coerce')
sells7 = sells7.dropna(subset=['return_pct'])
sells7['return_decimal'] = sells7['return_pct'] / 100
sells7['weekday'] = sells7['trade_date'].dt.weekday
sells7['month']   = sells7['trade_date'].dt.month

weekday_names = ['周一','周二','周三','周四','周五']
wd_rows = []
for i, label in enumerate(weekday_names):
    sub = sells7[sells7['weekday'] == i]
    cnt  = len(sub)
    wins = (sub['return_decimal'] > 0).sum()
    wr   = wins / cnt if cnt > 0 else 0
    avg  = sub['return_decimal'].mean() if cnt > 0 else 0
    wd_rows.append({'星期': label, '交易笔数': cnt, '胜率': f"{wr*100:.1f}%",
                    '平均收益%': f"{avg*100:.2f}%" if cnt > 0 else '-'})

mo_rows = []
for m in range(1, 13):
    sub = sells7[sells7['month'] == m]
    cnt  = len(sub)
    wins = (sub['return_decimal'] > 0).sum()
    wr   = wins / cnt if cnt > 0 else 0
    avg  = sub['return_decimal'].mean() if cnt > 0 else 0
    mo_rows.append({'月份': f'{m}月', '交易笔数': cnt, '胜率': f"{wr*100:.1f}%",
                    '平均收益%': f"{avg*100:.2f}%" if cnt > 0 else '-'})

wd_df = pd.DataFrame(wd_rows)
mo_df = pd.DataFrame(mo_rows)
wd_df.to_csv(OUT_DIR / 'step7_weekday_dist.csv', index=False, encoding='utf-8-sig', quoting=1)
mo_df.to_csv(OUT_DIR / 'step7_month_dist.csv', index=False, encoding='utf-8-sig', quoting=1)
print(f"已保存: step7_weekday_dist.csv | step7_month_dist.csv")
print("\n按星期：")
print(wd_df.to_string(index=False))
print("\n按月份：")
print(mo_df.to_string(index=False))

# ═══════════════════════════════════════════════════════════
# 完成
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("全部分析完成！")
print(f"输出目录: {OUT_DIR}")
print("生成文件:")
for f in sorted(OUT_DIR.glob('step*.csv')):
    print(f"  {f.name}")
html_file = OUT_DIR / 'step2_monthly_heatmap.html'
if html_file.exists():
    print(f"  {html_file.name}")
print("=" * 60)