"""
交易所客户端基类
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from models.market import Market, Trade, Position, OrderSide, OrderType


class BaseExchangeClient(ABC):
    """交易所客户端抽象基类"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化客户端

        Args:
            config: 配置字典
        """
        self.config = config
        self._session = None

    @abstractmethod
    async def initialize(self) -> bool:
        """
        初始化连接和认证

        Returns:
            是否成功
        """
        pass

    @abstractmethod
    async def get_markets(self, limit: int = 100) -> List[Market]:
        """
        获取所有活跃市场

        Args:
            limit: 返回数量限制

        Returns:
            市场列表
        """
        pass

    @abstractmethod
    async def get_market(self, market_id: str) -> Optional[Market]:
        """
        获取单个市场详情

        Args:
            market_id: 市场ID

        Returns:
            市场对象
        """
        pass

    @abstractmethod
    async def get_orderbook(self, market_id: str) -> Dict[str, Any]:
        """
        获取订单簿

        Args:
            market_id: 市场ID

        Returns:
            订单簿数据
        """
        pass

    @abstractmethod
    async def place_order(
        self,
        market_id: str,
        side: OrderSide,
        order_type: OrderType,
        price: float,
        amount: float
    ) -> Trade:
        """
        下单

        Args:
            market_id: 市场ID
            side: 买/卖
            order_type: 订单类型
            price: 价格
            amount: 数量

        Returns:
            交易对象
        """
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """
        取消订单

        Args:
            order_id: 订单ID

        Returns:
            是否成功
        """
        pass

    @abstractmethod
    async def get_balances(self) -> Dict[str, float]:
        """
        获取账户余额

        Returns:
            余额字典
        """
        pass

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """
        获取持仓

        Returns:
            持仓列表
        """
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """
        查询订单状态

        Args:
            order_id: 订单ID

        Returns:
            订单状态
        """
        pass

    async def close(self):
        """关闭连接"""
        if self._session:
            await self._session.close()
