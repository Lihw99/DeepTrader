# coding=utf-8
"""
jq_lite.py — 聚宽语法本地回测兼容层（第一阶段）
===============================================
将聚宽(JQ)策略语法翻译为 Backtrader 执行。

支持 P0 功能：
  - get_price(security, count, frequency, fields, fq)
  - history(count, unit, field, security_list, df)
  - order(security, amount)          / order_target(security, amount)
  - g 全局变量（self.g）
  - context（current_dt / portfolio / available_cash / positions）
  - set_benchmark / set_order_cost
  - initialize(context) / handle_data(context, data)

数据来源：
  - 优先使用本地 Parquet 数据（/mnt/d/A股全数据260320/）
  - Tushare Pro 作为补充（需配置 token）

使用方式：
    from jq_lite import *

    def initialize(context):
        context stock = "000001.SZ"

    def handle_data(context, data):
        order(context.stock, 100)
"""

import os
import sys
from datetime import datetime
from typing import Union, List, Optional

import numpy as np
import pandas as pd
import backtrader as bt

# ============================================================
# 常量
# ============================================================
STOCK_CODE_MAP = {
    "XSHE": "SZ",  # 聚宽 .XSHE → .SZ
    "XSHG": "SH",  # 聚宽 .XSHG → .SH
}
REVERSE_CODE_MAP = {
    "SZ": "XSHE",
    "SH": "XSHG",
}

# 默认复权方式
DEFAULT_FQ = "front"  # 前复权

# 数据目录（本地Parquet）
DATA_DIR = "/mnt/d/A股全数据260320/"


# ============================================================
# 工具函数
# ============================================================
def _jq_to_tushare_code(code: str) -> str:
    """聚宽代码 → Tushare代码，如 000001.XSHE → 000001.SZ"""
    if "." in code:
        symbol, market = code.split(".")
        if market in STOCK_CODE_MAP:
            return f"{symbol}.{STOCK_CODE_MAP[market]}"
    return code


def _tushare_to_jq_code(code: str) -> str:
    """Tushare代码 → 聚宽代码，如 000001.SZ → 000001.XSHE"""
    if "." in code:
        symbol, market = code.split(".")
        if market in REVERSE_CODE_MAP:
            return f"{symbol}.{REVERSE_CODE_MAP[market]}"
    return code


def _parse_date(date_str: str) -> datetime:
    """解析 YYYYMMDD 格式日期"""
    if isinstance(date_str, datetime):
        return date_str
    return datetime.strptime(str(date_str), "%Y%m%d")


def _normalize_frequency(freq: str) -> str:
    """将聚宽频率字符串转为标准格式（d/m）"""
    freq = freq.lower()
    if freq == "1d":
        return "D"
    elif freq.endswith("m"):
        return freq  # 如 "5m", "15m"
    elif freq.endswith("d"):
        return "D"
    return "D"


# ============================================================
# 数据加载
# ============================================================
def _load_parquet(stock_code: str, start_date: str, end_date: str, adjust: str = "front") -> Optional[pd.DataFrame]:
    """
    从本地Parquet加载K线数据。

    数据目录结构: /mnt/d/A股全数据260320/个股日线/
    文件命名: {ts_code}_{start}_{end}.parquet  例如 000001.SZ_20200101_20260320.parquet

    Args:
        stock_code: Tushare格式股票代码，如 "000001.SZ"
        start_date: YYYYMMDD
        end_date: YYYYMMDD
        adjust: "front"(前复权) / "back"(后复权) / "none"(不复权)

    Returns:
        DataFrame，字段：date, open, high, low, close, volume
    """
    import os

    STOCK_DATA_DIR = "/mnt/d/A股全数据260320/个股日线/"
    if not os.path.exists(STOCK_DATA_DIR):
        print(f"[jq_lite] 本地数据目录不存在: {STOCK_DATA_DIR}")
        return None

    start_dt = start_date.replace("-", "")
    end_dt = end_date.replace("-", "")

    # 查找匹配的文件（前缀 = 股票代码 + "_"）
    prefix = stock_code + "_"  # "000001.SZ_"
    matching_files = [f for f in os.listdir(STOCK_DATA_DIR) if f.startswith(prefix) and f.endswith(".parquet")]

    if not matching_files:
        return None

    all_rows = []
    for fname in matching_files:
        fpath = os.path.join(STOCK_DATA_DIR, fname)
        try:
            df = pd.read_parquet(fpath)
            # trade_date 统一转为字符串（可能是 int 或 str）
            if "trade_date" in df.columns:
                df["trade_date"] = df["trade_date"].astype(str)
            elif "date" in df.columns:
                df["trade_date"] = df["date"].astype(str)

            # 按日期过滤
            df = df[
                (df["trade_date"] >= start_dt) & (df["trade_date"] <= end_dt)
            ]
            if len(df) > 0:
                # 字段映射（统一命名）
                rename = {}
                if "trade_date" in df.columns:
                    rename["trade_date"] = "date"
                if "vol" in df.columns:
                    rename["vol"] = "volume"
                if rename:
                    df = df.rename(columns=rename)

                # 只保留需要的字段
                cols = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in df.columns]
                df = df[cols].copy()
                all_rows.append(df)

        except Exception as e:
            print(f"[jq_lite] 读取失败 {fname}: {e}")

    if not all_rows:
        return None

    # 合并，并按日期排序
    result = pd.concat(all_rows, ignore_index=True)
    result = result.sort_values("date")
    result = result.drop_duplicates(subset=["date"], keep="first")

    # date 转为 YYYY-MM-DD 格式
    result["date"] = pd.to_datetime(result["date"]).dt.strftime("%Y-%m-%d")

    return result


