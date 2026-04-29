# coding=utf-8
"""
均线交叉策略 — 真实数据版
使用本地Parquet数据 / Tushare数据回测
"""
from jq_lite import JQStrategy, Backtester, load_stock_data


class MaCrossStrategy(JQStrategy):
    """
    快速均线上穿慢速均线 → 买入（，金叉）
    快速均线下穿慢速均线 → 卖出（死叉）
    """

    pfast = 10   # 快速均线周期
    pslow = 30   # 慢速均线周期

    def initialize(self, context):
        """初始化 — 聚宽风格"""
        context.stock = "000001.SZ"
        context.i = 0

    def handle_data(self, context, data):
        """每个bar执行一次"""
        current_price = data.close

        # 计算当期均线值
        fast_ma_val = self._sma_value(self.pfast)
        slow_ma_val = self._sma_value(self.pslow)

        if fast_ma_val is None or slow_ma_val is None:
            context.i += 1
            return  # 数据不够，跳过

        # ========== 交易逻辑 ==========
        if not self.position:
            # 金叉：快速均线 > 慢速均线 → 买入
            if fast_ma_val > slow_ma_val:
                target_value = self.broker.get_cash() * 0.8
                size = int(target_value / current_price)
                if size > 0:
                    self.buy(size=size)
                    self.log(f"买入: 价格={current_price:.2f}, 数量={size}, ma_fast={fast_ma_val:.2f}, ma_slow={slow_ma_val:.2f}")
        else:
            # 死叉：快速均线 < 慢速均线 → 卖出
            if fast_ma_val < slow_ma_val:
                self.close()
                self.log(f"卖出: 价格={current_price:.2f}, ma_fast={fast_ma_val:.2f}, ma_slow={slow_ma_val:.2f}")

        context.i += 1

    def _sma_value(self, period: int):
        """计算当期简单移动平均"""
        closes = self.history(period + 1, unit="1d", fields="close")
        if closes is None or len(closes) < period:
            return None
        return float(closes[-period:].mean())

    def stop(self):
        final = self.broker.getvalue()
        self.log(f"最终资金: {final:,.2f}")


if __name__ == "__main__":
    print("=" * 60)
    print("均线交叉策略回测 — 真实数据")
    print("=" * 60)

    bt = Backtester(
        strategy=MaCrossStrategy,
        stock="000001.SZ",
        start_date="20200101",
        end_date="20231231",
        initial_cash=1_000_000,
        commission=0.0003,
    )
    bt.run()
