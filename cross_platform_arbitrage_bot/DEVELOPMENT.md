# 开发文档

## 完整开发指南 | Cross-Platform Arbitrage Bot

---

## 目录

1. [系统架构](#系统架构)
2. [核心模块详解](#核心模块详解)
3. [API参考](#api参考)
4. [开发流程](#开发流程)
5. [性能优化](#性能优化)
6. [部署指南](#部署指南)

---

## 系统架构

### 整体设计

```
┌──────────────────────────────────────────────────────────────┐
│                        主程序 (main.py)                        │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  CrossPlatformArbitrageBot                              │  │
│  │  - 初始化各组件                                           │  │
│  │  - 运行主循环                                            │  │
│  │  - 异常处理                                              │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌───────────────────┬──────────────────┬──────────────────┬─────────────────┐
│  Exchange Clients │   Arbitrage      │   Risk           │   Models        │
│                   │   Engine         │   Management     │                 │
│  ┌─────────────┐  │  ┌────────────┐  │  ┌────────────┐  │  ┌───────────┐  │
│  │  Opinion    │  │  │  Matcher   │  │  │   Risk     │  │  │  Market   │  │
│  │  Client     │  │  │            │  │  │  Manager   │  │  │  Trade    │  │
│  ├─────────────┤  │  ├────────────┤  │  └────────────┘  │  │  Position │  │
│  │ Polymarket  │  │  │  Detector  │  │                  │  │  Arbitrage│  │
│  │  Client     │  │  │            │  │                  │  └───────────┘  │
│  └─────────────┘  │  ├────────────┤  │                  │                 │
│                   │  │  Executor  │  │                  │                 │
│                   │  └────────────┘  │                  │                 │
└───────────────────┴──────────────────┴──────────────────┴─────────────────┘
```

### 数据流

```
1. 数据采集
   ├─ Opinion.get_markets() → List[Market]
   └─ Polymarket.get_markets() → List[Market]
                ↓
2. 市场匹配
   ├─ Matcher.find_matches() → List[(Market, Market)]
   └─ 文本相似度算法 (NLP)
                ↓
3. 套利检测
   ├─ Detector.detect_opportunities() → List[ArbitrageOpportunity]
   ├─ 计算价差
   ├─ 计算费用
   └─ 计算净利润
                ↓
4. 风险检查
   ├─ RiskManager.check_can_trade() → (bool, str)
   ├─ 检查每日亏损限制
   ├─ 检查持仓限制
   └─ 检查机会有效性
                ↓
5. 套利执行
   ├─ Executor.execute_opportunity() → bool
   ├─ 并发下单
   ├─ 监控执行
   └─ 记录结果
```

---

## 核心模块详解

### 1. Exchange Clients (交易所客户端)

#### BaseExchangeClient

**文件**: `exchange_clients/base_client.py`

**作用**: 定义所有交易所客户端的通用接口

**核心方法**:
```python
class BaseExchangeClient(ABC):
    @abstractmethod
    async def initialize() -> bool:
        """初始化连接和认证"""
        pass

    @abstractmethod
    async def get_markets(limit: int) -> List[Market]:
        """获取所有活跃市场"""
        pass

    @abstractmethod
    async def place_order(...) -> Trade:
        """下单"""
        pass

    @abstractmethod
    async def get_balances() -> Dict[str, float]:
        """获取账户余额"""
        pass
```

#### OpinionClient

**文件**: `exchange_clients/opinion_client.py`

**特点**:
- 连接到 `https://proxy.opinion.trade:8443`
- 支持EIP712签名
- Maker费用 = 0%
- 超低延迟 (200-500ms)

**关键实现**:
```python
class OpinionClient(BaseExchangeClient):
    async def place_order(self, market_id, side, order_type, price, amount):
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
                return Trade(status='failed', error_message=data.get('errmsg'))

            return Trade(
                order_id=data['result']['order_id'],
                status='pending',
                ...
            )
```

**缓存策略**:
```python
# 市场数据缓存60秒
if market_id in self._markets_cache:
    cache_age = (now - self._cache_time[market_id]).total_seconds()
    if cache_age < 60:
        return self._markets_cache[market_id]
```

#### PolymarketClient

**文件**: `exchange_clients/polymarket_client.py`

**特点**:
- 连接到 `https://clob.polymarket.com`
- 使用CLOB API
- Maker费用 = 0%
- 支持Polygon网络

**订单簿格式差异**:
```python
# Opinion格式
{
    'bids': [{'price': 0.5, 'amount': 100}, ...],
    'asks': [{'price': 0.52, 'amount': 100}, ...]
}

# Polymarket格式
{
    'bids': [{'price': '0.5', 'size': '100'}, ...],
    'asks': [{'price': '0.52', 'size': '100'}, ...]
}
```

### 2. Arbitrage Engine (套利引擎)

#### Matcher (市场匹配器)

**文件**: `arbitrage/matcher.py`

**核心算法**:
```python
def _calculate_similarity(text1: str, text2: str) -> float:
    """
    多算法加权相似度计算

    算法组合:
    - Token Sort Ratio: 不考虑词序
    - Token Set Ratio: 词集合比较
    - Partial Ratio: 部分匹配

    权重: 0.4 + 0.4 + 0.2 = 1.0
    """
    token_sort_ratio = fuzz.token_sort_ratio(text1, text2) / 100.0
    token_set_ratio = fuzz.token_set_ratio(text1, text2) / 100.0
    partial_ratio = fuzz.partial_ratio(text1, text2) / 100.0

    similarity = (
        token_sort_ratio * 0.4 +
        token_set_ratio * 0.4 +
        partial_ratio * 0.2
    )

    return similarity
```

**文本规范化**:
```python
def _normalize_text(text: str) -> str:
    # 1. 转小写
    text = text.lower()

    # 2. 移除标点
    text = text.translate(str.maketrans('', '', string.punctuation))

    # 3. 移除停用词
    stop_words = ['will', 'the', 'a', 'an', 'in', 'on', 'at']
    words = [w for w in text.split() if w not in stop_words]

    # 4. 重组
    return ' '.join(words)
```

**匹配示例**:
```
输入1: "Will Bitcoin reach $100,000 by December 2025?"
输出1: "bitcoin reach 100000 december 2025"

输入2: "BTC > $100K by Dec 2025"
输出2: "btc 100k dec 2025"

相似度: token_sort=0.85, token_set=0.92, partial=0.88
最终得分: 0.85*0.4 + 0.92*0.4 + 0.88*0.2 = 0.884 ✅
```

#### Detector (套利检测器)

**文件**: `arbitrage/detector.py`

**检测逻辑流程图**:
```
for each matched pair:
    ├─ 方向1: Opinion买入 → Polymarket卖出
    │   ├─ buy_price = opinion.yes_ask
    │   ├─ sell_price = poly.yes_bid
    │   ├─ gross_profit = sell_price - buy_price
    │   ├─ fees = buy_fee + sell_fee
    │   ├─ net_profit = gross_profit - fees
    │   ├─ profit_pct = net_profit / buy_price
    │   └─ if profit_pct >= min_margin: ✅ 套利机会
    │
    └─ 方向2: Polymarket买入 → Opinion卖出
        └─ (同上逻辑)
```

**费用计算**:
```python
def _calculate_fee(platform: Platform, price: float, is_maker: bool) -> float:
    if platform == Platform.OPINION:
        if is_maker:
            return 0.0  # Maker费用为0
        else:
            # Taker费用 = topic_rate × price × (1 - price)
            # 简化: 使用固定0.5%，最低$0.5
            return max(0.005, 0.5 / (price * 1000))

    elif platform == Platform.POLYMARKET:
        if is_maker:
            return 0.0
        else:
            return 0.02  # 2%固定费用
```

**最优交易量计算**:
```python
def _calculate_optimal_size(max_size, profit_pct, price) -> float:
    # 根据利润率调整仓位
    if profit_pct > 0.10:        # >10% 高利润
        return min(max_size, max_trade_size)

    elif profit_pct > 0.05:      # 5-10% 中等利润
        return min(max_size, max_trade_size * 0.7)

    else:                        # 3-5% 低利润
        return min(max_size, max_trade_size * 0.4)
```

**置信度评估**:
```python
def _assess_confidence(...) -> float:
    score = 0.5  # 基础分

    # 1. 价差大小
    if profit_pct > 0.10:
        score += 0.2
    elif profit_pct > 0.05:
        score += 0.1

    # 2. 订单簿深度
    if has_orderbook_data:
        score += 0.15

    # 3. 交易量
    if avg_volume > 100000:
        score += 0.1

    # 4. 价差稳定性
    if spread < 0.05:
        score += 0.05

    return min(1.0, score)
```

#### Executor (套利执行器)

**文件**: `arbitrage/executor.py`

**并发执行策略**:
```python
async def _place_simultaneous_orders(opportunity):
    # 准备两个订单
    buy_task = place_order_with_retry(
        platform=opportunity.buy_platform,
        market_id=opportunity.buy_market.market_id,
        side='BUY',
        price=opportunity.buy_price,
        amount=opportunity.suggested_size
    )

    sell_task = place_order_with_retry(
        platform=opportunity.sell_platform,
        market_id=opportunity.sell_market.market_id,
        side='SELL',
        price=opportunity.sell_price,
        amount=opportunity.suggested_size
    )

    # 并发执行（最小化时间差）
    buy_trade, sell_trade = await asyncio.gather(buy_task, sell_task)

    return buy_trade, sell_trade
```

**时间线**:
```
t=0ms     : 开始并发下单
t=50ms    : 两个HTTP请求同时发出
t=200ms   : Opinion确认
t=250ms   : Polymarket确认
t=300ms   : 两个订单都已提交 ✅

总延迟: ~300ms (vs 串行: ~500ms)
```

**订单监控**:
```python
async def _monitor_execution(buy_trade, sell_trade, timeout=30):
    start_time = datetime.utcnow()

    while (datetime.utcnow() - start_time).total_seconds() < timeout:
        # 检查买单
        if buy_trade.status == 'pending':
            status = await check_order_status(buy_trade.order_id)
            buy_trade.status = status.get('status')

        # 检查卖单
        if sell_trade.status == 'pending':
            status = await check_order_status(sell_trade.order_id)
            sell_trade.status = status.get('status')

        # 都成交了？
        if buy_trade.status == 'filled' and sell_trade.status == 'filled':
            return True

        # 有失败？
        if 'failed' in [buy_trade.status, sell_trade.status]:
            return False

        await asyncio.sleep(1)  # 每秒检查

    return False  # 超时
```

**失败处理**:
```python
async def _handle_execution_failure(buy_trade, sell_trade):
    # 情况1: 只有买单成交
    if buy_trade.status == 'filled' and sell_trade.status != 'filled':
        logger.warning("买单成交但卖单未成交，需要对冲")

        # 对冲策略:
        # 1. 在同一平台反向平仓
        # 2. 等待价格机会
        # 3. 持有到市场结算

        await cancel_order(sell_trade.order_id)

    # 情况2: 只有卖单成交
    elif sell_trade.status == 'filled' and buy_trade.status != 'filled':
        logger.warning("卖单成交但买单未成交，需要对冲")

        # 做空风险，需要尽快买入对冲
        await cancel_order(buy_trade.order_id)
```

### 3. Risk Management (风险管理)

**文件**: `risk/risk_manager.py`

**多层风险控制**:
```python
async def check_can_trade(opportunity) -> (bool, str):
    # 第1层: 紧急止损
    if self.emergency_stop:
        return False, "紧急止损已启用"

    # 第2层: 每日亏损限制
    if self.daily_pnl < -self.max_daily_loss:
        self.emergency_stop = True
        return False, "触发每日亏损限制"

    # 第3层: 每日交易次数
    if self.daily_trades_count >= self.max_daily_trades:
        return False, "交易次数超限"

    # 第4层: 单市场持仓
    if buy_market_position > self.max_position_per_market:
        return False, "单市场持仓超限"

    # 第5层: 总持仓
    if total_position > self.max_position_size:
        return False, "总持仓超限"

    # 第6层: 机会有效性
    if not opportunity.is_valid:
        return False, "套利机会已失效"

    # 第7层: 执行风险
    if opportunity.execution_risk == "high" and opportunity.confidence_score < 0.6:
        return False, "执行风险过高"

    return True, "通过风险检查"
```

**每日重置逻辑**:
```python
def _reset_daily_counters_if_needed():
    current_date = datetime.utcnow().date()

    if current_date != self.last_reset_date:
        logger.info("重置每日计数器")
        self.daily_pnl = 0.0
        self.daily_trades_count = 0
        self.last_reset_date = current_date
        # 注意: emergency_stop不自动重置
```

---

## API参考

### 配置文件 (config.yaml)

```yaml
# Opinion.Trade配置
opinion:
  host: str                    # API端点
  api_key: str                 # API密钥
  private_key: str             # 私钥
  chain_id: int                # 链ID (56)
  rpc_url: str                 # RPC节点
  multisig_address: str        # 多签地址

# Polymarket配置
polymarket:
  host: str                    # API端点
  api_key: str                 # API密钥（可选）
  private_key: str             # 私钥
  chain_id: int                # 链ID (137)
  rpc_url: str                 # RPC节点

# 策略配置
strategy:
  min_profit_margin: float     # 最小利润率 (0-1)
  max_trade_size: float        # 最大交易金额
  min_trade_size: float        # 最小交易金额
  max_position_size: float     # 最大总持仓
  price_update_interval: int   # 价格更新间隔(秒)
  market_scan_interval: int    # 市场扫描间隔(秒)
  auto_execute: bool           # 是否自动执行
  slippage_tolerance: float    # 滑点容忍度

# 费用配置
fees:
  opinion:
    maker: float               # Maker费用
    taker: float               # Taker费用
  polymarket:
    maker: float
    taker: float

# 风险管理
risk_management:
  max_daily_loss: float        # 每日最大亏损
  max_daily_trades: int        # 每日最大交易次数
  max_position_per_market: float  # 单市场最大持仓
  emergency_stop: bool         # 紧急止损标志

# 市场匹配
market_matching:
  similarity_threshold: float  # 相似度阈值 (0-1)
  fuzzy_matching: bool         # 启用模糊匹配
  manual_matches: dict         # 手动匹配映射

# 性能优化
performance:
  max_concurrent_requests: int    # 最大并发数
  connection_pool_size: int       # 连接池大小
  request_timeout: int            # 请求超时(秒)
  enable_cache: bool              # 启用缓存
  cache_ttl: int                  # 缓存TTL(秒)
```

### 数据模型

#### Market
```python
@dataclass
class Market:
    platform: Platform          # 平台
    market_id: str             # 市场ID
    title: str                 # 标题
    description: str           # 描述
    yes_price: float           # YES价格
    no_price: float            # NO价格
    yes_bid: float             # YES买价
    yes_ask: float             # YES卖价
    yes_bid_size: float        # 买单量
    yes_ask_size: float        # 卖单量
    status: str                # 状态
    volume: float              # 交易量
    timestamp: datetime        # 时间戳

    @property
    def mid_price(self) -> float:
        """中间价"""
        return (self.yes_bid + self.yes_ask) / 2

    @property
    def spread(self) -> float:
        """买卖价差"""
        return self.yes_ask - self.yes_bid
```

#### ArbitrageOpportunity
```python
@dataclass
class ArbitrageOpportunity:
    buy_platform: Platform      # 买入平台
    buy_market: Market          # 买入市场
    buy_price: float            # 买入价格

    sell_platform: Platform     # 卖出平台
    sell_market: Market         # 卖出市场
    sell_price: float           # 卖出价格

    gross_profit: float         # 毛利润
    net_profit: float           # 净利润
    profit_pct: float           # 利润率

    suggested_size: float       # 建议交易量
    max_size: float             # 最大交易量

    buy_fee: float              # 买入费用
    sell_fee: float             # 卖出费用
    total_fee: float            # 总费用

    confidence_score: float     # 置信度 (0-1)
    execution_risk: str         # 执行风险 (low/medium/high)

    @property
    def is_valid(self) -> bool:
        """检查是否有效"""
        if self.buy_price >= self.sell_price:
            return False
        if self.net_profit <= 0:
            return False
        age = (datetime.utcnow() - self.discovered_at).total_seconds()
        if age > 30:  # 30秒过期
            return False
        return True
```

---

## 开发流程

### 1. 本地开发

```bash
# 1. 克隆代码
git clone <repo_url>
cd cross_platform_arbitrage_bot

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装开发依赖
pip install pytest pytest-asyncio black flake8 mypy

# 5. 配置
cp config.yaml.example config.yaml
vim config.yaml  # 编辑配置

# 6. 运行测试
pytest tests/ -v

# 7. 运行机器人
python main.py
```

### 2. 代码规范

**使用Black格式化**:
```bash
black . --line-length 100
```

**使用Flake8检查**:
```bash
flake8 . --max-line-length 100
```

**使用Mypy类型检查**:
```bash
mypy . --ignore-missing-imports
```

### 3. 提交前检查清单

- [ ] 代码已格式化 (`black .`)
- [ ] 通过代码检查 (`flake8 .`)
- [ ] 通过类型检查 (`mypy .`)
- [ ] 所有测试通过 (`pytest`)
- [ ] 更新了文档
- [ ] 更新了CHANGELOG
- [ ] 提交信息清晰

---

## 性能优化

### 1. 异步优化

**使用asyncio.gather并发**:
```python
# ❌ 串行（慢）
markets1 = await client1.get_markets()
markets2 = await client2.get_markets()

# ✅ 并发（快）
markets1, markets2 = await asyncio.gather(
    client1.get_markets(),
    client2.get_markets()
)
```

**使用连接池**:
```python
# 创建持久连接
connector = aiohttp.TCPConnector(
    limit=20,           # 最大连接数
    limit_per_host=10,  # 每个host最大连接数
    ttl_dns_cache=300   # DNS缓存
)

session = aiohttp.ClientSession(connector=connector)
```

### 2. 缓存优化

**多层缓存**:
```python
# L1: 内存缓存（快）
self._markets_cache = {}

# L2: Redis缓存（可选）
# redis_client.setex(f"market:{id}", 60, json.dumps(market))

# 缓存失效
if cache_age > TTL:
    market = await fetch_from_api()
    self._markets_cache[id] = market
```

### 3. 网络优化

**使用专用RPC节点**:
```yaml
opinion:
  rpc_url: "https://bsc.nodereal.io/v1/YOUR_KEY"  # 更快
```

**减少请求延迟**:
```python
# 使用HTTP/2
connector = aiohttp.TCPConnector(force_close=False)

# 启用Keep-Alive
headers = {'Connection': 'keep-alive'}
```

---

## 部署指南

### 1. 使用Systemd

创建服务文件 `/etc/systemd/system/arbitrage-bot.service`:

```ini
[Unit]
Description=Cross-Platform Arbitrage Bot
After=network.target

[Service]
Type=simple
User=arbitrage
WorkingDirectory=/home/arbitrage/bot
ExecStart=/home/arbitrage/bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务:
```bash
sudo systemctl enable arbitrage-bot
sudo systemctl start arbitrage-bot
sudo systemctl status arbitrage-bot
```

### 2. 使用Docker

创建 `Dockerfile`:
```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

构建和运行:
```bash
docker build -t arbitrage-bot .
docker run -d --name bot -v $(pwd)/config.yaml:/app/config.yaml arbitrage-bot
```

### 3. 监控和告警

**使用Prometheus + Grafana**:
```python
from prometheus_client import Counter, Gauge, start_http_server

# 启动指标服务器
start_http_server(9090)

# 定义指标
arbitrage_opportunities = Counter('arbitrage_opportunities_total', 'Total arbitrage opportunities')
daily_pnl = Gauge('daily_pnl_usd', 'Daily P&L in USD')

# 记录指标
arbitrage_opportunities.inc()
daily_pnl.set(125.50)
```

---

**文档版本**: v1.0
**最后更新**: 2025-11-18
