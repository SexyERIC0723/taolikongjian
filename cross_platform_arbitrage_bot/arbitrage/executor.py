"""
套利执行器 - 执行套利交易
"""
import asyncio
from typing import Dict, Optional, List
from datetime import datetime
from loguru import logger

from models.market import ArbitrageOpportunity, Trade, OrderSide, OrderType, Platform
from exchange_clients.base_client import BaseExchangeClient


class ArbitrageExecutor:
    """套利执行器"""

    def __init__(
        self,
        opinion_client: BaseExchangeClient,
        polymarket_client: BaseExchangeClient,
        config: Dict
    ):
        """
        初始化执行器

        Args:
            opinion_client: Opinion客户端
            polymarket_client: Polymarket客户端
            config: 配置字典
        """
        self.opinion_client = opinion_client
        self.polymarket_client = polymarket_client
        self.config = config

        self.auto_execute = config.get('auto_execute', True)
        self.max_retries = 3

        # 交易历史
        self.trade_history: List[Trade] = []

    async def execute_opportunity(
        self,
        opportunity: ArbitrageOpportunity
    ) -> bool:
        """
        执行套利机会

        Args:
            opportunity: 套利机会

        Returns:
            是否成功
        """
        if not self.auto_execute:
            logger.warning("⚠️  自动执行已禁用")
            return False

        if not opportunity.is_valid:
            logger.warning("⚠️  套利机会已失效")
            return False

        logger.info(f"🚀 开始执行套利: {opportunity}")

        try:
            # 步骤1: 同时在两个平台下单
            buy_trade, sell_trade = await self._place_simultaneous_orders(opportunity)

            if not buy_trade or not sell_trade:
                logger.error("❌ 下单失败")
                await self._cleanup_failed_execution(buy_trade, sell_trade)
                return False

            # 步骤2: 监控订单执行
            success = await self._monitor_execution(buy_trade, sell_trade)

            if success:
                # 记录执行结果
                opportunity.executed = True
                opportunity.execution_result = {
                    'buy_trade': buy_trade,
                    'sell_trade': sell_trade,
                    'executed_at': datetime.utcnow()
                }

                logger.info(f"✅ 套利执行成功! 净利润: ${opportunity.net_profit:.2f}")
                return True
            else:
                logger.error("❌ 套利执行失败")
                await self._handle_execution_failure(buy_trade, sell_trade)
                return False

        except Exception as e:
            logger.error(f"❌ 执行套利时发生错误: {e}")
            return False

    async def _place_simultaneous_orders(
        self,
        opportunity: ArbitrageOpportunity
    ) -> tuple[Optional[Trade], Optional[Trade]]:
        """
        同时在两个平台下单

        Args:
            opportunity: 套利机会

        Returns:
            (买单, 卖单)
        """
        # 准备订单参数
        buy_params = self._prepare_order_params(
            platform=opportunity.buy_platform,
            market_id=opportunity.buy_market.market_id,
            side=OrderSide.BUY,
            price=opportunity.buy_price,
            amount=opportunity.suggested_size
        )

        sell_params = self._prepare_order_params(
            platform=opportunity.sell_platform,
            market_id=opportunity.sell_market.market_id,
            side=OrderSide.SELL,
            price=opportunity.sell_price,
            amount=opportunity.suggested_size
        )

        # 并行下单（最小化延迟）
        logger.info("📝 同时下单...")

        buy_task = self._place_order_with_retry(
            opportunity.buy_platform,
            **buy_params
        )
        sell_task = self._place_order_with_retry(
            opportunity.sell_platform,
            **sell_params
        )

        # 等待两个订单都完成
        results = await asyncio.gather(buy_task, sell_task, return_exceptions=True)

        buy_trade = results[0] if not isinstance(results[0], Exception) else None
        sell_trade = results[1] if not isinstance(results[1], Exception) else None

        return buy_trade, sell_trade

    def _prepare_order_params(
        self,
        platform: Platform,
        market_id: str,
        side: OrderSide,
        price: float,
        amount: float
    ) -> Dict:
        """准备订单参数"""
        return {
            'market_id': market_id,
            'side': side,
            'order_type': OrderType.LIMIT,  # 使用限价单控制价格
            'price': price,
            'amount': amount
        }

    async def _place_order_with_retry(
        self,
        platform: Platform,
        **order_params
    ) -> Optional[Trade]:
        """
        下单（带重试）

        Args:
            platform: 平台
            **order_params: 订单参数

        Returns:
            交易对象
        """
        client = self._get_client(platform)

        for attempt in range(self.max_retries):
            try:
                trade = await client.place_order(**order_params)

                if trade.status != 'failed':
                    self.trade_history.append(trade)
                    return trade

                logger.warning(f"⚠️  下单失败 (尝试 {attempt + 1}/{self.max_retries}): {trade.error_message}")

                if attempt < self.max_retries - 1:
                    await asyncio.sleep(0.5)  # 等待0.5秒后重试

            except Exception as e:
                logger.error(f"❌ 下单错误 (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(0.5)

        return None

    async def _monitor_execution(
        self,
        buy_trade: Trade,
        sell_trade: Trade,
        timeout: int = 30
    ) -> bool:
        """
        监控订单执行

        Args:
            buy_trade: 买单
            sell_trade: 卖单
            timeout: 超时时间（秒）

        Returns:
            是否都成功执行
        """
        logger.info("👀 监控订单执行...")

        start_time = datetime.utcnow()
        check_interval = 1  # 每秒检查一次

        while (datetime.utcnow() - start_time).total_seconds() < timeout:
            # 检查买单状态
            if buy_trade.status == 'pending':
                buy_status = await self._check_order_status(
                    buy_trade.platform,
                    buy_trade.order_id
                )
                if buy_status:
                    buy_trade.status = buy_status.get('status', 'pending')
                    buy_trade.filled_amount = float(buy_status.get('filled_amount', 0))

            # 检查卖单状态
            if sell_trade.status == 'pending':
                sell_status = await self._check_order_status(
                    sell_trade.platform,
                    sell_trade.order_id
                )
                if sell_status:
                    sell_trade.status = sell_status.get('status', 'pending')
                    sell_trade.filled_amount = float(sell_status.get('filled_amount', 0))

            # 检查是否都成交
            if buy_trade.status == 'filled' and sell_trade.status == 'filled':
                logger.info("✅ 两个订单都已成交")
                return True

            # 检查是否有失败
            if buy_trade.status == 'failed' or sell_trade.status == 'failed':
                logger.error("❌ 有订单失败")
                return False

            await asyncio.sleep(check_interval)

        logger.warning("⏰ 订单执行超时")
        return False

    async def _check_order_status(
        self,
        platform: Platform,
        order_id: str
    ) -> Optional[Dict]:
        """查询订单状态"""
        try:
            client = self._get_client(platform)
            status = await client.get_order_status(order_id)
            return status
        except Exception as e:
            logger.error(f"查询订单状态错误: {e}")
            return None

    async def _cleanup_failed_execution(
        self,
        buy_trade: Optional[Trade],
        sell_trade: Optional[Trade]
    ):
        """清理失败的执行"""
        logger.info("🧹 清理失败的执行...")

        # 取消任何未完成的订单
        if buy_trade and buy_trade.status == 'pending':
            await self._cancel_order(buy_trade.platform, buy_trade.order_id)

        if sell_trade and sell_trade.status == 'pending':
            await self._cancel_order(sell_trade.platform, sell_trade.order_id)

    async def _handle_execution_failure(
        self,
        buy_trade: Trade,
        sell_trade: Trade
    ):
        """处理执行失败"""
        logger.warning("⚠️  处理执行失败...")

        # 如果只有一边成交，需要对冲风险
        if buy_trade.status == 'filled' and sell_trade.status != 'filled':
            logger.warning("⚠️  买单成交但卖单未成交，需要对冲")
            # TODO: 实现对冲逻辑
            # 可以选择：
            # 1. 在同一平台反向平仓
            # 2. 等待价格机会后平仓
            # 3. 持有到市场结算

        elif sell_trade.status == 'filled' and buy_trade.status != 'filled':
            logger.warning("⚠️  卖单成交但买单未成交，需要对冲")
            # TODO: 实现对冲逻辑

        # 取消未成交的订单
        await self._cleanup_failed_execution(buy_trade, sell_trade)

    async def _cancel_order(
        self,
        platform: Platform,
        order_id: str
    ) -> bool:
        """取消订单"""
        try:
            client = self._get_client(platform)
            result = await client.cancel_order(order_id)
            if result:
                logger.info(f"✅ 订单已取消: {order_id}")
            return result
        except Exception as e:
            logger.error(f"取消订单错误: {e}")
            return False

    def _get_client(self, platform: Platform) -> BaseExchangeClient:
        """获取交易所客户端"""
        if platform == Platform.OPINION:
            return self.opinion_client
        elif platform == Platform.POLYMARKET:
            return self.polymarket_client
        else:
            raise ValueError(f"未知平台: {platform}")

    def get_trade_stats(self) -> Dict:
        """获取交易统计"""
        total_trades = len(self.trade_history)
        successful_trades = len([t for t in self.trade_history if t.status == 'filled'])
        failed_trades = len([t for t in self.trade_history if t.status == 'failed'])

        return {
            'total_trades': total_trades,
            'successful_trades': successful_trades,
            'failed_trades': failed_trades,
            'success_rate': successful_trades / total_trades if total_trades > 0 else 0
        }
