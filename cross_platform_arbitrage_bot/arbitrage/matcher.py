"""
市场匹配器 - 在不同平台之间匹配相同的预测市场
"""
from typing import List, Dict, Tuple, Optional
from fuzzywuzzy import fuzz
from loguru import logger

from models.market import Market, Platform


class MarketMatcher:
    """市场匹配器"""

    def __init__(self, config: Dict):
        """
        初始化匹配器

        Args:
            config: 配置字典
        """
        self.config = config
        self.similarity_threshold = config.get('similarity_threshold', 0.85)
        self.fuzzy_matching = config.get('fuzzy_matching', True)
        self.manual_matches = config.get('manual_matches', {})

        # 匹配缓存
        self._match_cache: Dict[Tuple[str, str], bool] = {}

    def find_matches(
        self,
        opinion_markets: List[Market],
        polymarket_markets: List[Market]
    ) -> List[Tuple[Market, Market]]:
        """
        找到两个平台之间的匹配市场

        Args:
            opinion_markets: Opinion市场列表
            polymarket_markets: Polymarket市场列表

        Returns:
            匹配对列表 [(opinion_market, polymarket_market), ...]
        """
        matches = []

        logger.info(f"🔍 开始匹配市场: Opinion {len(opinion_markets)}, Polymarket {len(polymarket_markets)}")

        for opinion_market in opinion_markets:
            # 首先检查手动匹配
            manual_match = self._check_manual_match(opinion_market, polymarket_markets)
            if manual_match:
                matches.append((opinion_market, manual_match))
                logger.info(f"✅ 手动匹配: {opinion_market.title[:50]} <-> {manual_match.title[:50]}")
                continue

            # 自动匹配
            if self.fuzzy_matching:
                best_match = self._find_best_match(opinion_market, polymarket_markets)
                if best_match:
                    matches.append((opinion_market, best_match))

        logger.info(f"✅ 找到 {len(matches)} 对匹配市场")
        return matches

    def _check_manual_match(
        self,
        opinion_market: Market,
        polymarket_markets: List[Market]
    ) -> Optional[Market]:
        """检查手动匹配配置"""
        if opinion_market.market_id in self.manual_matches:
            poly_id = self.manual_matches[opinion_market.market_id]
            for poly_market in polymarket_markets:
                if poly_market.market_id == poly_id:
                    return poly_market
        return None

    def _find_best_match(
        self,
        opinion_market: Market,
        polymarket_markets: List[Market]
    ) -> Optional[Market]:
        """
        找到最佳匹配

        Args:
            opinion_market: Opinion市场
            polymarket_markets: Polymarket市场列表

        Returns:
            最佳匹配的Polymarket市场
        """
        best_score = 0.0
        best_match = None

        opinion_text = self._normalize_text(opinion_market.title)

        for poly_market in polymarket_markets:
            poly_text = self._normalize_text(poly_market.title)

            # 计算相似度
            similarity = self._calculate_similarity(opinion_text, poly_text)

            if similarity > best_score and similarity >= self.similarity_threshold:
                best_score = similarity
                best_match = poly_market

        if best_match:
            logger.debug(
                f"匹配: {opinion_market.title[:50]} <-> {best_match.title[:50]} "
                f"(相似度: {best_score:.2f})"
            )

        return best_match

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        计算文本相似度

        使用多种算法的加权平均:
        - Token Sort Ratio: 词序不敏感
        - Token Set Ratio: 词集合比较
        - Partial Ratio: 部分匹配

        Args:
            text1: 文本1
            text2: 文本2

        Returns:
            相似度分数 (0-1)
        """
        # 完全匹配
        if text1 == text2:
            return 1.0

        # 使用fuzzywuzzy计算多种相似度
        token_sort_ratio = fuzz.token_sort_ratio(text1, text2) / 100.0
        token_set_ratio = fuzz.token_set_ratio(text1, text2) / 100.0
        partial_ratio = fuzz.partial_ratio(text1, text2) / 100.0

        # 加权平均
        similarity = (
            token_sort_ratio * 0.4 +
            token_set_ratio * 0.4 +
            partial_ratio * 0.2
        )

        return similarity

    def _normalize_text(self, text: str) -> str:
        """
        规范化文本

        Args:
            text: 原始文本

        Returns:
            规范化后的文本
        """
        # 转小写
        text = text.lower()

        # 移除标点符号
        import string
        text = text.translate(str.maketrans('', '', string.punctuation))

        # 移除多余空格
        text = ' '.join(text.split())

        # 移除常见的无关词
        stop_words = ['will', 'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for']
        words = text.split()
        words = [w for w in words if w not in stop_words]
        text = ' '.join(words)

        return text

    def is_match(self, market1: Market, market2: Market) -> bool:
        """
        判断两个市场是否匹配

        Args:
            market1: 市场1
            market2: 市场2

        Returns:
            是否匹配
        """
        cache_key = (market1.market_id, market2.market_id)

        if cache_key in self._match_cache:
            return self._match_cache[cache_key]

        text1 = self._normalize_text(market1.title)
        text2 = self._normalize_text(market2.title)

        similarity = self._calculate_similarity(text1, text2)
        result = similarity >= self.similarity_threshold

        # 缓存结果
        self._match_cache[cache_key] = result

        return result

    def clear_cache(self):
        """清空匹配缓存"""
        self._match_cache.clear()
        logger.debug("匹配缓存已清空")
