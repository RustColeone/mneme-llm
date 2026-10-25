"""Turning text into search terms, the same way for notes and for queries.

Words of any alphabet (Latin with its accents, Cyrillic, Greek, Arabic, Hebrew, Devanagari…, combining marks
included) are case-folded, possessive 's is dropped, and English plurals get a light trim on ASCII words; runs of
Chinese, Japanese and Korean characters, and of the scripts written without spaces (Thai, Lao, Khmer, Burmese),
become overlapping two-character pieces plus their single characters ("考试没考好" → 考试 试没 没考 考好 考 试),
which match without a word list, including one-character words such as 猫 or 茶. With `use_jieba()` (and jieba
installed), its words are added on top. Function words and characters that would match everything are dropped.
"""

from __future__ import annotations

import re
import unicodedata

CJK = "㐀-䶿一-鿿豈-﫿぀-ヿ가-힯"
UNSPACED = CJK + "\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff"  # also Thai, Lao, Burmese, Khmer: no spaces between words
_UNSPACED = re.compile(rf"[{UNSPACED}]")
_CJK = re.compile(rf"[{CJK}]")
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
STOP_CJK_CHARS = frozenset("的了是我你他她它们这那在有就也都和与吗呢吧啊呀哦嗯哈嘿呜不没很太还又个一要会能说去来到上下"
                           "对好么着过把被给让从向但而且或之其此该每些")

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


def version() -> str:
    """Changes whenever `terms` would split text differently, so cached terms can be rebuilt."""
    return "4+jieba" if _jieba is not None else "4"


OPTIONAL_MARKS = re.compile("[\u0591-\u05c7\u064b-\u065f\u0670]")  # Hebrew points, Arabic vowel marks
JOINERS = "'-\u200c\u200d"  # inside a word: an apostrophe, a hyphen, and the (non-)joiners of Persian and Indic


def fold(text: str) -> str:
    """Case folded in any alphabet: "Straße" is "strasse", and Turkish "İstanbul" is "istanbul"."""
    return text.casefold().replace("i\u0307", "i")


def normalize(text: str) -> str:
    """NFKC, case-folded ("Straße" finds "STRASSE"), without the vowel marks Hebrew and Arabic usually leave out
    (so שָׁלוֹם finds שלום), with a typographic apostrophe read as a plain one ("don’t" is "don't")."""
    return fold(OPTIONAL_MARKS.sub("", unicodedata.normalize("NFKC", text)).replace("\u2019", "'"))


def _word(word: str) -> str | None:
    word = word.strip("'_-")
    if word.endswith("'s"):  # a possessive, in any language written with one
        word = word[:-2]
    if len(word) < 2 or word in STOP_LATIN:
        return None
    if word.isascii():  # the plural trim is English's; other languages' words are kept as they are
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
    return word


def _pieces(text: str):
    """Runs of an unspaced script, and words: letters, digits and combining marks of any alphabet (so Devanagari,
    Hebrew with its points or Arabic with its vowel marks stay whole), apostrophes allowed inside a word."""
    piece, unspaced = [], False
    for index, character in enumerate(text):
        is_unspaced = bool(_UNSPACED.match(character))
        is_word = is_unspaced or unicodedata.category(character)[0] in "LNM" or character == "_" or (
            character in JOINERS and piece and not unspaced and index + 1 < len(text)
            and unicodedata.category(text[index + 1])[0] in "LNM")
        if piece and (not is_word or is_unspaced != unspaced):
            yield "".join(piece), unspaced
            piece = []
        if is_word:
            if not piece:
                unspaced = is_unspaced
            piece.append(character)
    if piece:
        yield "".join(piece), unspaced


def terms(text: str) -> list[str]:
    """The distinct search terms of `text`, in order of first appearance."""
    found: dict[str, None] = {}
    for piece, unspaced in _pieces(normalize(text)):
        if unspaced:
            for i in range(len(piece) - 1):
                pair = piece[i:i + 2]
                if pair not in STOP_CJK:
                    found.setdefault(pair, None)
            for character in piece:
                if character not in STOP_CJK_CHARS and not unicodedata.category(character).startswith("M"):
                    found.setdefault(character, None)
            if _jieba is not None and _CJK.match(piece):
                for word in _jieba.cut(piece):
                    if len(word) >= 2 and word not in STOP_CJK:
                        found.setdefault(word, None)
        else:
            word = _word(piece)
            if word:
                found.setdefault(word, None)
    return list(found)


SCRIPTS = {"CJK": "cjk", "HIRAGANA": "cjk", "KATAKANA": "cjk", "HANGUL": "cjk", "LATIN": "latin",
           "CYRILLIC": "cyrillic", "GREEK": "greek", "ARABIC": "arabic", "HEBREW": "hebrew",
           "DEVANAGARI": "devanagari", "THAI": "thai"}


def script(text: str) -> str:
    """The writing that makes up most of `text`: "cjk" (Chinese, Japanese, Korean), "latin", "cyrillic", "greek",
    "arabic", "hebrew", "devanagari", "thai", or "other"; "" when it has no letters. A CJK character counts as two
    letters."""
    counts: dict[str, int] = {}
    for character in text:
        if not unicodedata.category(character).startswith("L"):
            continue
        name = unicodedata.name(character, "")
        kind = next((SCRIPTS[word] for word in name.split() if word in SCRIPTS), "other")  # FULLWIDTH LATIN …
        counts[kind] = counts.get(kind, 0) + (2 if kind == "cjk" else 1)
    return max(counts, key=counts.get) if counts else ""


CONTROL = re.compile("[\x00-\x08\x0e-\x1b\x7f-\x84\x86-\x9f]")  # control characters that are not whitespace
SURROGATE = re.compile("[\ud800-\udfff]")


def clean(text: str) -> str:
    """Text that can be stored and shown to a model: control characters (other than whitespace) dropped, and lone
    surrogates, which UTF-8 cannot hold, replaced by U+FFFD."""
    text = CONTROL.sub("", text)
    if SURROGATE.search(text):
        text = text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return text


def blank(text: str) -> bool:
    """Whether `text` shows nothing: only spaces, invisible format characters and marks with nothing to mark."""
    return not any(unicodedata.category(character)[0] in "LNPS" for character in text)


def required(value, what: str) -> str:
    """`value`, which must be a non-empty string (a subject, say); TypeError or ValueError otherwise."""
    if not isinstance(value, str):
        raise TypeError(f"{what} must be a string, not {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{what} must not be empty")
    return value


def clip(text: str, limit: int) -> str:
    """`text` cleaned and on one line, cut to `limit` characters, ending in "…" when something was cut."""
    text = " ".join(clean(text).split())
    return text if len(text) <= limit else text[:max(0, limit - 1)].rstrip() + "…"
