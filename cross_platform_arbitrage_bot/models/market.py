"""
市场数据模型
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class Platform(Enum):
    """交易平台枚举"""
    OPINION = "opinion"
    POLYMARKET = "polymarket"


class OrderSide(Enum):
    """订单方向"""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """订单类型"""
    MARKET = "MARKET_ORDER"
    LIMIT = "LIMIT_ORDER"


@dataclass
class Market:
    """预测市场数据结构"""
    platform: Platform
    market_id: str
    title: str
    description: str

    # 价格信息
    yes_price: float  # YES代币价格
    no_price: float   # NO代币价格

    # 订单簿信息
    yes_bid: Optional[float] = None  # YES最高买价
    yes_ask: Optional[float] = None  # YES最低卖价
    no_bid: Optional[float] = None   # NO最高买价
    no_ask: Optional[float] = None   # NO最低卖价

    # 流动性信息
    yes_bid_size: float = 0.0
    yes_ask_size: float = 0.0
    no_bid_size: float = 0.0
    no_ask_size: float = 0.0

    # 市场状态
    status: str = "active"
    volume: float = 0.0

    # 时间戳
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # 原始数据
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """初始化后处理"""
        # 确保价格在有效范围内
        self.yes_price = max(0.01, min(0.99, self.yes_price))
        self.no_price = max(0.01, min(0.99, self.no_price))

    @property
    def mid_price(self) -> float:
        """中间价"""
        if self.yes_bid and self.yes_ask:
            return (self.yes_bid + self.yes_ask) / 2
        return self.yes_price

    @property
    def spread(self) -> float:
        """买卖价差"""
        if self.yes_ask and self.yes_bid:
            return self.yes_ask - self.yes_bid
        return 0.0

    @property
    def spread_pct(self) -> float:
        """价差百分比"""
        if self.mid_price > 0:
            return self.spread / self.mid_price
        return 0.0


@dataclass
class ArbitrageOpportunity:
    """套利机会"""

    # 市场信息
    buy_platform: Platform
    buy_market: Market
    buy_price: float

    sell_platform: Platform
    sell_market: Market
    sell_price: float

    # 利润信息
    gross_profit: float  # 毛利润
    net_profit: float    # 净利润（扣除费用）
    profit_pct: float    # 利润率

    # 交易参数
    suggested_size: float  # 建议交易量
    max_size: float        # 最大交易量（基于流动性）

    # 费用信息
    buy_fee: float = 0.0
    sell_fee: float = 0.0
    total_fee: float = 0.0

    # 风险评估
    confidence_score: float = 0.0  # 置信度分数 (0-1)
    execution_risk: str = "low"     # low, medium, high

    # 时间戳
    discovered_at: datetime = field(default_factory=datetime.utcnow)

    # 是否已执行
    executed: bool = False
    execution_result: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        """字符串表示"""
        return (
            f"Arbitrage: Buy {self.buy_platform.value}@{self.buy_price:.4f}, "
            f"Sell {self.sell_platform.value}@{self.sell_price:.4f}, "
            f"Profit: {self.profit_pct*100:.2f}% (${self.net_profit:.2f})"
        )

    @property
    def is_valid(self) -> bool:
        """检查套利机会是否仍然有效"""
        # 检查价格是否合理
        if self.buy_price >= self.sell_price:
            return False

        # 检查净利润是否为正
        if self.net_profit <= 0:
            return False

        # 检查时间是否过期 (例如30秒)
        age = (datetime.utcnow() - self.discovered_at).total_seconds()
        if age > 30:
            return False

        return True


@dataclass
class Trade:
    """交易记录"""
    trade_id: str
    platform: Platform
    market_id: str

    side: OrderSide
    order_type: OrderType

    price: float
    amount: float

    status: str = "pending"  # pending, filled, cancelled, failed

    # 执行信息
    order_id: Optional[str] = None
    filled_amount: float = 0.0
    average_price: float = 0.0

    # 费用
    fee: float = 0.0

    # 时间戳
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    filled_at: Optional[datetime] = None

    # 关联的套利机会
    arbitrage_id: Optional[str] = None

    # 错误信息
    error_message: Optional[str] = None


@dataclass
class Position:
    """持仓信息"""
    platform: Platform
    market_id: str

    # 持仓数量
    yes_shares: float = 0.0
    no_shares: float = 0.0

    # 成本基础
    yes_cost_basis: float = 0.0
    no_cost_basis: float = 0.0

    # 当前价值
    yes_value: float = 0.0
    no_value: float = 0.0

    # 盈亏
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    # 时间戳
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_shares(self) -> float:
        """总持仓"""
        return self.yes_shares + self.no_shares

    @property
    def total_value(self) -> float:
        """总价值"""
        return self.yes_value + self.no_value

    @property
    def total_pnl(self) -> float:
        """总盈亏"""
        return self.unrealized_pnl + self.realized_pnl
