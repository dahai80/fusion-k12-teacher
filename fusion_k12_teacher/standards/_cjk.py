from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[一-鿿]")


def _cjk_tokens(text: str) -> list[str]:
    """CJK+拉丁混合分词 — CJK 段取 2-gram, 拉丁段按空白切 (STD-6/7)。

    E4: 单一实现, query.py 与 aligner.py 共用此份 (原先各抄一份已分叉)。
    STD-2: 单字 CJK chunk 产 0 bigram (range(0) 空), 回退保留原 chunk 不丢弃,
    避空 token 集恒假致对齐全漏。
    """
    text = text.lower().strip()
    tokens: list[str] = []
    for chunk in text.split():
        if _CJK_RE.search(chunk):
            tokens.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
            tokens.append(chunk)
        else:
            tokens.append(chunk)
    return [t for t in tokens if t]


def _word_match(needle: str, haystack: str) -> bool:
    """CJK 整词命中 — bigram token 交集替代裸子串, 避免"加法"命中"参加法学"。

    needle/haystack 均 bigram 分词; 至少 1 个 needle bigram 出现在 haystack token 集内才算命中。
    拉丁词走精确 token 相等。无 bigram(needle<2 字)时回退裸子串(已由 loose 守门)。
    E4: 单一实现, query.py 与 aligner.py 共用。
    """
    if not needle:
        return False
    if len(needle) < 2:
        return needle in haystack
    hay_set = set(_cjk_tokens(haystack))
    return any(tok in hay_set for tok in _cjk_tokens(needle))
