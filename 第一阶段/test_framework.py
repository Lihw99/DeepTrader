# coding=utf-8
"""
均线交叉策略回测 — Mock数据版（验证框架逻辑）
"""
from jq_lite import JQStrategy, Backtester
import numpy as np
import pandas as pd
import backtrader as bt


class MaCrossMockData(JQStrategy):
    """均线交叉策略 — Mock数据版"""

    pfast = 10
    pslow = 30

    def initialize(self, context):
        context.stock = "000001.SZ"
        context.i = 0
        print(f"[初始化] 快速均线: {self.pfast}, 慢速均线: {self.pslow}")
        # 打印第一根bar验证数据
        print(f"  当前日期: {self.datas[0].datetime.date(0)}")
        print(f"  当前收盘: {self.datas[0].close[0]:.2f}")

    def handle_data(self, context, data):
        """每个bar执行一次"""
        current_price = data.close

        # 计算均线（使用 history 方法）
        ma_fast = self._sma(self.pfast)
        ma_slow = self._sma(self.pslow)

        if ma_fast is None or ma_slow is None:
            context.i += 1
            return  # 数据不够，跳过

        # 计算当期均线值
        fast_ma_val = self._sma_value(self.pfast)
        slow_ma_val = self._sma_value(self.pslow)

        if fast_ma_val is None or slow_ma_val is None:
            context.i += 1
            return  # 数据不够，跳过

        # Debug: 每10个bar打印一次
        if context.i % 20 == 0:
            print(f"[{data._data.datetime.date(0)}] i={context.i} price={current_price:.2f} ma_fast={fast_ma_val:.2f} ma_slow={slow_ma_val:.2f} pos={self.position.size}")

        # ========== 交易逻辑 ==========
        if not self.position:
            # 金叉：快速均线 > 慢速均线 → 买入
            if fast_ma_val > slow_ma_val:
                target_value = self.broker.get_cash() * 0.8
                size = int(target_value / current_price)
                if size > 0:
                    self.buy(size=size)
                    self.log(f"买入: 价格={current_price:.2f}, 数量={size}, 均线={fast_ma_val:.2f}/{slow_ma_val:.2f}")
        else:
            # 死叉：快速均线 < 慢速均线 → 卖出
            if fast_ma_val < slow_ma_val:
                self.close()
                self.log(f"卖出: 价格={current_price:.2f}, 均线={fast_ma_val:.2f}/{slow_ma_val:.2f}")

        context.i += 1

    def _sma(self, period: int):
        """计算简单移动平均"""
        closes = self.history(period, unit="1d", field="close")
        if closes is None or len(closes) < period:
            return None
        return closes[-period:]  # 返回均线值序列

    def _sma_value(self, period: int) -> float:
        """计算当期均线值"""
        closes = self.history(period, unit="1d", field="close")
        if closes is None or len(closes) < period:
            return None
        return float(np.mean(closes[-period:]))

    def stop(self):
        final = self.broker.getvalue()
        self.log(f"最终资金: {final:,.2f}")


class MockBacktester(Backtester):
    """使用Mock数据运行回测"""

    def run(self):
        import numpy as np
        import backtrader as bt_module
        cerebro = bt_module.Cerebro(stdstats=False)

        # 生成 Mock 日线数据（2020年）
        dates = pd.date_range("2020-01-02", "2020-12-31", freq="B")
        np.random.seed(42)
        n = len(dates)

        # 生成随机游走价格
        prices = 10 + np.cumsum(np.random.randn(n) * 0.3)
        df = pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "open": prices * 0.99,
            "high": prices * 1.02,
            "low": prices * 0.98,
            "close": prices,
            "volume": np.random.randint(1e6, 1e7, n),
        })

        print(f"[Mock数据] {len(df)} 条K线，日期范围: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
        print(f"[Mock数据] 价格范围: {df['close'].min():.2f} ~ {df['close'].max():.2f}")

        df.index = pd.to_datetime(df["date"])
        data = bt_module.feeds.PandasData(
            dataname=df,
            fromdate=pd.to_datetime(self.start_date),
            todate=pd.to_datetime(self.end_date),
        )
        cerebro.adddata(data)
        cerebro.broker.setcash(self.initial_cash)
        cerebro.broker.setcommission(self.commission)
        cerebro.addstrategy(self.strategy, pfast=self.strategy.pfast, pslow=self.strategy.pslow)
        cerebro.run()

        end_value = cerebro.broker.getvalue()
        profit = end_value - self.initial_cash
        print(f"\n{'='*50}")
        print(f"  回测区间: {self.start_date} ~ {self.end_date}")
        print(f"  初始资金: {self.initial_cash:,.2f}")
        print(f"  最终资金: {end_value:,.2f}")
        print(f"  净收益:   {profit:,.2f}")
        print(f"  收益率:   {profit/self.initial_cash*100:.2f}%")
        print(f"{'='*50}")
        return end_value


if __name__ == "__main__":
    print("=" * 60)
    print("均线交叉策略 — Mock数据回测（验证框架）")
    print("=" * 60)

    bt = MockBacktester(
        strategy=MaCrossMockData,
        stock="000001.SZ",
        start_date="20200101",
        end_date="20201231",
        initial_cash=1_000_000,
        commission=0.0003,
    )
    bt.run()
