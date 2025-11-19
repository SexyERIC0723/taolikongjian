"""
Polymarket 客户端实现
"""
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
import aiohttp
from loguru import logger

from .base_client import BaseExchangeClient
from models.market import Market, Trade, Position, OrderSide, OrderType, Platform


class PolymarketClient(BaseExchangeClient):
    """Polymarket API客户端"""

    def __init__(self, config: Dict[str, Any]):
        """初始化Polymarket客户端"""
        super().__init__(config)

        self.host = config.get('host', 'https://clob.polymarket.com')
        self.api_key = config.get('api_key', '')
        self.private_key = config['private_key']
        self.chain_id = config.get('chain_id', 137)

        # 缓存
        self._markets_cache = {}
        self._cache_time = {}

    async def initialize(self) -> bool:
        """初始化连接"""
        try:
            # 创建异步HTTP会话
            headers = {'Content-Type': 'application/json'}
            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'

            self._session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            )

            # 测试连接 - 尝试获取市场数据
            try:
                url = f'{self.host}/markets'
                async with self._session.get(url, params={'limit': 1}) as resp:
                    if resp.status == 200:
                        logger.info("✅ Polymarket客户端初始化成功")
                        return True
                    else:
                        logger.error(f"❌ Polymarket API返回错误: {resp.status}")
                        text = await resp.text()
                        logger.debug(f"   响应内容: {text[:200]}")
                        await self._session.close()
                        return False
            except aiohttp.ClientConnectorError as e:
                logger.error(f"❌ 无法连接到Polymarket: {e}")
                await self._session.close()
                return False

        except Exception as e:
            logger.error(f"❌ Polymarket初始化错误: {e}")
            if self._session:
                await self._session.close()
            return False

    async def get_markets(self, limit: int = 100) -> List[Market]:
        """获取所有活跃市场"""
        try:
            url = f'{self.host}/markets'
            params = {
                'limit': limit,
                'active': 'true',
                'closed': 'false'
            }

            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"获取Polymarket市场失败: {resp.status}")
                    return []

                data = await resp.json()

                markets = []
                for item in data:
                    market = self._parse_market(item)
                    if market:
                        markets.append(market)
                        # 缓存
                        self._markets_cache[market.market_id] = market

                logger.info(f"📊 获取到 {len(markets)} 个Polymarket市场")
                return markets

        except Exception as e:
            logger.error(f"获取Polymarket市场错误: {e}")
            return []

    async def get_market(self, market_id: str) -> Optional[Market]:
        """获取单个市场"""
        try:
            # 检查缓存
            if market_id in self._markets_cache:
                cache_age = (datetime.utcnow() - self._cache_time.get(market_id, datetime.min)).total_seconds()
                if cache_age < 60:  # 1分钟缓存
                    return self._markets_cache[market_id]

            url = f'{self.host}/markets/{market_id}'

            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()
                market = self._parse_market(data)

                # 更新缓存
                if market:
                    self._markets_cache[market_id] = market
                    self._cache_time[market_id] = datetime.utcnow()

                return market

        except Exception as e:
            logger.error(f"获取Polymarket市场 {market_id} 错误: {e}")
            return None

    async def get_orderbook(self, market_id: str) -> Dict[str, Any]:
        """获取订单簿"""
        try:
            url = f'{self.host}/book'
            params = {'token_id': market_id}

            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    return {'bids': [], 'asks': []}

                data = await resp.json()
                return {
                    'bids': data.get('bids', []),
                    'asks': data.get('asks', [])
                }

        except Exception as e:
            logger.error(f"获取Polymarket订单簿错误: {e}")
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
            url = f'{self.host}/order'

            # Polymarket使用不同的订单格式
            payload = {
                'token_id': market_id,
                'side': 'BUY' if side == OrderSide.BUY else 'SELL',
                'type': 'GTC',  # Good Till Cancel
                'price': str(price),
                'size': str(amount)
            }

            async with self._session.post(url, json=payload) as resp:
                data = await resp.json()

                if resp.status != 200:
                    error_msg = data.get('error', 'Unknown error')
                    logger.error(f"Polymarket下单失败: {error_msg}")

                    return Trade(
                        trade_id=f"failed_{datetime.utcnow().timestamp()}",
                        platform=Platform.POLYMARKET,
                        market_id=market_id,
                        side=side,
                        order_type=order_type,
                        price=price,
                        amount=amount,
                        status='failed',
                        error_message=error_msg
                    )

                order_id = data.get('orderID')

                logger.info(f"✅ Polymarket订单已提交: {order_id}")

                return Trade(
                    trade_id=order_id,
                    platform=Platform.POLYMARKET,
                    market_id=market_id,
                    side=side,
                    order_type=order_type,
                    price=price,
                    amount=amount,
                    status='pending',
                    order_id=order_id
                )

        except Exception as e:
            logger.error(f"Polymarket下单错误: {e}")
            return Trade(
                trade_id=f"error_{datetime.utcnow().timestamp()}",
                platform=Platform.POLYMARKET,
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
            url = f'{self.host}/order/{order_id}'

            async with self._session.delete(url) as resp:
                if resp.status == 200:
                    logger.info(f"✅ Polymarket订单已取消: {order_id}")
                    return True
                return False

        except Exception as e:
            logger.error(f"取消Polymarket订单错误: {e}")
            return False

    async def get_balances(self) -> Dict[str, float]:
        """获取余额"""
        try:
            url = f'{self.host}/balance'

            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return {}

                data = await resp.json()
                return data

        except Exception as e:
            logger.error(f"获取Polymarket余额错误: {e}")
            return {}

    async def get_positions(self) -> List[Position]:
        """获取持仓"""
        try:
            url = f'{self.host}/positions'

            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return []

                data = await resp.json()
                positions = []

                for item in data:
                    position = Position(
                        platform=Platform.POLYMARKET,
                        market_id=item.get('token_id'),
                        yes_shares=float(item.get('size', 0)),
                        yes_value=float(item.get('value', 0))
                    )
                    positions.append(position)

                return positions

        except Exception as e:
            logger.error(f"获取Polymarket持仓错误: {e}")
            return []

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """查询订单状态"""
        try:
            url = f'{self.host}/order/{order_id}'

            async with self._session.get(url) as resp:
                if resp.status != 200:
                    return {}

                data = await resp.json()
                return data

        except Exception as e:
            logger.error(f"查询Polymarket订单状态错误: {e}")
            return {}

    def _parse_market(self, data: Dict[str, Any]) -> Optional[Market]:
        """解析Polymarket市场数据"""
        try:
            if not data:
                return None

            # Polymarket的市场结构
            market_id = data.get('token_id') or data.get('id')
            question = data.get('question', '')
            description = data.get('description', '')

            # 获取价格（Polymarket使用last_price或mid_price）
            yes_price = float(data.get('last_price', 0.5))

            # 如果有orderbook数据
            best_bid = data.get('best_bid')
            best_ask = data.get('best_ask')

            if best_bid:
                yes_bid = float(best_bid)
            else:
                yes_bid = None

            if best_ask:
                yes_ask = float(best_ask)
            else:
                yes_ask = None

            market = Market(
                platform=Platform.POLYMARKET,
                market_id=str(market_id),
                title=question,
                description=description,
                yes_price=yes_price,
                no_price=1.0 - yes_price,
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                volume=float(data.get('volume', 0)),
                status='active',
                raw_data=data
            )

            return market

        except Exception as e:
            logger.error(f"解析Polymarket市场数据错误: {e}")
            return None
