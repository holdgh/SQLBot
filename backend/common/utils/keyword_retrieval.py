# ========= 【改造标记 RAG-KEYWORD】↓ BM25 关键词检索工具 =========
# 改造点1：将问数流程中术语/SQL示例的 ILIKE 模糊包含查询，替换为 RAG 典型的
# BM25 分词打分检索。项目未引入 jieba，故采用「英文/数字按词切分 + 中文单字/二元组」
# 的轻量分词方案，配合标准 BM25（k1=1.5, b=0.75）对候选项打分取 Top-K。
# ========= 【改造标记 RAG-KEYWORD】↑ 改造说明结束 =========
import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from typing import TypeVar

from common.core.config import settings

T = TypeVar("T")

# 中文（CJK 统一表意文字 + 扩展A）连续片段
_CJK_PATTERN = re.compile(r"[一-鿿㐀-䶿]+")
# 英文/数字连续片段（小写化后匹配）
_ALNUM_PATTERN = re.compile(r"[a-z0-9]+")

# BM25 标准参数默认值（可被配置覆盖）
DEFAULT_K1: float = 1.5
DEFAULT_B: float = 0.75


def tokenize(text: str) -> list[str]:
    """轻量中文分词：英文/数字按词切分；中文产出单字（unigram）+ 相邻二元组（bigram）。

    无词典依赖，兼顾召回（unigram）与精度（bigram），对短词条（术语/示例问题）友好。
    """
    if not text:
        return []

    lowered = text.lower()
    tokens: list[str] = []
    tokens.extend(_ALNUM_PATTERN.findall(lowered))

    for match in _CJK_PATTERN.finditer(lowered):
        run = match.group()
        length = len(run)
        for i in range(length):
            tokens.append(run[i])
            if i + 1 < length:
                tokens.append(run[i:i + 2])

    return tokens


class BM25:
    """标准 BM25 打分器（Okapi BM25）。"""

    def __init__(self, corpus: list[list[str]], k1: float = DEFAULT_K1, b: float = DEFAULT_B) -> None:
        self.k1 = k1
        self.b = b
        self.doc_count = len(corpus)
        self.doc_freqs: list[Counter[str]] = [Counter(doc) for doc in corpus]
        self.doc_lens: list[int] = [len(doc) for doc in corpus]
        total_len = sum(self.doc_lens)
        self.avg_len: float = (total_len / self.doc_count) if self.doc_count else 0.0

        df: Counter[str] = Counter()
        for freqs in self.doc_freqs:
            df.update(freqs.keys())

        self.idf: dict[str, float] = {
            term: math.log((self.doc_count - freq + 0.5) / (freq + 0.5) + 1.0)
            for term, freq in df.items()
        }

    def scores(self, query_tokens: list[str]) -> list[float]:
        """计算 query 分词对每篇文档的 BM25 得分。"""
        result = [0.0] * self.doc_count
        if self.doc_count == 0 or not query_tokens:
            return result

        avg_len = self.avg_len if self.avg_len > 0 else 1.0

        for term in query_tokens:
            idf = self.idf.get(term)
            if idf is None:
                continue
            for idx, freqs in enumerate(self.doc_freqs):
                tf = freqs.get(term, 0)
                if tf == 0:
                    continue
                dl = self.doc_lens[idx]
                denom = tf + self.k1 * (1.0 - self.b + self.b * dl / avg_len)
                result[idx] += idf * (tf * (self.k1 + 1.0)) / denom

        return result


def bm25_search(
    query: str,
    documents: Sequence[T],
    text_getter: Callable[[T], str | None],
    top_k: int = 10,
    min_score: float = 0.0,
    k1: float = DEFAULT_K1,
    b: float = DEFAULT_B,
) -> list[tuple[T, float]]:
    """对候选项集合按 query 做 BM25 打分，返回 (doc, score) 降序 Top-K。

    min_score 为最低分阈值（严格大于）：默认 0.0 表示只保留至少有一个分词命中的结果。
    """
    if not documents or top_k <= 0:
        return []

    corpus = [tokenize(text_getter(doc) or "") for doc in documents]
    bm25 = BM25(corpus, k1=k1, b=b)
    scores = bm25.scores(tokenize(query))

    scored = [
        (doc, score)
        for doc, score in zip(documents, scores, strict=False)
        if score > min_score
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


def bm25_retrieve(
    query: str,
    documents: Sequence[T],
    text_getter: Callable[[T], str | None],
) -> list[T]:
    """按 settings 配置执行 BM25 检索，仅返回命中的文档列表（供 curd 层使用）。"""
    return [
        doc
        for doc, _score in bm25_search(
            query=query,
            documents=documents,
            text_getter=text_getter,
            top_k=settings.KEYWORD_RETRIEVAL_TOP_COUNT,
            min_score=settings.KEYWORD_RETRIEVAL_MIN_SCORE,
            k1=settings.KEYWORD_RETRIEVAL_BM25_K1,
            b=settings.KEYWORD_RETRIEVAL_BM25_B,
        )
    ]