def _load_tushare(stock_code: str, start_date: str, end_date: str, adjust: str = "front") -> Optional[pd.DataFrame]:
    """
    通过Tushare Pro API加载K线数据。

    Args:
        stock_code: Tushare格式股票代码
        adjust: "1"=前复权 "2"=后复权 "3"=不复权
    """
    try:
        import tushare as ts

        # 读取token
        token_path = os.path.join(os.path.dirname(__file__), "token.txt")
        if os.path.exists(token_path):
            with open(token_path) as f:
                token = f.read().strip()
        else:
            # 回退到已知的token
            token = "zVqthiTTyQpJhOzfCdKfgRZTFHCEbMRKtdUUnDUTqBAKrzXwPAdOskmccOGLDQfb"

        pro = ts.pro_api(token)
        pro._DataApi__http_url = "http://121.40.135.59:8010/"

        # Tushare pro.daily 接受完整代码如 "000001.SZ"
        df = pro.daily(
            ts_code=stock_code,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )
        if df is None or df.empty:
            return None

        df = df.sort_values("trade_date")
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.rename(columns={
            "trade_date": "date",
            "vol": "volume",
        })
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        return df[["date", "open", "high", "low", "close", "volume"]]

    except Exception as e:
        print(f"[jq_lite] Tushare加载失败: {e}")
        return None


def load_stock_data(
    stock_code: str,
    start_date: str,
    end_date: str,
    adjust: str = "front",
) -> Optional[pd.DataFrame]:
    """
    统一数据加载入口：先本地Parquet，失败则Tushare。

    Args:
        stock_code: 聚宽格式股票代码，如 "000001.XSHE" 或 "000001.SZ"
        start_date: YYYYMMDD 或 YYYY-MM-DD
        end_date: YYYYMMDD 或 YYYY-MM-DD
        adjust: "front" / "back" / "none"

    Returns:
        DataFrame（date, open, high, low, close, volume）或 None
    """
    # 统一日期格式
    start_date = start_date.replace("-", "")
    end_date = end_date.replace("-", "")

    # 转换为Tushare格式
    ts_code = _jq_to_tushare_code(stock_code) if "." in stock_code else stock_code

    # 1. 尝试本地Parquet
    df = _load_parquet(ts_code, start_date, end_date, adjust)
    if df is not None and len(df) > 0:
        print(f"[jq_lite] {ts_code}: 本地Parquet加载成功 ({len(df)}条)")
        return df

    # 2. 尝试Tushare
    print(f"[jq_lite] {ts_code}: 本地无数据，尝试Tushare...")
    df = _load_tushare(ts_code, start_date, end_date, adjust)
    if df is not None and len(df) > 0:
        print(f"[jq_lite] {ts_code}: Tushare加载成功 ({len(df)}条)")
        return df

    print(f"[jq_lite] {ts_code}: 数据加载失败")
    return None


# ============================================================
# 核心 API 函数（供策略内部调用）
# ============================================================

def get_price(
    security: Union[str, List[str]],
    count: int = None,
    start_date: str = None,
    end_date: str = None,
    frequency: str = "1d",
    fields: List[str] = None,
    fq: str = "front",
) -> Union[pd.DataFrame, np.ndarray]:
    """
    获取股票历史行情，类似聚宽 get_price()。

    Args:
        security: 股票代码，如 "000001.SZ" 或 ["000001.SZ", "000002.SZ"]
        count: 获取多少条（从 end_date 往前数）
        start_date: YYYYMMDD
        end_date: YYYYMMDD
        frequency: "1d" / "1m" / "5m" 等（目前仅支持日线）
        fields: ["open", "close", "high", "low", "volume"]，None表示全部
        fq: "front"(前复权) / "back"(后复权) / "none"(不复权)

    Returns:
        单只股票: DataFrame
        多只股票: dict {code: DataFrame}
    """
    if frequency != "1d":
        raise NotImplementedError("目前仅支持日线 frequency='1d'")

    from datetime import timedelta

    # 确定 end_date
    if end_date is None:
        end_date = datetime.today().strftime("%Y%m%d")

    # 确定 start_date（从 count 推算，需要多取一些）
    if start_date is None and count is not None:
        # 粗略估算：每个交易日约间隔1天，多取50%用于缓冲
        fromdate = datetime.strptime(end_date, "%Y%m%d") - timedelta(days=int(count * 2))
        start_date = fromdate.strftime("%Y%m%d")
    elif start_date is None:
        start_date = "20150101"  # 默认取较早的数据

    # 加载数据
    if isinstance(security, str):
        df = load_stock_data(security, start_date or "", end_date or "", fq)
        if df is None:
            return pd.DataFrame()
        if count is not None:
            df = df.tail(count)
        if fields:
            available = [f for f in fields if f in df.columns]
            df = df[["date"] + available]
        return df
    else:
        result = {}
        for code in security:
            df = load_stock_data(code, start_date or "", end_date or "", fq)
            if df is not None:
                if count is not None:
                    df = df.tail(count)
                if fields:
                    available = [f for f in fields if f in df.columns]
                    df = df[["date"] + available]
                result[code] = df
        return result


