# API连接故障排查指南

## 问题诊断

你遇到的错误信息：
```
❌ Opinion.Trade连接失败: 404
❌ Polymarket连接失败: 404
```

这表示API端点返回404 (Not Found)，可能的原因：

1. **API端点不正确** ⭐ 最可能
2. **API密钥未配置或无效**
3. **网络连接问题**
4. **API服务暂时不可用**

---

## 解决步骤

### 步骤1: 运行诊断工具

我已经创建了一个诊断脚本，运行它来找出问题：

```bash
cd cross_platform_arbitrage_bot
python test_api_connection.py
```

这个脚本会：
- 测试网络连接
- 尝试不同的API端点
- 显示详细的错误信息
- 给出具体的修复建议

### 步骤2: 检查配置文件

确认 `config.yaml` 中的配置正确：

```yaml
# Opinion.Trade 配置
opinion:
  host: "https://proxy.opinion.trade:8443"  # 确认这个URL是否正确
  api_key: "YOUR_API_KEY"                   # 替换为实际的API密钥
  private_key: "YOUR_PRIVATE_KEY"
  multisig_address: "YOUR_ADDRESS"

# Polymarket 配置
polymarket:
  host: "https://clob.polymarket.com"       # 确认这个URL是否正确
  api_key: ""                                # Polymarket可能不需要API key
  private_key: "YOUR_PRIVATE_KEY"
```

### 步骤3: 获取正确的API端点

#### Opinion.Trade

访问官方文档获取正确的API端点：
https://docs.opinion.trade/developer-guide/getting-started/quick-start

可能的端点：
- `https://api.opinion.trade`
- `https://proxy.opinion.trade:8443`
- `https://opinion.trade/api`

#### Polymarket

访问官方文档：
https://docs.polymarket.com

可能的端点：
- `https://clob.polymarket.com`
- `https://gamma-api.polymarket.com`

### 步骤4: 申请API密钥

如果还没有API密钥：

**Opinion.Trade**:
1. 访问: https://docs.opinion.trade/developer-guide/getting-started/quick-start
2. 填写API申请表单
3. 等待审核（通常1-3天）

**Polymarket**:
1. Polymarket的CLOB API可能不需要API密钥
2. 只需要钱包私钥即可

### 步骤5: 测试基本连接

手动测试API是否可用：

```bash
# 测试Opinion.Trade
curl https://proxy.opinion.trade:8443/api/v1/markets?limit=1

# 测试Polymarket
curl https://clob.polymarket.com/markets?limit=1
```

如果返回JSON数据，说明API可用。如果返回404，说明端点不对。

---

## 快速修复

如果你还没有API密钥或API不可用，可以先使用**模拟模式**测试代码：

### 创建模拟客户端

我可以为你创建一个模拟版本，使用假数据运行，这样你可以：
1. 测试代码逻辑
2. 熟悉系统运行流程
3. 等待API密钥申请通过后再切换到真实API

需要我创建模拟模式吗？

---

## 常见问题解答

**Q: 为什么会出现 "Unclosed client session" 警告？**

A: 这是因为初始化失败时，aiohttp会话没有正确关闭。我已经在修复代码中添加了 `await self._session.close()`，这个警告会消失。

**Q: 可以跳过Opinion.Trade，只用Polymarket吗？**

A: 可以，但需要修改代码。跨平台套利需要两个平台，单平台只能做做市策略。

**Q: API申请需要多久？**

A:
- Opinion.Trade: 通常1-3天
- Polymarket: CLOB API是公开的，可能不需要申请

**Q: 有没有测试环境？**

A: 需要查看官方文档。通常预测市场平台会提供测试网环境。

---

## 下一步

1. **立即运行诊断**:
   ```bash
   python test_api_connection.py
   ```

2. **查看诊断结果**，根据提示修复配置

3. **如果API密钥未就绪**，告诉我，我可以创建模拟模式让你先测试代码

4. **如果需要帮助**，把诊断脚本的输出发给我

---

**需要我现在创建模拟模式吗？这样你可以在等待API密钥期间先测试系统。**
