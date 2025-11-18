"""
套利机会检测器
"""
import uuid
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from loguru import logger

from models.market import Market, ArbitrageOpportunity, Platform


class ArbitrageDetector:
    """套利机会检测器"""

    def __init__(self, config: Dict):
        """
        初始化检测器

        Args:
            config: 配置字典
        """
        self.config = config

        # 策略参数
        self.min_profit_margin = config.get('min_profit_margin', 0.03)
        self.max_trade_size = config.get('max_trade_size', 1000)
        self.min_trade_size = config.get('min_trade_size', 50)
        self.slippage_tolerance = config.get('slippage_tolerance', 0.01)

        # 费用配置
        self.fees = config.get('fees', {})
        self.opinion_maker_fee = self.fees.get('opinion', {}).get('maker', 0.0)
        self.opinion_taker_fee = self.fees.get('opinion', {}).get('taker', 0.005)
        self.poly_maker_fee = self.fees.get('polymarket', {}).get('maker', 0.0)
        self.poly_taker_fee = self.fees.get('polymarket', {}).get('taker', 0.02)

    def detect_opportunities(
        self,
        matched_markets: List[Tuple[Market, Market]]
    ) -> List[ArbitrageOpportunity]:
        """
        检测套利机会

        Args:
            matched_markets: 匹配的市场对列表

        Returns:
            套利机会列表
        """
        opportunities = []

        for opinion_market, poly_market in matched_markets:
            # 检测两个方向的套利机会

            # 方向1: Opinion买入 -> Polymarket卖出
            opp1 = self._check_arbitrage(
                buy_market=opinion_market,
                sell_market=poly_market
            )
            if opp1 and opp1.net_profit > 0:
                opportunities.append(opp1)

            # 方向2: Polymarket买入 -> Opinion卖出
            opp2 = self._check_arbitrage(
                buy_market=poly_market,
                sell_market=opinion_market
            )
            if opp2 and opp2.net_profit > 0:
                opportunities.append(opp2)

        # 按净利润排序
        opportunities.sort(key=lambda x: x.net_profit, reverse=True)

        if opportunities:
            logger.info(f"🎯 发现 {len(opportunities)} 个套利机会")
            for opp in opportunities[:3]:  # 显示前3个
                logger.info(f"   {opp}")

        return opportunities

    def _check_arbitrage(
        self,
        buy_market: Market,
        sell_market: Market
    ) -> Optional[ArbitrageOpportunity]:
        """
        检查单向套利机会

        Args:
            buy_market: 买入市场
            sell_market: 卖出市场

        Returns:
            套利机会（如果存在）
        """
        # 获取买入价格（使用ask价格，因为我们要买）
        if buy_market.yes_ask:
            buy_price = buy_market.yes_ask
            buy_size = buy_market.yes_ask_size
        else:
            buy_price = buy_market.yes_price
            buy_size = self.max_trade_size  # 默认最大值

        # 获取卖出价格（使用bid价格，因为我们要卖）
        if sell_market.yes_bid:
            sell_price = sell_market.yes_bid
            sell_size = sell_market.yes_bid_size
        else:
            sell_price = sell_market.yes_price
            sell_size = self.max_trade_size

        # 检查价格差
        if buy_price >= sell_price:
            return None  # 没有套利空间

        # 计算费用
        buy_fee = self._calculate_fee(buy_market.platform, buy_price, is_maker=False)
        sell_fee = self._calculate_fee(sell_market.platform, sell_price, is_maker=False)
        total_fee = buy_fee + sell_fee

        # 计算毛利润和净利润
        gross_profit = sell_price - buy_price
        net_profit = gross_profit - total_fee

        # 检查是否满足最小利润要求
        if net_profit <= 0:
            return None

        profit_pct = net_profit / buy_price

        if profit_pct < self.min_profit_margin:
            return None  # 利润率不足

        # 计算建议交易量
        max_size = min(buy_size, sell_size, self.max_trade_size)
        suggested_size = self._calculate_optimal_size(
            max_size,
            profit_pct,
            buy_price
        )

        if suggested_size < self.min_trade_size:
            return None  # 交易量太小

        # 计算实际利润（基于建议交易量）
        actual_net_profit = net_profit * suggested_size / buy_price

        # 风险评估
        confidence_score = self._assess_confidence(
            buy_market,
            sell_market,
            profit_pct
        )

        execution_risk = self._assess_execution_risk(
            buy_market,
            sell_market,
            suggested_size
        )

        # 创建套利机会对象
        opportunity = ArbitrageOpportunity(
            buy_platform=buy_market.platform,
            buy_market=buy_market,
            buy_price=buy_price,
            sell_platform=sell_market.platform,
            sell_market=sell_market,
            sell_price=sell_price,
            gross_profit=gross_profit,
            net_profit=actual_net_profit,
            profit_pct=profit_pct,
            suggested_size=suggested_size,
            max_size=max_size,
            buy_fee=buy_fee * suggested_size / buy_price,
            sell_fee=sell_fee * suggested_size / sell_price,
            total_fee=total_fee * suggested_size / buy_price,
            confidence_score=confidence_score,
            execution_risk=execution_risk
        )

        return opportunity

    def _calculate_fee(
        self,
        platform: Platform,
        price: float,
        is_maker: bool = False
    ) -> float:
        """
        计算交易费用

        Args:
            platform: 交易平台
            price: 价格
            is_maker: 是否maker订单

        Returns:
            费用（作为价格的一部分）
        """
        if platform == Platform.OPINION:
            if is_maker:
                return self.opinion_maker_fee  # 0%
            else:
                # Opinion的Taker费用是动态的
                # fee = topic_rate × price × (1 - price)
                # 我们使用简化版本
                return max(self.opinion_taker_fee, 0.005 / price)  # 最低$0.5

        elif platform == Platform.POLYMARKET:
            if is_maker:
                return self.poly_maker_fee  # 0%
            else:
                return self.poly_taker_fee  # 2%

        return 0.0

    def _calculate_optimal_size(
        self,
        max_size: float,
        profit_pct: float,
        price: float
    ) -> float:
        """
        计算最优交易量

        考虑因素：
        1. 流动性限制
        2. 利润率
        3. 风险控制

        Args:
            max_size: 最大可用流动性
            profit_pct: 利润率
            price: 价格

        Returns:
            建议交易量
        """
        # 基础策略：根据利润率调整交易量
        if profit_pct > 0.10:  # >10%利润
            # 高利润，使用较大仓位
            size = min(max_size, self.max_trade_size)
        elif profit_pct > 0.05:  # 5-10%利润
            # 中等利润，使用中等仓位
            size = min(max_size, self.max_trade_size * 0.7)
        else:  # 3-5%利润
            # 低利润，使用小仓位
            size = min(max_size, self.max_trade_size * 0.4)

        # 确保在最小和最大之间
        size = max(self.min_trade_size, size)
        size = min(self.max_trade_size, size)

        return size

    def _assess_confidence(
        self,
        buy_market: Market,
        sell_market: Market,
        profit_pct: float
    ) -> float:
        """
        评估套利机会的置信度

        Args:
            buy_market: 买入市场
            sell_market: 卖出市场
            profit_pct: 利润率

        Returns:
            置信度分数 (0-1)
        """
        score = 0.5  # 基础分数

        # 因素1: 价差大小（越大越好）
        if profit_pct > 0.10:
            score += 0.2
        elif profit_pct > 0.05:
            score += 0.1

        # 因素2: 订单簿深度（有订单簿数据更好）
        if buy_market.yes_ask and sell_market.yes_bid:
            score += 0.15

        # 因素3: 交易量（高交易量市场更可靠）
        avg_volume = (buy_market.volume + sell_market.volume) / 2
        if avg_volume > 100000:  # >$100K
            score += 0.1
        elif avg_volume > 10000:  # >$10K
            score += 0.05

        # 因素4: 价差稳定性（价差不应该太极端）
        spread = buy_market.spread_pct
        if spread < 0.05:  # <5%价差
            score += 0.05

        return min(1.0, score)

    def _assess_execution_risk(
        self,
        buy_market: Market,
        sell_market: Market,
        trade_size: float
    ) -> str:
        """
        评估执行风险

        Args:
            buy_market: 买入市场
            sell_market: 卖出市场
            trade_size: 交易量

        Returns:
            风险等级: low, medium, high
        """
        risk_score = 0

        # 因素1: 流动性
        if buy_market.yes_ask_size < trade_size:
            risk_score += 2
        if sell_market.yes_bid_size < trade_size:
            risk_score += 2

        # 因素2: 价差
        avg_spread = (buy_market.spread_pct + sell_market.spread_pct) / 2
        if avg_spread > 0.05:  # >5%
            risk_score += 1

        # 因素3: 交易量
        avg_volume = (buy_market.volume + sell_market.volume) / 2
        if avg_volume < 1000:  # <$1K
            risk_score += 2

        # 风险等级
        if risk_score >= 4:
            return "high"
        elif risk_score >= 2:
            return "medium"
        else:
            return "low"

    def validate_opportunity(
        self,
        opportunity: ArbitrageOpportunity,
        current_buy_market: Market,
        current_sell_market: Market
    ) -> bool:
        """
        验证套利机会是否仍然有效

        Args:
            opportunity: 原套利机会
            current_buy_market: 当前买入市场数据
            current_sell_market: 当前卖出市场数据

        Returns:
            是否仍然有效
        """
        # 重新计算套利机会
        new_opp = self._check_arbitrage(
            buy_market=current_buy_market,
            sell_market=current_sell_market
        )

        if not new_opp:
            logger.warning("⚠️  套利机会已消失")
            return False

        # 检查利润是否显著下降
        profit_change = (new_opp.net_profit - opportunity.net_profit) / opportunity.net_profit

        if profit_change < -0.2:  # 利润下降超过20%
            logger.warning(f"⚠️  利润大幅下降: {profit_change*100:.1f}%")
            return False

        # 检查价格是否在滑点容忍范围内
        buy_price_change = abs(new_opp.buy_price - opportunity.buy_price) / opportunity.buy_price
        sell_price_change = abs(new_opp.sell_price - opportunity.sell_price) / opportunity.sell_price

        if buy_price_change > self.slippage_tolerance or sell_price_change > self.slippage_tolerance:
            logger.warning(f"⚠️  价格变化超过滑点容忍度")
            return False

        return True
