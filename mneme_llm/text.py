"""Turning text into search terms, the same way for notes and for queries.

Latin words are lowercased with a light plural trim; runs of Chinese, Japanese and Korean characters become
overlapping two-character pieces ("考试没考好" → 考试 试没 没考 考好), which match without a word list. If `jieba` is
installed and enabled, its words are added on top. Function words that would match everything are dropped.
"""

from __future__ import annotations

import re
import unicodedata

CJK = "㐀-䶿一-鿿豈-﫿぀-ヿ가-힯"
_PIECES = re.compile(rf"[a-z0-9][a-z0-9'_-]*|[{CJK}]+")
STOP_LATIN = frozenset("""
a an and are as at be been but by can could did do does for from had has have he her his how i if in into is it its
just me my no not of on or our she so than that the their them then there they this to too up us was we were what
when where which who why will with would you your yours i'm it's don't im ok okay yes yeah oh
""".split())
STOP_CJK = frozenset("""
我们 你们 他们 她们 什么 怎么 这个 那个 一个 不是 是不 就是 还是 可是 但是 因为 所以 如果 然后 已经 没有 可以 知道 觉得
现在 今天 一下 一点 有点 真的 这样 那样 这么 那么 自己 时候 了吧 的话 一样 好的 嗯嗯 哈哈 呜呜 嘿嘿 呵呵 嘻嘻 啊啊
哦哦 噢噢 吗吗 了了 的的
""".split())

_jieba = None


def use_jieba(enabled: bool = True) -> bool:
    """Add jieba's word segmentation to CJK text if the package is installed; returns whether it is now in use."""
    global _jieba
    if not enabled:
        _jieba = None
        return False
    try:
        import jieba  # type: ignore
    except ImportError:
        _jieba = None
        return False
    jieba.setLogLevel(60)
    _jieba = jieba
    return True


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def _latin(word: str) -> str | None:
    word = word.strip("'_-")
    if word.endswith("'s"):
        word = word[:-2]
    if len(word) < 2 or word in STOP_LATIN:
        return None
    if len(word) > 4 and word.endswith("ies"):
        word = word[:-3] + "y"
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word


def terms(text: str) -> list[str]:
    """The distinct search terms of `text`, in order of first appearance."""
    found: dict[str, None] = {}
    for piece in _PIECES.findall(normalize(text)):
        if re.match(rf"[{CJK}]", piece):
            if len(piece) == 1:
                continue
            for i in range(len(piece) - 1):
                pair = piece[i:i + 2]
                if pair not in STOP_CJK:
                    found.setdefault(pair, None)
            if _jieba is not None:
                for word in _jieba.cut(piece):
                    if len(word) >= 2 and word not in STOP_CJK:
                        found.setdefault(word, None)
        else:
            word = _latin(piece)
            if word:
                found.setdefault(word, None)
    return list(found)


def clip(text: str, limit: int) -> str:
    """`text` cut to `limit` characters, ending in "…" when something was cut."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:max(0, limit - 1)].rstrip() + "…"
