"""
跨平台套利机器人 - 主程序

作者: Claude Code Quantitative Research Team
版本: v1.0
日期: 2025-11-18

描述:
    在Opinion.Trade和Polymarket之间自动检测并执行套利交易
"""
import asyncio
import yaml
from pathlib import Path
from datetime import datetime
from loguru import logger

# 配置日志
logger.add(
    "logs/arbitrage_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="INFO"
)

from exchange_clients.opinion_client import OpinionClient
from exchange_clients.polymarket_client import PolymarketClient
from arbitrage.matcher import MarketMatcher
from arbitrage.detector import ArbitrageDetector
from arbitrage.executor import ArbitrageExecutor
from risk.risk_manager import RiskManager


class CrossPlatformArbitrageBot:
    """跨平台套利机器人"""

    def __init__(self, config_path: str = "config.yaml"):
        """
        初始化套利机器人

        Args:
            config_path: 配置文件路径
        """
        # 加载配置
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        # 初始化客户端
        self.opinion_client = OpinionClient(self.config['opinion'])
        self.polymarket_client = PolymarketClient(self.config['polymarket'])

        # 初始化核心组件
        self.matcher = MarketMatcher(self.config.get('market_matching', {}))
        self.detector = ArbitrageDetector(self.config.get('strategy', {}))
        self.executor = ArbitrageExecutor(
            self.opinion_client,
            self.polymarket_client,
            self.config.get('strategy', {})
        )
        self.risk_manager = RiskManager(self.config.get('risk_management', {}))

        # 运行状态
        self.is_running = False
        self.cycle_count = 0

    async def initialize(self) -> bool:
        """初始化机器人"""
        logger.info("=" * 80)
        logger.info("🤖 跨平台套利机器人 v1.0")
        logger.info("=" * 80)

        # 初始化客户端
        logger.info("📡 初始化交易所连接...")

        opinion_ok = await self.opinion_client.initialize()
        poly_ok = await self.polymarket_client.initialize()

        if not opinion_ok or not poly_ok:
            logger.error("❌ 客户端初始化失败")
            return False

        # 检查余额
        logger.info("💰 检查账户余额...")
        opinion_balance = await self.opinion_client.get_balances()
        poly_balance = await self.polymarket_client.get_balances()

        logger.info(f"   Opinion余额: {opinion_balance}")
        logger.info(f"   Polymarket余额: {poly_balance}")

        logger.info("✅ 机器人初始化完成")
        logger.info("=" * 80)

        return True

    async def run(self):
        """运行套利机器人"""
        if not await self.initialize():
            return

        self.is_running = True
        scan_interval = self.config['strategy'].get('market_scan_interval', 5)

        logger.info(f"🚀 开始运行套利策略 (扫描间隔: {scan_interval}秒)")

        try:
            while self.is_running:
                self.cycle_count += 1
                cycle_start = datetime.utcnow()

                logger.info(f"\n{'='*80}")
                logger.info(f"🔄 第 {self.cycle_count} 轮扫描开始")
                logger.info(f"{'='*80}")

                # 执行一轮套利检测和执行
                await self.arbitrage_cycle()

                # 显示风险指标
                await self.display_risk_metrics()

                # 计算耗时
                elapsed = (datetime.utcnow() - cycle_start).total_seconds()
                logger.info(f"⏱️  本轮扫描耗时: {elapsed:.2f}秒")

                # 等待下一轮
                sleep_time = max(0, scan_interval - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        except KeyboardInterrupt:
            logger.info("\n⚠️  收到中断信号，正在停止...")
        except Exception as e:
            logger.error(f"❌ 运行错误: {e}", exc_info=True)
        finally:
            await self.shutdown()

    async def arbitrage_cycle(self):
        """执行一轮套利循环"""
        try:
            # 步骤1: 获取两个平台的市场数据
            logger.info("📊 获取市场数据...")

            opinion_markets, poly_markets = await asyncio.gather(
                self.opinion_client.get_markets(limit=100),
                self.polymarket_client.get_markets(limit=100)
            )

            if not opinion_markets or not poly_markets:
                logger.warning("⚠️  无法获取市场数据")
                return

            logger.info(f"   Opinion市场: {len(opinion_markets)}")
            logger.info(f"   Polymarket市场: {len(poly_markets)}")

            # 步骤2: 匹配市场
            logger.info("🔗 匹配市场...")
            matched_markets = self.matcher.find_matches(opinion_markets, poly_markets)

            if not matched_markets:
                logger.info("   未找到匹配市场")
                return

            # 步骤3: 检测套利机会
            logger.info("🔍 检测套利机会...")
            opportunities = self.detector.detect_opportunities(matched_markets)

            if not opportunities:
                logger.info("   未发现套利机会")
                return

            # 步骤4: 执行套利
            logger.info(f"💼 发现 {len(opportunities)} 个套利机会，开始执行...")

            for i, opp in enumerate(opportunities[:3], 1):  # 限制每轮最多3个
                logger.info(f"\n--- 机会 {i}/{len(opportunities[:3])} ---")
                logger.info(f"{opp}")

                # 风险检查
                can_trade, reason = await self.risk_manager.check_can_trade(opp)

                if not can_trade:
                    logger.warning(f"⚠️  跳过: {reason}")
                    continue

                # 再次验证机会（价格可能已变化）
                updated_buy_market = await self._get_updated_market(
                    opp.buy_platform,
                    opp.buy_market.market_id
                )
                updated_sell_market = await self._get_updated_market(
                    opp.sell_platform,
                    opp.sell_market.market_id
                )

                if not updated_buy_market or not updated_sell_market:
                    logger.warning("⚠️  无法更新市场数据")
                    continue

                # 验证套利机会
                is_valid = self.detector.validate_opportunity(
                    opp,
                    updated_buy_market,
                    updated_sell_market
                )

                if not is_valid:
                    logger.warning("⚠️  价格已变化，机会失效")
                    continue

                # 执行套利
                success = await self.executor.execute_opportunity(opp)

                if success:
                    # 记录交易
                    buy_trade = opp.execution_result['buy_trade']
                    sell_trade = opp.execution_result['sell_trade']
                    self.risk_manager.record_trade(opp, buy_trade, sell_trade)

                # 短暂等待，避免过快交易
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"❌ 套利循环错误: {e}", exc_info=True)

    async def _get_updated_market(self, platform, market_id):
        """获取更新的市场数据"""
        if platform.value == 'opinion':
            return await self.opinion_client.get_market(market_id)
        else:
            return await self.polymarket_client.get_market(market_id)

    async def display_risk_metrics(self):
        """显示风险指标"""
        metrics = self.risk_manager.get_risk_metrics()
        trade_stats = self.executor.get_trade_stats()

        logger.info(f"\n📈 风险指标:")
        logger.info(f"   今日盈亏: ${metrics['daily_pnl']:.2f}")
        logger.info(f"   今日交易: {metrics['daily_trades']}")
        logger.info(f"   总持仓: ${metrics['total_position_value']:.2f}")
        logger.info(f"   总盈亏: ${metrics['total_pnl']:.2f}")
        logger.info(f"   剩余亏损额度: ${metrics['max_daily_loss_remaining']:.2f}")
        logger.info(f"   剩余交易次数: {metrics['max_daily_trades_remaining']}")

        logger.info(f"\n📊 交易统计:")
        logger.info(f"   总交易: {trade_stats['total_trades']}")
        logger.info(f"   成功: {trade_stats['successful_trades']}")
        logger.info(f"   失败: {trade_stats['failed_trades']}")
        logger.info(f"   成功率: {trade_stats['success_rate']*100:.1f}%")

    async def shutdown(self):
        """关闭机器人"""
        logger.info("\n🛑 正在关闭机器人...")

        self.is_running = False

        # 关闭客户端连接
        await self.opinion_client.close()
        await self.polymarket_client.close()

        # 显示最终统计
        logger.info("\n📊 最终统计:")
        await self.display_risk_metrics()

        logger.info("✅ 机器人已安全关闭")


async def main():
    """主函数"""
    # 创建机器人实例
    bot = CrossPlatformArbitrageBot(config_path="config.yaml")

    # 运行机器人
    await bot.run()


if __name__ == "__main__":
    # 创建必要的目录
    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    # 运行主程序
    asyncio.run(main())