def history(
    count: int,
    unit: str = "1d",
    field: str = "close",
    security_list: Union[str, List[str]] = None,
    df: bool = False,
) -> np.ndarray:
    """
    获取历史数据，类似聚宽 history()。

    Args:
        count: 获取多少条
        unit: "1d" / "1m" 等
        field: "open" / "close" / "high" / "low" / "volume"
        security_list: 股票代码列表，None表示使用上下文中的当前标的
        df: True返回DataFrame，False返回numpy数组

    Returns:
        numpy数组或DataFrame
    """
    # 注意：history 是日内调用，只能获取已经加载的历史数据
    # 在 Backtrader 中，数据已经在 self.datas 中
    # 这个函数在 jq_lite 策略框架中由 JQStrategy 维护历史缓存
    raise NotImplementedError(
        "history() 已在 JQStrategy 内部实现，请在策略类中通过 self.history() 调用"
    )


def order(
    security: str,
    amount: int,
    price: float = None,
    style=None,
) -> None:
    """
    下单函数，类似聚宽 order()。
    正数买入，负数卖出。

    在 jq_lite 策略中，会调用 self.buy() 或 self.sell()。
    """
    raise NotImplementedError(
        "order() 已在 JQStrategy 内部实现，请在策略类中通过 self.order() 调用"
    )


def order_target(
    security: str,
    amount: int,
    price: float = None,
) -> None:
    """
    调仓到目标股数，类似聚宽 order_target()。
    """
    raise NotImplementedError(
        "order_target() 已在 JQStrategy 内部实现，请在策略类中通过 self.order_target() 调用"
    )


# ============================================================
# Backtrader Strategy 基类（核心）
# ============================================================

