"""Deterministic lexical retrieval (BM25) and helpers. No network, no models."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from filings_lens.parse import Passage

STOPWORDS = frozenset(
    """a an and are as at be been but by can could did do does for from had has have how
    i if in into is it its may might more most new of on or our over per so such than that the
    their them then there these they this those to under up was we were what when where which
    while who why will with would you your company companys company's filing filings item
    risk risks factor factors added add describe described list tell me about any were
    year years discuss discussed say says said""".split()
)

_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower().replace("\u2019", "'")) if t not in STOPWORDS]


def stem(tok: str) -> str:
    """Crude, deterministic stemmer: strip a common suffix, then truncate to 6
    characters (compete / competition / competitive -> ``compet``)."""
    for suf in ("ations", "ation", "ings", "ing", "ies", "es", "s", "ed"):
        if len(tok) > len(suf) + 3 and tok.endswith(suf):
            tok = tok[: -len(suf)]
            break
    return tok[:6]


def terms(text: str) -> list[str]:
    return [stem(t) for t in tokenize(text)]


class BM25:
    def __init__(self, docs: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = [terms(d) for d in docs]
        self.k1, self.b = k1, b
        self.n = len(self.docs)
        self.avgdl = (sum(len(d) for d in self.docs) / self.n) if self.n else 0.0
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def score(self, query: str) -> list[float]:
        q = set(terms(query))
        out = []
        for tf, d in zip(self.tf, self.docs):
            s = 0.0
            for t in q:
                f = tf.get(t, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * len(d) / (self.avgdl or 1))
                s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / denom
            out.append(s)
        return out


def rank(query: str, passages: Sequence[Passage], top_k: int) -> list[tuple[Passage, float]]:
    if not passages:
        return []
    scores = BM25([p.text for p in passages]).score(query)
    order = sorted(range(len(passages)), key=lambda i: (-scores[i], passages[i].start))
    return [(passages[i], scores[i]) for i in order[:top_k] if scores[i] > 0]


_ABBREV = re.compile(
    r"(?:\b(?:Inc|Corp|Co|Ltd|No|Nos|Mr|Ms|Dr|St|vs|etc|e\.g|i\.e|U\.S|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)|\b[A-Z])\.$"
)


def sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) spans of sentences within ``text`` (relative offsets).

    Splits on ``.``/``!``/``?`` followed by whitespace and an uppercase letter,
    digit or opening quote, and on newlines; common abbreviations (Inc., U.S.)
    do not end a sentence. Spans shorter than 20 characters are dropped.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        end_here = False
        if ch == "\n":
            end_here = True
            cut = i
        elif ch in ".!?":
            j = i + 1
            while j < n and text[j] in ".!?\u201d\")'":
                j += 1
            boundary = j >= n or (
                text[j] == " "
                and j + 1 < n
                and (text[j + 1].isupper() or text[j + 1].isdigit() or text[j + 1] in '\u201c"(')
            )
            if boundary and not _ABBREV.search(text[max(start, i - 6) : i + 1]):
                end_here = True
                cut = j
                i = j - 1
        if end_here:
            _push(text, start, cut, spans)
            start = cut
        i += 1
    _push(text, start, n, spans)
    return spans


def _push(text: str, s: int, e: int, spans: list[tuple[int, int]]) -> None:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    if e - s >= 20:
        spans.append((s, e))
