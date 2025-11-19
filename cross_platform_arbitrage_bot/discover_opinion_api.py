#!/usr/bin/env python3
"""
Opinion.Trade API探测工具

尝试找到正确的API端点
"""
import asyncio
import aiohttp
from loguru import logger


async def test_endpoint(session, base_url, path, api_key=""):
    """测试单个端点"""
    url = f"{base_url}{path}"

    headers = {}
    if api_key:
        # 尝试不同的认证方式
        auth_methods = [
            {'Authorization': f'Bearer {api_key}'},
            {'X-API-Key': api_key},
            {'api-key': api_key},
        ]
    else:
        auth_methods = [{}]

    for auth_header in auth_methods:
        try:
            async with session.get(
                url,
                headers=auth_header,
                params={'limit': 1},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.success(f"✅ 找到了! {url}")
                    logger.info(f"   认证方式: {auth_header}")
                    logger.info(f"   响应示例: {str(data)[:150]}")
                    return url
                elif resp.status == 401:
                    logger.warning(f"⚠️  {url} - 需要认证 (401)")
                elif resp.status != 404:
                    logger.info(f"   {url} - 状态码: {resp.status}")
        except Exception as e:
            pass

    return None


async def discover_opinion_api():
    """探测Opinion.Trade API"""
    logger.info("🔍 开始探测 Opinion.Trade API...")
    logger.info("=" * 60)

    # 可能的基础URL
    base_urls = [
        "https://proxy.opinion.trade:8443",
        "https://api.opinion.trade",
        "https://opinion.trade",
        "https://app.opinion.trade",
        "https://opinion.trade/api",
        "https://api.opinion.trade:8443",
    ]

    # 可能的路径
    paths = [
        "/markets",
        "/api/markets",
        "/api/v1/markets",
        "/api/v2/markets",
        "/v1/markets",
        "/v2/markets",
        "/clob/markets",
        "/trading/markets",
        "/public/markets",
        "/query/markets",
        "/graphql",  # 可能使用GraphQL
    ]

    # 从config读取API key
    try:
        import yaml
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
            api_key = config.get('opinion', {}).get('api_key', '')
    except:
        api_key = ''

    found_endpoints = []

    async with aiohttp.ClientSession() as session:
        logger.info(f"测试 {len(base_urls)} 个基础URL × {len(paths)} 个路径...")
        logger.info("")

        for base_url in base_urls:
            logger.info(f"📡 测试基础URL: {base_url}")

            # 先测试基础URL是否可达
            try:
                async with session.get(
                    base_url,
                    timeout=aiohttp.ClientTimeout(total=3)
                ) as resp:
                    logger.info(f"   服务器响应: {resp.status}")
            except Exception as e:
                logger.error(f"   ❌ 无法连接: {e}")
                continue

            # 测试所有路径
            for path in paths:
                result = await test_endpoint(session, base_url, path, api_key)
                if result:
                    found_endpoints.append(result)

            logger.info("")

    # 总结
    logger.info("=" * 60)
    logger.info("📋 探测结果")
    logger.info("=" * 60)

    if found_endpoints:
        logger.success(f"✅ 找到 {len(found_endpoints)} 个可用端点:")
        for endpoint in found_endpoints:
            logger.info(f"   • {endpoint}")

        logger.info("")
        logger.info("💡 请在 config.yaml 中更新:")
        logger.info("opinion:")
        logger.info(f"  host: \"{found_endpoints[0].rsplit('/', 1)[0]}\"")
    else:
        logger.error("❌ 未找到可用的API端点")
        logger.info("")
        logger.info("💡 可能的原因:")
        logger.info("1. Opinion.Trade API还未公开发布")
        logger.info("2. 需要先在网站上申请API访问权限")
        logger.info("3. API使用了不同的认证方式（如OAuth）")
        logger.info("4. API仅对特定用户开放")
        logger.info("")
        logger.info("🔗 建议:")
        logger.info("1. 访问 https://docs.opinion.trade 查看最新文档")
        logger.info("2. 联系 Opinion.Trade 支持团队")
        logger.info("3. 查看官方 Discord/Telegram 社区")


if __name__ == "__main__":
    asyncio.run(discover_opinion_api())