class JQStrategy(bt.Strategy):
    """
    聚宽兼容策略基类。

    用户只需定义 initialize(context) 和 handle_data(context, data)，
    无需关心 Backtrader 的 Cerebro/DataFeed。

    示例：
        class MyStrategy(JQStrategy):
            def initialize(self, context):
                context.stock = "000001.SZ"
                context.i = 0

            def handle_data(self, context, data):
                if context.i == 0:
                    order(context.stock, 100)
                context.i += 1
    """

    def __init__(self, **kwargs):
        super().__init__()

        # 聚宽兼容：self.g = 全局变量字典
        self.g = GlobalVars()

        # 聚宽兼容：context（包含 current_dt / portfolio / positions）
        self._context = ContextWrapper(self)

        # 初始化用户自定义 context（用户在 initialize 中填充）
        self._user_context = ContextDict()

        # 用户在 initialize 中填充 context 后，handle_data 每次 bar 调用
        self._initialized = False

        # 追踪历史数据（供 self.history() 使用）
        self._history_cache = {}  # {order_book_id: list of dicts}

        # 追踪所有订单（供 get_orders / get_open_orders / cancel 使用）
        self.order_dict = {}  # {ref: order}

        # 处理 kwargs（来自 cerebro.addstrategy 的参数）
        for k, v in kwargs.items():
            setattr(self, k, v)

    def prenext(self):
        """在所有数据加载完毕后初始化"""
        # Backtrader 的 nextstart 会在所有数据准备好后触发
        self.next()

    def nextstart(self):
        """所有数据加载完毕后，调用初始化 + 开始主循环"""
        # 先初始化
        self._call_initialize()
        # 再执行第一个 handle_data
        self._call_handle_data()
        # 标记已初始化
        self._initialized = True

    def next(self):
        """每个bar执行一次"""
        if not self._initialized:
            # 处理没有足够数据的情况
            return
        self._call_handle_data()

    def _call_initialize(self):
        """调用用户的 initialize(context)"""
        self._update_context()
        self.initialize(self._user_context)

    def _call_handle_data(self):
        """调用用户的 handle_data(context, data)"""
        self._update_context()
        data = DataWrapper(self.datas[0])
        self.handle_data(self._user_context, data)

    def _update_context(self):
        """更新 context 中的当前时间和持仓信息"""
        # current_dt
        self._user_context._current_dt = self.datas[0].datetime.date(0)

        # 更新 positions
        self._user_context._positions = self.positions

        # available_cash
        self._user_context._available_cash = self.broker.get_cash()

    # ---- 以下方法供用户在 handle_data 中调用 ----

    def history(
        self,
        count: int,
        unit: str = "1d",
        fields: Union[str, List[str]] = "close",
        df: bool = False,
    ) -> Union[np.ndarray, pd.DataFrame]:
        """
        获取最近 N 条历史数据（不包括当前bar），按时间从旧到新排列。

        Args:
            count: 条数
            unit: "1d"（仅支持日线）
            fields: 字段名，str 或 list。如 "close" / ["close", "open"] / ["high", "low"]
            df: True 返回 DataFrame，False 返回 numpy 数组（单字段时）或 dict（多字段时）

        Returns:
            df=False + str fields  → numpy array（时间从旧到新）
            df=False + list fields → dict {field: np.array}
            df=True                → DataFrame（index=日期, columns=fields）
        """
        if unit != "1d":
            raise NotImplementedError("目前仅支持 unit='1d'")

        data = self.datas[0]
        field_map = {"open": 0, "high": 1, "low": 2, "close": 3, "volume": 4}

        # 统一转 list
        if isinstance(fields, str):
            field_list = [fields]
        else:
            field_list = list(fields)

        # 校验字段
        for f in field_list:
            if f not in field_map:
                return np.array([]) if not df else pd.DataFrame()

        lookback = min(count, len(data))
        lines = data.lines

        # Backtrader buffer: 索引 0 = 当前bar，-1 = 上一个bar
        # lines[idx][-i] 获取第i个最近的bar（1=当前，2=上一个，...）
        def get_series(idx: int) -> np.ndarray:
            return np.array([lines[idx][-i] for i in range(lookback, 0, -1)])

        if not df:
            if len(field_list) == 1:
                return get_series(field_map[field_list[0]])
            else:
                return {f: get_series(field_map[f]) for f in field_list}
        else:
            # DataFrame 模式：列名=字段，行=时间从旧到新
            dates = [bt.num2date(lines[6][-i]) for i in range(lookback, 0, -1)]
            data_dict = {f: get_series(field_map[f]) for f in field_list}
            return pd.DataFrame(data_dict, index=dates, columns=field_list)

    def _get_field_idx(self, field: str) -> Optional[int]:
        """获取 Backtrader 数据字段索引"""
        field_map = {
            "open": 0, "high": 1, "low": 2, "close": 3,
            "volume": 4, "datetime": 6,
        }
        return field_map.get(field)

    def order(self, security: str, amount: int, price: float = None) -> None:
        """
        下单。正数买入，负数卖出（市价单）。

        Args:
            security: 股票代码（仅支持单只，当前数据源）
            amount: 正数买入，负数卖出
        """
        if amount > 0:
            self.buy(size=amount)
        elif amount < 0:
            self.sell(size=abs(amount))

    def order_target(self, security: str, target_amount: int) -> None:
        """
        调仓到目标股数。

        Args:
            security: 股票代码
            target_amount: 目标持仓股数（0=清仓）
        """
        # 当前持仓
        current = self.getposition(self.datas[0]).size
        diff = target_amount - current
        if diff != 0:
            if diff > 0:
                self.buy(size=diff)
            else:
                self.sell(size=abs(diff))

    # ---- RQAlpha 兼容 API ----

    def get_position(self, security: str = None) -> dict:
        """
        获取持仓（RQAlpha 风格），返回 dict 包含 amount/security/cost。

        Args:
            security: 股票代码，None 时使用当前数据源
        Returns:
            dict: {"security": str, "amount": int, "avg_cost": float}
        """
        data = self.datas[0]
        pos = self.getposition(data)
        return {
            "security": getattr(data, "_security", "unknown"),
            "amount": pos.size,
            "avg_cost": pos.price if pos.size > 0 else 0.0,
        }

    def update_universe(self, securities: Union[str, List[str]]) -> None:
        """
        更新当前股票池（仅支持单只，模拟调用）。
        多标的支持需要修改 Backtrader Cerebro 架构，此处做占位。
        """
        if isinstance(securities, str):
            securities = [securities]
        self._universe = securities

    def get_index_stocks(self, index_code: str, date: str = None) -> List[str]:
        """
        获取指数成分股。

        Args:
            index_code: 指数代码，如 "000300.XSHG"（沪深300）
            date: 日期，默认当前日期
        Returns:
            股票代码列表
        """
        # 通过 Tushare 获取指数成分
        index_map = {
            "000300.XSHG": "000300.SH",  # 沪深300
            "000905.XSHG": "000905.SH",  # 中证500
            "000001.XSHG": "000001.SH",  # 上证指数
            "399001.XSHE": "399001.SZ",  # 深证成指
        }
        ts_index = index_map.get(index_code, index_code.replace("XSHG",".SH").replace("XSHE",".SZ"))
        try:
            import tushare as ts
            token = "zVqthiTTyQpJhOzfCdKfgRZTFHCEbMRKtdUUnDUTqBAKrzXwPAdOskmccOGLDQfb"
            pro = ts.pro_api(token)
            pro._DataApi__http_url = "http://121.40.135.59:8010/"
            df = pro.index_weight(index_code=ts_index)
            if df is not None and not df.empty:
                return df["con_code"].tolist()
        except Exception:
            pass
        return []

    def get_all_securities(self, type_: str = "stock", date: str = None) -> pd.DataFrame:
        """
        获取全量证券列表。

        Args:
            type_: 类型，"stock" / "index" / "etf"
            date: 日期（默认全部）
        Returns:
            DataFrame: columns=[code, name, type, start_date, end_date]
        """
        # 从本地 Parquet 目录扫描所有股票文件
        data_dir = "/mnt/d/A股全数据260320/个股日线/"
        if not os.path.exists(data_dir):
            return pd.DataFrame(columns=["code", "name", "type", "start_date", "end_date"])

        files = os.listdir(data_dir)
        codes_seen = set()
        records = []
        for f in files:
            if not f.endswith(".parquet"):
                continue
            # 文件名格式: 000001.SZ_20170101_20191231.parquet
            code_part = f.rsplit("_", 2)[0]
            if code_part in codes_seen:
                continue
            codes_seen.add(code_part)
            records.append({
                "code": code_part,
                "name": code_part,
                "type": "stock",
                "start_date": "",
                "end_date": "",
            })
        return pd.DataFrame(records)

    def get_trade_days(self, start_date: str = None, end_date: str = None, count: int = None) -> List[str]:
        """
        获取交易日列表。

        Args:
            start_date: 开始日期
            end_date: 结束日期
            count: 取最近 N 个交易日（与 start/end 二选一）
        Returns:
            日期字符串列表 ["2020-01-02", ...]
        """
        try:
            import tushare as ts
            token = "zVqthiTTyQpJhOzfCdKfgRZTFHCEbMRKtdUUnDUTqBAKrzXwPAdOskmccOGLDQfb"
            pro = ts.pro_api(token)
            pro._DataApi__http_url = "http://121.40.135.59:8010/"
            if count:
                end_date = pd.Timestamp.today().strftime("%Y%m%d")
                start_date = (pd.Timestamp.today() - pd.Timedelta(days=count*2)).strftime("%Y%m%d")
            df = pro.trade_cal(
                start_date=start_date.replace("-","") if start_date else None,
                end_date=end_date.replace("-","") if end_date else None,
                is_open="A",
            )
            if df is not None and not df.empty:
                return df["cal_date"].sort_values().tolist()
        except Exception:
            pass
        return []

    def sma(self, period: int, field: str = "close") -> float:
        """
        计算简单移动平均（当前 bar 的 SMA 值）。

        Args:
            period: 周期
            field: 字段名
        Returns:
            SMA 浮点值（当前 bar）
        """
        arr = self.history(period, unit="1d", fields=field, df=False)
        if arr is None or len(arr) < period:
            return None
        return float(arr.mean())

    def set_benchmark(self, security: str) -> None:
        """
        设置基准指数，用于计算相对收益（Alpha 等指标）。
        目前为占位实现：Backtrader 基准功能较复杂，此处记录后供分析使用。

        Args:
            security: 基准代码，如 "000300.SH"（沪深300）
        """
        self._benchmark = security
        print(f"[jq_lite] 基准已设置为: {security}")

    def set_order_cost(self, commission: float, tax: float = None) -> None:
        """
        设置交易佣金（聚宽风格）。

        Args:
            commission: 佣金率，如 0.0003（万三）
            tax: 印花税率，如 0.001（千一），卖出时收取
        """
        self._commission = commission
        self._tax = tax if tax is not None else 0.001
        # 通过 broker 设置
        self.broker.setcommission(commission)
        print(f"[jq_lite] 佣金率: {commission:.4f}, 印花税: {self._tax:.4f}")

    def normalize_code(self, security: str) -> str:
        """
        标准化证券代码格式，确保返回 6 位数字 + .SH/.SZ 后缀。

        Args:
            security: 股票代码，支持 6 位数字 / 聚宽格式 / Tushare 格式
        Returns:
            标准化代码，如 "000001.SZ"
        """
        if not security:
            return security

        # 已经是标准格式
        if "." in security and len(security) == 10:
            return security.upper()

        # 6 位数字 → 补全后缀
        if security.isdigit() and len(security) == 6:
            # 判断沪深的简单规则（以 0/3/6 开头）
            if security.startswith(("0", "3")):
                return f"{security}.SZ"
            else:
                return f"{security}.SH"

        # 聚宽格式 .XSHE/.XSHG → .SZ/.SH
        if "." in security:
            code, suffix = security.split(".")
            if suffix.upper() == "XSHE":
                return f"{code}.SZ"
            elif suffix.upper() == "XSHG":
                return f"{code}.SH"
        return security

    def attribute_sid(self, security: str) -> str:
        """
        获取股票代码（纯数字部分），等价于聚宽的 attribute_sid()。

        Args:
            security: 标准格式代码，如 "000001.SZ"
        Returns:
            6 位股票代码，如 "000001"
        """
        if "." in security:
            return security.split(".")[0]
        return security

    def attribute_days(self, security: str = None, date: str = None) -> int:
        """
        获取股票上市天数。

        Args:
            security: 股票代码，None 时使用当前数据源
            date: 日期（默认当前日期）
        Returns:
            上市天数（int）
        """
        security = security or getattr(self.datas[0], "_security", "000001.SZ")
        # 尝试从 Tushare 获取上市日期
        try:
            import tushare as ts
            token = "zVqthiTTyQpJhOzfCdKfgRZTFHCEbMRKtdUUnDUTqBAKrzXwPAdOskmccOGLDQfb"
            pro = ts.pro_api(token)
            pro._DataApi__http_url = "http://121.40.135.59:8010/"
            df = pro.stock_basic(ts_code=self.normalize_code(security), fields="list_date")
            if df is not None and not df.empty:
                list_date = str(df.iloc[0]["list_date"])
                list_dt = pd.to_datetime(list_date)
                current_dt = pd.to_datetime(date) if date else self.datas[0].datetime.date(0)
                return (current_dt - list_dt).days
        except Exception:
            pass
        return 0

    def get_extras(self, security: str, attr_name: str, start_date: str = None, end_date: str = None, count: int = None) -> Union[pd.DataFrame, List]:
        """
        获取股票补充数据（聚宽 get_extras）。

        支持字段：
          - is_st: 是否 ST
          - is_delisted: 是否退市
          - list_date: 上市日期
          - delist_date: 退市日期

        Args:
            security: 股票代码
            attr_name: 属性名
            start_date / end_date / count: 日期范围
        Returns:
            DataFrame 或 list
        """
        security = self.normalize_code(security)
        try:
            import tushare as ts
            token = "zVqthiTTyQpJhOzfCdKfgRZTFHCEbMRKtdUUnDUTqBAKrzXwPAdOskmccOGLDQfb"
            pro = ts.pro_api(token)
            pro._DataApi__http_url = "http://121.40.135.59:8010/"
            df = pro.stock_basic(ts_code=security, fields="list_date,delist_date,is_hs,name")
            if df is not None and not df.empty:
                row = df.iloc[0]
                if attr_name == "list_date":
                    return [str(row["list_date"])] if pd.notna(row["list_date"]) else [""]
                elif attr_name == "delist_date":
                    val = row["delist_date"]
                    return [str(int(val))] if pd.notna(val) else [""]
                elif attr_name == "is_st":
                    name = str(row.get("name", ""))
                    return ["ST" in name]
        except Exception:
            pass
        return [] if count is None else pd.DataFrame()

    def get_valuation(self, securities: Union[str, List[str]] = None, start_date: str = None, end_date: str = None, count: int = None, fields: List[str] = None) -> pd.DataFrame:
        """
        获取估值数据（PE/市净率/市值等），聚宽 get_valuation()。

        字段：code,trade_date,pe_ttm,pe_ltm,pb,ps_ttm,ps_ltm,market_cap,circulating_market_cap

        Args:
            securities: 股票代码列表，None 时使用全部
            start_date / end_date / count: 日期范围
            fields: 返回字段列表
        Returns:
            DataFrame
        """
        if securities is None:
            securities = [getattr(self.datas[0], "_security", "000001.SZ")]
        if isinstance(securities, str):
            securities = [securities]

        securities = [self.normalize_code(s) for s in securities]
        try:
            import tushare as ts
            token = "zVqthiTTyQpJhOzfCdKfgRZTFHCEbMRKtdUUnDUTqBAKrzXwPAdOskmccOGLDQfb"
            pro = ts.pro_api(token)
            pro._DataApi__http_url = "http://121.40.135.59:8010/"

            # Tushare daily_basic 提供 PE/PB/市值
            if count:
                end_dt = pd.Timestamp.today().strftime("%Y%m%d")
                start_dt = (pd.Timestamp.today() - pd.Timedelta(days=count * 3)).strftime("%Y%m%d")
            else:
                end_dt = end_date.replace("-", "") if end_date else pd.Timestamp.today().strftime("%Y%m%d")
                start_dt = start_date.replace("-", "") if start_date else (pd.Timestamp.today() - pd.Timedelta(days=365)).strftime("%Y%m%d")

            all_dfs = []
            for code in securities:
                df = pro.daily_basic(
                    ts_code=self.normalize_code(code),
                    start_date=start_dt,
                    end_date=end_dt,
                    fields="ts_code,trade_date,close,pe_ttm,pb,ps_ttm,market_cap,circ_market_cap",
                )
                if df is not None and not df.empty:
                    df = df.rename(columns={
                        "ts_code": "code",
                        "close": "close",
                        "pe_ttm": "pe_ttm",
                        "pb": "pb",
                        "ps_ttm": "ps_ttm",
                        "market_cap": "market_cap",
                        "circ_market_cap": "circulating_market_cap",
                    })
                    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
                    all_dfs.append(df)

            if not all_dfs:
                return pd.DataFrame()

            result = pd.concat(all_dfs, ignore_index=True)
            if fields:
                available = [f for f in fields if f in result.columns]
                result = result[["code", "trade_date"] + available]
            else:
                result = result[["code", "trade_date", "close", "pe_ttm", "pb", "ps_ttm", "market_cap", "circulating_market_cap"]]
            return result.sort_values(["code", "trade_date"])
        except Exception as e:
            print(f"[jq_lite] get_valuation 失败: {e}")
            return pd.DataFrame()

    def get_fundamentals(self, security: str = None, start_date: str = None, end_date: str = None, count: int = None, stat_date: str = None, fields: List[str] = None) -> pd.DataFrame:
        """
        获取财务数据（资产负债表/利润表/现金流量表），聚宽 get_fundamentals()。

        Args:
            security: 股票代码，None 时使用当前数据源
            start_date / end_date: 日期范围
            count: 取最近 N 个财报季
            stat_date: 财报截止日期，如 "2024q3"
            fields: 返回字段
        Returns:
            DataFrame（可能为空，本地数据有限）
        """
        security = security or getattr(self.datas[0], "_security", "000001.SZ")
        security = self.normalize_code(security)

        # 尝试从本地基本面 parquet 读取
        data_dir = "/mnt/d/A股全数据260320/"
        fundamental_dir = os.path.join(data_dir, "fundamental")
        if os.path.exists(fundamental_dir):
            files = [f for f in os.listdir(fundamental_dir) if security.replace(".SZ","").replace(".SH","") in f and f.endswith(".parquet")]
            dfs = []
            for f in files:
                try:
                    df = pd.read_parquet(os.path.join(fundamental_dir, f))
                    dfs.append(df)
                except Exception:
                    pass
            if dfs:
                result = pd.concat(dfs, ignore_index=True)
                if fields:
                    available = [c for c in fields if c in result.columns]
                    result = result[available]
                return result

        # Tushare 财务接口（需要专业权限）
        try:
            import tushare as ts
            token = "zVqthiTTyQpJhOzfCdKfgRZTFHCEbMRKtdUUnDUTqBAKrzXwPAdOskmccOGLDQfb"
            pro = ts.pro_api(token)
            pro._DataApi__http_url = "http://121.40.135.59:8010/"

            # 获取利润表
            df = pro.fina_indicator(ts_code=security, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                df["trade_date"] = pd.to_datetime(df["end_date"]).dt.strftime("%Y-%m-%d")
                return df
        except Exception:
            pass
        return pd.DataFrame()

    def get_money_flow(self, securities: Union[str, List[str]] = None, start_date: str = None, end_date: str = None, count: int = None) -> pd.DataFrame:
        """
        获取资金流向数据，聚宽 get_money_flow()。

        Args:
            securities: 股票代码列表
            start_date / end_date: 日期范围
            count: 取最近 N 个交易日
        Returns:
            DataFrame: code,trade_date,buy_count,buy_amount,buy-elg-amount,...
        """
        if securities is None:
            securities = [getattr(self.datas[0], "_security", "000001.SZ")]
        if isinstance(securities, str):
            securities = [securities]
        securities = [self.normalize_code(s) for s in securities]

        try:
            import tushare as ts
            token = "zVqthiTTyQpJhOzfCdKfgRZTFHCEbMRKtdUUnDUTqBAKrzXwPAdOskmccOGLDQfb"
            pro = ts.pro_api(token)
            pro._DataApi__http_url = "http://121.40.135.59:8010/"

            if count:
                end_dt = pd.Timestamp.today().strftime("%Y%m%d")
                start_dt = (pd.Timestamp.today() - pd.Timedelta(days=count * 2)).strftime("%Y%m%d")
            else:
                end_dt = (end_date or pd.Timestamp.today()).strftime("%Y%m%d")
                start_dt = (start_date or (pd.Timestamp.today() - pd.Timedelta(days=30))).strftime("%Y%m%d")

            all_dfs = []
            for code in securities:
                df = pro.moneyflow(ts_code=code, start_date=start_dt, end_date=end_dt)
                if df is not None and not df.empty:
                    df = df.rename(columns={"ts_code": "code"})
                    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
                    all_dfs.append(df)
            if all_dfs:
                return pd.concat(all_dfs, ignore_index=True).sort_values(["code", "trade_date"])
        except Exception as e:
            print(f"[jq_lite] get_money_flow 失败: {e}")
        return pd.DataFrame()

    def get_price_limit(self, security: str = None, start_date: str = None, end_date: str = None, count: int = None) -> pd.DataFrame:
        """
        获取涨跌停价，聚宽 get_price_limit()。

        Returns:
            DataFrame: code,trade_date,pre_close,up_limit,down_limit
        """
        security = security or getattr(self.datas[0], "_security", "000001.SZ")
        security = self.normalize_code(security)

        try:
            import tushare as ts
            token = "zVqthiTTyQpJhOzfCdKfgRZTFHCEbMRKtdUUnDUTqBAKrzXwPAdOskmccOGLDQfb"
            pro = ts.pro_api(token)
            pro._DataApi__http_url = "http://121.40.135.59:8010/"

            if count:
                end_dt = pd.Timestamp.today().strftime("%Y%m%d")
                start_dt = (pd.Timestamp.today() - pd.Timedelta(days=count)).strftime("%Y%m%d")
            else:
                end_dt = (end_date or pd.Timestamp.today()).strftime("%Y%m%d")
                start_dt = (start_date or (pd.Timestamp.today() - pd.Timedelta(days=1))).strftime("%Y%m%d")

            df = pro.stk_limit(ts_code=security, start_date=start_dt, end_date=end_dt)
            if df is not None and not df.empty:
                df = df.rename(columns={"ts_code": "code", "trade_date": "trade_date"})
                df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
                return df
        except Exception:
            pass

        # 回退：用当前 bar 数据估算涨跌停（±10% 或 ±20%）
        data = self.datas[0]
        close = data.close[0]
        up_limit = close * 1.10
        down_limit = close * 0.90
        return pd.DataFrame([{
            "code": security,
            "trade_date": bt.num2date(data.datetime[0]).strftime("%Y-%m-%d"),
            "up_limit": round(up_limit, 2),
            "down_limit": round(down_limit, 2),
        }])

    def cancel(self, order_id: int) -> None:
        """
        撤销订单（RQAlpha 兼容）。

        Args:
            order_id: 订单 ID
        """
        for order in self.order_dict.values():
            if order.ref == order_id:
                self.cancel(order)
                return
        print(f"[jq_lite] cancel: 订单 {order_id} 未找到")

    def get_orders(self, security: str = None, status: str = None, start_date: str = None, end_date: str = None, count: int = None) -> List:
        """
        获取订单历史，聚宽 get_orders()。

        Args:
            security: 股票代码过滤
            status: "open" / "closed" / "all"
            start_date / end_date / count: 日期过滤
        Returns:
            Order 列表
        """
        orders = list(self.order_dict.values())
        if security:
            orders = [o for o in orders if getattr(o, "_security", None) == security]
        if status == "open":
            orders = [o for o in orders if o.status == bt.Order.Partial]
        elif status == "closed":
            orders = [o for o in orders if o.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Rejected]]
        return orders

    def get_open_orders(self, security: str = None) -> List:
        """
        获取未成交订单，聚宽 get_open_orders()。

        Args:
            security: 股票代码过滤，None 表示全部
        Returns:
            未完成订单列表
        """
        open_orders = [o for o in self.order_dict.values() if o.status in [bt.Order.Submitted, bt.Order.Partial]]
        if security:
            open_orders = [o for o in open_orders if getattr(o, "_security", None) == security]
        return open_orders

    # ---- Backtrader 回调 ----

    def notify_order(self, order):
        # 追踪所有订单
        self.order_dict[order.ref] = order
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"买入: 价格={order.executed.price:.2f}, 数量={order.executed.size}")
            else:
                self.log(f"卖出: 价格={order.executed.price:.2f}, 数量={order.executed.size}")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"盈亏: 毛={trade.pnl:.2f}, 净={trade.pnlcomm:.2f}")

    def log(self, txt):
        print(f"[{self.datas[0].datetime.date(0)}] {txt}")


