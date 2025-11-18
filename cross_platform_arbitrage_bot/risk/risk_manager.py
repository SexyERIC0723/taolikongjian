"""
风险管理系统
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from loguru import logger

from models.market import ArbitrageOpportunity, Trade, Position


class RiskManager:
    """风险管理器"""

    def __init__(self, config: Dict):
        """
        初始化风险管理器

        Args:
            config: 风险配置
        """
        self.config = config

        # 风险限制
        self.max_daily_loss = config.get('max_daily_loss', 500)
        self.max_daily_trades = config.get('max_daily_trades', 100)
        self.max_position_per_market = config.get('max_position_per_market', 2000)
        self.max_position_size = config.get('max_position_size', 10000)
        self.emergency_stop = config.get('emergency_stop', False)

        # 状态跟踪
        self.daily_pnl = 0.0
        self.daily_trades_count = 0
        self.last_reset_date = datetime.utcnow().date()

        # 持仓跟踪
        self.positions: Dict[str, Position] = {}

    async def check_can_trade(
        self,
        opportunity: ArbitrageOpportunity
    ) -> tuple[bool, str]:
        """
        检查是否允许交易

        Args:
            opportunity: 套利机会

        Returns:
            (是否允许, 原因)
        """
        # 重置每日计数器
        self._reset_daily_counters_if_needed()

        # 1. 检查紧急止损
        if self.emergency_stop:
            return False, "紧急止损已启用"

        # 2. 检查每日亏损限制
        if self.daily_pnl < -self.max_daily_loss:
            logger.error(f"🛑 触发每日亏损限制: ${self.daily_pnl:.2f}")
            self.emergency_stop = True
            return False, f"触发每日亏损限制 (${self.max_daily_loss})"

        # 3. 检查每日交易次数
        if self.daily_trades_count >= self.max_daily_trades:
            return False, f"触发每日交易次数限制 ({self.max_daily_trades})"

        # 4. 检查单个市场持仓限制
        buy_market_id = opportunity.buy_market.market_id
        sell_market_id = opportunity.sell_market.market_id

        buy_position = self.positions.get(buy_market_id)
        sell_position = self.positions.get(sell_market_id)

        if buy_position and buy_position.total_value > self.max_position_per_market:
            return False, f"买入市场持仓超限 (${buy_position.total_value:.2f})"

        if sell_position and sell_position.total_value > self.max_position_per_market:
            return False, f"卖出市场持仓超限 (${sell_position.total_value:.2f})"

        # 5. 检查总持仓限制
        total_position_value = sum(p.total_value for p in self.positions.values())

        if total_position_value + opportunity.suggested_size > self.max_position_size:
            return False, f"总持仓超限 (${total_position_value:.2f})"

        # 6. 检查机会有效性
        if not opportunity.is_valid:
            return False, "套利机会已失效"

        # 7. 检查执行风险
        if opportunity.execution_risk == "high":
            logger.warning(f"⚠️  高执行风险: {opportunity}")
            # 可以选择拒绝或降低仓位
            if opportunity.confidence_score < 0.6:
                return False, "执行风险过高且置信度低"

        return True, "通过风险检查"

    def record_trade(
        self,
        opportunity: ArbitrageOpportunity,
        buy_trade: Trade,
        sell_trade: Trade
    ):
        """
        记录交易

        Args:
            opportunity: 套利机会
            buy_trade: 买入交易
            sell_trade: 卖出交易
        """
        # 更新每日计数
        self.daily_trades_count += 1

        # 计算实际盈亏
        if buy_trade.status == 'filled' and sell_trade.status == 'filled':
            actual_pnl = (
                sell_trade.average_price * sell_trade.filled_amount -
                buy_trade.average_price * buy_trade.filled_amount -
                buy_trade.fee - sell_trade.fee
            )

            self.daily_pnl += actual_pnl

            logger.info(
                f"📊 交易记录: PnL=${actual_pnl:.2f}, "
                f"今日PnL=${self.daily_pnl:.2f}, "
                f"今日交易数={self.daily_trades_count}"
            )

        # 更新持仓
        self._update_positions(buy_trade, sell_trade)

    def _update_positions(self, buy_trade: Trade, sell_trade: Trade):
        """更新持仓"""
        # 更新买入市场持仓
        if buy_trade.status == 'filled':
            market_id = buy_trade.market_id
            if market_id not in self.positions:
                self.positions[market_id] = Position(
                    platform=buy_trade.platform,
                    market_id=market_id
                )

            pos = self.positions[market_id]
            pos.yes_shares += buy_trade.filled_amount
            pos.yes_cost_basis += buy_trade.average_price * buy_trade.filled_amount

        # 更新卖出市场持仓
        if sell_trade.status == 'filled':
            market_id = sell_trade.market_id
            if market_id not in self.positions:
                self.positions[market_id] = Position(
                    platform=sell_trade.platform,
                    market_id=market_id
                )

            pos = self.positions[market_id]
            pos.yes_shares -= sell_trade.filled_amount
            # 记录已实现盈亏
            if pos.yes_cost_basis > 0:
                avg_cost = pos.yes_cost_basis / pos.yes_shares if pos.yes_shares > 0 else 0
                realized = (sell_trade.average_price - avg_cost) * sell_trade.filled_amount
                pos.realized_pnl += realized

    def get_risk_metrics(self) -> Dict:
        """获取风险指标"""
        total_position_value = sum(p.total_value for p in self.positions.values())
        total_pnl = sum(p.total_pnl for p in self.positions.values())

        return {
            'daily_pnl': self.daily_pnl,
            'daily_trades': self.daily_trades_count,
            'total_position_value': total_position_value,
            'total_pnl': total_pnl,
            'max_daily_loss_remaining': self.max_daily_loss + self.daily_pnl,
            'max_daily_trades_remaining': self.max_daily_trades - self.daily_trades_count,
            'emergency_stop': self.emergency_stop
        }

    def _reset_daily_counters_if_needed(self):
        """如果需要，重置每日计数器"""
        current_date = datetime.utcnow().date()

        if current_date != self.last_reset_date:
            logger.info("🔄 重置每日风险计数器")
            self.daily_pnl = 0.0
            self.daily_trades_count = 0
            self.last_reset_date = current_date
            # 不重置emergency_stop，需要手动重置

    def reset_emergency_stop(self):
        """重置紧急止损"""
        logger.warning("⚠️  重置紧急止损标志")
        self.emergency_stop = False

    def enable_emergency_stop(self, reason: str = "手动触发"):
        """启用紧急止损"""
        logger.error(f"🚨 启用紧急止损: {reason}")
        self.emergency_stop = True
