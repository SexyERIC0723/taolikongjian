#!/usr/bin/env python3
"""
API连接诊断工具

用途: 测试Opinion.Trade和Polymarket的API连接
"""
import asyncio
import aiohttp
import yaml
from loguru import logger


async def test_opinion_api(config):
    """测试Opinion.Trade API"""
    logger.info("=" * 60)
    logger.info("🔍 测试 Opinion.Trade API")
    logger.info("=" * 60)

    host = config.get('host', 'https://proxy.opinion.trade:8443')
    api_key = config.get('api_key', '')

    logger.info(f"API端点: {host}")
    logger.info(f"API密钥: {api_key[:20]}..." if api_key else "API密钥: 未配置")

    # 测试1: 连接性测试
    logger.info("\n📡 测试1: 连接性测试")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(host, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                logger.info(f"✅ 能够连接到 {host}")
                logger.info(f"   状态码: {resp.status}")
    except aiohttp.ClientConnectorError as e:
        logger.error(f"❌ 无法连接到 {host}")
        logger.error(f"   错误: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ 连接错误: {e}")
        return False

    # 测试2: API端点测试
    logger.info("\n📊 测试2: 获取市场数据")
    endpoints_to_test = [
        '/api/v1/markets',
        '/markets',
        '/api/markets',
    ]

    for endpoint in endpoints_to_test:
        url = f"{host}{endpoint}"
        logger.info(f"\n尝试端点: {url}")

        try:
            headers = {}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params={'limit': 1},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    logger.info(f"   状态码: {resp.status}")

                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"   ✅ 成功! 找到正确的端点")
                        logger.info(f"   响应数据示例: {str(data)[:200]}")
                        return True
                    elif resp.status == 401:
                        logger.warning(f"   ⚠️  需要认证 - 请检查API密钥")
                    elif resp.status == 404:
                        logger.warning(f"   ⚠️  端点不存在")
                    else:
                        text = await resp.text()
                        logger.warning(f"   ⚠️  响应: {text[:200]}")

        except Exception as e:
            logger.error(f"   ❌ 错误: {e}")

    logger.error("\n❌ 未找到可用的API端点")
    return False


async def test_polymarket_api(config):
    """测试Polymarket API"""
    logger.info("\n" + "=" * 60)
    logger.info("🔍 测试 Polymarket API")
    logger.info("=" * 60)

    host = config.get('host', 'https://clob.polymarket.com')
    api_key = config.get('api_key', '')

    logger.info(f"API端点: {host}")
    logger.info(f"API密钥: {api_key[:20]}..." if api_key else "API密钥: 未配置")

    # 测试1: 连接性测试
    logger.info("\n📡 测试1: 连接性测试")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(host, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                logger.info(f"✅ 能够连接到 {host}")
                logger.info(f"   状态码: {resp.status}")
    except aiohttp.ClientConnectorError as e:
        logger.error(f"❌ 无法连接到 {host}")
        logger.error(f"   错误: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ 连接错误: {e}")
        return False

    # 测试2: API端点测试
    logger.info("\n📊 测试2: 获取市场数据")
    endpoints_to_test = [
        '/markets',
        '/api/markets',
        '/v1/markets',
    ]

    for endpoint in endpoints_to_test:
        url = f"{host}{endpoint}"
        logger.info(f"\n尝试端点: {url}")

        try:
            headers = {}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params={'limit': 1},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    logger.info(f"   状态码: {resp.status}")

                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"   ✅ 成功! 找到正确的端点")
                        logger.info(f"   响应数据示例: {str(data)[:200]}")
                        return True
                    elif resp.status == 401:
                        logger.warning(f"   ⚠️  需要认证 - 请检查API密钥")
                    elif resp.status == 404:
                        logger.warning(f"   ⚠️  端点不存在")
                    else:
                        text = await resp.text()
                        logger.warning(f"   ⚠️  响应: {text[:200]}")

        except Exception as e:
            logger.error(f"   ❌ 错误: {e}")

    logger.error("\n❌ 未找到可用的API端点")
    return False


async def main():
    """主函数"""
    logger.info("🔬 API连接诊断工具")
    logger.info("=" * 60)

    # 加载配置
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("❌ 找不到 config.yaml 文件")
        logger.info("💡 请确保在 cross_platform_arbitrage_bot 目录下运行此脚本")
        return
    except Exception as e:
        logger.error(f"❌ 加载配置文件错误: {e}")
        return

    # 测试Opinion.Trade
    opinion_ok = await test_opinion_api(config.get('opinion', {}))

    # 测试Polymarket
    poly_ok = await test_polymarket_api(config.get('polymarket', {}))

    # 总结
    logger.info("\n" + "=" * 60)
    logger.info("📋 诊断总结")
    logger.info("=" * 60)

    if opinion_ok:
        logger.info("✅ Opinion.Trade API: 正常")
    else:
        logger.error("❌ Opinion.Trade API: 失败")

    if poly_ok:
        logger.info("✅ Polymarket API: 正常")
    else:
        logger.error("❌ Polymarket API: 失败")

    if not opinion_ok or not poly_ok:
        logger.info("\n💡 故障排查建议:")
        logger.info("1. 检查网络连接")
        logger.info("2. 检查API密钥是否正确")
        logger.info("3. 检查API端点URL是否正确")
        logger.info("4. 查看Opinion.Trade文档: https://docs.opinion.trade")
        logger.info("5. 查看Polymarket文档: https://docs.polymarket.com")


if __name__ == "__main__":
    asyncio.run(main())