# ============================================================
# 辅助类
# ============================================================

class GlobalVars:
    """self.g 全局变量容器"""
    def __getattr__(self, name):
        return getattr(self, name, None)

    def __setattr__(self, name, value):
        super().__setattr__(name, value)


class ContextDict:
    """聚宽 context 兼容字典"""
    def __init__(self):
        object.__setattr__(self, "_data", {})
        object.__setattr__(self, "_current_dt", None)
        object.__setattr__(self, "_available_cash", 0)
        object.__setattr__(self, "_positions", {})

    def __getattr__(self, name):
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        return self._data.get(name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self._data[name] = value

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value


class ContextWrapper:
    """包装 JQStrategy，提供聚宽风格的 context 属性访问"""
    def __init__(self, strategy: JQStrategy):
        self._strategy = strategy

    @property
    def current_dt(self):
        return self._strategy._user_context._current_dt

    @property
    def portfolio(self):
        return self._strategy._user_context

    @property
    def available_cash(self):
        return self._strategy._user_context._available_cash

    @property
    def positions(self):
        return self._strategy._user_context._positions


class DataWrapper:
    """
    包装 Backtrader 的 data line，提供聚宽风格的 data[security] 访问。
    data.close / data.high / data.low / data.open / data.volume
    """
    def __init__(self, data):
        self._data = data

    @property
    def close(self):
        return self._data.close[0]

    @property
    def open(self):
        return self._data.open[0]

    @property
    def high(self):
        return self._data.high[0]

    @property
    def low(self):
        return self._data.low[0]

    @property
    def volume(self):
        return self._data.volume[0]

    @property
    def open_interest(self):
        return getattr(self._data, "openinterest", 0)

    def __getitem__(self, key):
        """data["close"] → numpy数组"""
        if key == "close":
            return self._data.close
        elif key == "open":
            return self._data.open
        elif key == "high":
            return self._data.high
        elif key == "low":
            return self._data.low
        elif key == "volume":
            return self._data.volume
        raise KeyError(key)


# ============================================================
# Backtest 运行器
# ============================================================

class Backtester:
    """
    轻量回测运行器。

    使用方式：
        from jq_lite import Backtester, JQStrategy

        bt = Backtester(
            strategy=MyStrategy,
            stock="000001.SZ",
            start_date="20200101",
            end_date="20231231",
            initial_cash=1000000,
        )
        bt.run()
    """

    def __init__(
        self,
        strategy: type,
        stock: str,
        start_date: str,
        end_date: str,
        initial_cash: float = 1000000,
        commission: float = 0.0003,
        benchmark: str = "000300.SH",
        adjust: str = "front",
    ):
        self.strategy = strategy
        self.stock = stock
        self.start_date = start_date
        self.end_date = end_date
        self.initial_cash = initial_cash
        self.commission = commission
        self.benchmark = benchmark
        self.adjust = adjust

    def run(self):
        cerebro = bt.Cerebro(stdstats=False)

        # 1. 加载数据
        df = load_stock_data(self.stock, self.start_date, self.end_date, self.adjust)
        if df is None or df.empty:
            print(f"[jq_lite] 数据加载失败: {self.stock}")
            return

        # 转换为 Backtrader DataFeed
        df.index = pd.to_datetime(df["date"])
        data = bt.feeds.PandasData(
            dataname=df,
            fromdate=pd.to_datetime(self.start_date),
            todate=pd.to_datetime(self.end_date),
        )
        cerebro.adddata(data)

        # 2. 设置资金和佣金
        cerebro.broker.setcash(self.initial_cash)
        cerebro.broker.setcommission(self.commission)

        # 3. 添加策略
        cerebro.addstrategy(self.strategy)

        # 4. 运行
        cerebro.run()

        # 5. 输出结果
        end_value = cerebro.broker.getvalue()
        profit = end_value - self.initial_cash
        print(f"\n{'='*50}")
        print(f"  回测区间: {self.start_date} ~ {self.end_date}")
        print(f"  股票代码: {self.stock}")
        print(f"  初始资金: {self.initial_cash:,.2f}")
        print(f"  最终资金: {end_value:,.2f}")
        print(f"  净收益:   {profit:,.2f}")
        print(f"  收益率:   {profit/self.initial_cash*100:.2f}%")
        print(f"{'='*50}")
        return end_value


# ============================================================
# 公开 API
# ============================================================
__all__ = [
    "JQStrategy",
    "Backtester",
    "get_price",
    "load_stock_data",
]
