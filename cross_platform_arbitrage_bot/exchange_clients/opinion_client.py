"""
Opinion.Trade 客户端实现
"""
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
import aiohttp
from loguru import logger

from .base_client import BaseExchangeClient
from models.market import Market, Trade, Position, OrderSide, OrderType, Platform


class OpinionClient(BaseExchangeClient):
    """Opinion.Trade API客户端"""

    def __init__(self, config: Dict[str, Any]):
        """初始化Opinion客户端"""
        super().__init__(config)

        self.host = config.get('host', 'https://proxy.opinion.trade:8443')
        self.api_key = config['api_key']
        self.private_key = config['private_key']
        self.chain_id = config.get('chain_id', 56)

        # 缓存
        self._markets_cache = {}
        self._cache_time = {}

    async def initialize(self) -> bool:
        """初始化连接"""
        try:
            # 创建异步HTTP会话
            self._session = aiohttp.ClientSession(
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json'
                },
                timeout=aiohttp.ClientTimeout(total=10)
            )

            # 测试连接 - 尝试获取市场数据
            try:
                url = f'{self.host}/api/v1/markets'
                async with self._session.get(url, params={'limit': 1}) as resp:
                    if resp.status == 200:
                        logger.info("✅ Opinion.Trade客户端初始化成功")
                        return True
                    else:
                        logger.error(f"❌ Opinion.Trade API返回错误: {resp.status}")
                        text = await resp.text()
                        logger.debug(f"   响应内容: {text[:200]}")
                        await self._session.close()
                        return False
            except aiohttp.ClientConnectorError as e:
                logger.error(f"❌ 无法连接到Opinion.Trade: {e}")
                await self._session.close()
                return False

        except Exception as e:
            logger.error(f"❌ Opinion.Trade初始化错误: {e}")
            if self._session:
                await self._session.close()
            return False

    async def get_markets(self, limit: int = 100) -> List[Market]:
        """获取所有活跃市场"""
        try:
            url = f'{self.host}/api/v1/markets'
            params = {
                'limit': limit,
                'status': 'active'
            }

            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"获取市场失败: {resp.status}")
                    return []

                data = await resp.json()

                markets = []
                for item in data.get('result', []):
                    market = self._parse_market(item)
                    if market:
                        markets.append(market)
                        # 缓存
                        self._markets_cache[market.market_id] = market

                logger.info(f"📊 获取到 {len(markets)} 个Opinion市场")
                return markets

        except Exception as e:
            logger.error(f"获取Opinion市场错误: {e}")
            return []

    async def get_market(self, market_id: str) -> Optional[Market]:
        """获取单个市场"""
        try:
            # 检查缓存
            if market_id in self._markets_cache:
                cache_age = (datetime.utcnow() - self._cache_time.get(market_id, datetime.min)).total_seconds()
                if cache_age < 60:  # 1分钟缓存
                    return self._markets_cache[market_id]

            url = f'{self.host}/api/v1/markets/{market_id}'

            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()
                market = self._parse_market(data.get('result'))

                # 更新缓存
                if market:
                    self._markets_cache[market_id] = market
                    self._cache_time[market_id] = datetime.utcnow()

                return market

        except Exception as e:
            logger.error(f"获取市场 {market_id} 错误: {e}")
            return None

    async def get_orderbook(self, market_id: str) -> Dict[str, Any]:
        """获取订单簿"""
        try:
            url = f'{self.host}/api/v1/orderbook/{market_id}'

            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return {'bids': [], 'asks': []}

                data = await resp.json()
                return data.get('result', {'bids': [], 'asks': []})

        except Exception as e:
            logger.error(f"获取订单簿错误: {e}")
            return {'bids': [], 'asks': []}

    async def place_order(
        self,
        market_id: str,
        side: OrderSide,
        order_type: OrderType,
        price: float,
        amount: float
    ) -> Trade:
        """下单"""
        try:
            url = f'{self.host}/api/v1/orders'

            payload = {
                'market_id': market_id,
                'side': side.value,
                'order_type': order_type.value,
                'price': str(price),
                'amount': str(amount)
            }

            async with self._session.post(url, json=payload) as resp:
                data = await resp.json()

                if resp.status != 200:
                    error_msg = data.get('errmsg', 'Unknown error')
                    logger.error(f"下单失败: {error_msg}")

                    return Trade(
                        trade_id=f"failed_{datetime.utcnow().timestamp()}",
                        platform=Platform.OPINION,
                        market_id=market_id,
                        side=side,
                        order_type=order_type,
                        price=price,
                        amount=amount,
                        status='failed',
                        error_message=error_msg
                    )

                result = data.get('result', {})
                order_id = result.get('order_id')

                logger.info(f"✅ Opinion订单已提交: {order_id}")

                return Trade(
                    trade_id=order_id,
                    platform=Platform.OPINION,
                    market_id=market_id,
                    side=side,
                    order_type=order_type,
                    price=price,
                    amount=amount,
                    status='pending',
                    order_id=order_id
                )

        except Exception as e:
            logger.error(f"Opinion下单错误: {e}")
            return Trade(
                trade_id=f"error_{datetime.utcnow().timestamp()}",
                platform=Platform.OPINION,
                market_id=market_id,
                side=side,
                order_type=order_type,
                price=price,
                amount=amount,
                status='failed',
                error_message=str(e)
            )

    async def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        try:
            url = f'{self.host}/api/v1/orders/{order_id}'

            async with self._session.delete(url) as resp:
                if resp.status == 200:
                    logger.info(f"✅ 订单已取消: {order_id}")
                    return True
                return False

        except Exception as e:
            logger.error(f"取消订单错误: {e}")
            return False

    async def get_balances(self) -> Dict[str, float]:
        """获取余额"""
        try:
            url = f'{self.host}/api/v1/balances'

            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return {}

                data = await resp.json()
                return data.get('result', {})

        except Exception as e:
            logger.error(f"获取余额错误: {e}")
            return {}

    async def get_positions(self) -> List[Position]:
        """获取持仓"""
        try:
            url = f'{self.host}/api/v1/positions'

            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return []

                data = await resp.json()
                positions = []

                for item in data.get('result', []):
                    position = Position(
                        platform=Platform.OPINION,
                        market_id=item.get('market_id'),
                        yes_shares=float(item.get('yes_shares', 0)),
                        no_shares=float(item.get('no_shares', 0)),
                        yes_value=float(item.get('yes_value', 0)),
                        no_value=float(item.get('no_value', 0))
                    )
                    positions.append(position)

                return positions

        except Exception as e:
            logger.error(f"获取持仓错误: {e}")
            return []

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """查询订单状态"""
        try:
            url = f'{self.host}/api/v1/orders/{order_id}'

            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return {}

                data = await resp.json()
                return data.get('result', {})

        except Exception as e:
            logger.error(f"查询订单状态错误: {e}")
            return {}

    def _parse_market(self, data: Dict[str, Any]) -> Optional[Market]:
        """解析市场数据"""
        try:
            if not data:
                return None

            market_id = str(data.get('id') or data.get('market_id'))
            title = data.get('title', '')
            description = data.get('description', '')

            # 获取价格
            yes_price = float(data.get('yes_price', 0.5))
            no_price = float(data.get('no_price', 0.5))

            # 获取订单簿信息（如果有）
            orderbook = data.get('orderbook', {})
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])

            yes_bid = float(bids[0]['price']) if bids else None
            yes_ask = float(asks[0]['price']) if asks else None

            yes_bid_size = float(bids[0]['amount']) if bids else 0.0
            yes_ask_size = float(asks[0]['amount']) if asks else 0.0

            market = Market(
                platform=Platform.OPINION,
                market_id=market_id,
                title=title,
                description=description,
                yes_price=yes_price,
                no_price=no_price,
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                yes_bid_size=yes_bid_size,
                yes_ask_size=yes_ask_size,
                volume=float(data.get('volume', 0)),
                status=data.get('status', 'active'),
                raw_data=data
            )

            return market

        except Exception as e:
            logger.error(f"解析市场数据错误: {e}")
            return None
