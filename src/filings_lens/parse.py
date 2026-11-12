"""HTML -> normalized text, item sectioning, and passage splitting.

Character offsets in citations always refer to the *normalized text* produced by
:func:`html_to_text` (``PARSER_VERSION`` is recorded with every citation so that
offsets can be reproduced exactly).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser

PARSER_VERSION = "1"

_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "tr",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "section",
    "article",
    "ul",
    "ol",
    "hr",
    "title",
}
_SKIP_TAGS = {"script", "style", "head", "ix:header"}

# Canonical 10-K item titles (Form 10-K General Instructions).
TEN_K_ITEMS: dict[str, str] = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity",
    "6": "[Reserved]",
    "7": "Management's Discussion and Analysis",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "9C": "Disclosure Regarding Foreign Jurisdictions that Prevent Inspections",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership",
    "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibit and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}

TEN_Q_ITEMS: dict[str, str] = {
    "I.1": "Financial Statements",
    "I.2": "Management's Discussion and Analysis",
    "I.3": "Quantitative and Qualitative Disclosures About Market Risk",
    "I.4": "Controls and Procedures",
    "II.1": "Legal Proceedings",
    "II.1A": "Risk Factors",
    "II.2": "Unregistered Sales of Equity Securities and Use of Proceeds",
    "II.3": "Defaults Upon Senior Securities",
    "II.4": "Mine Safety Disclosures",
    "II.5": "Other Information",
    "II.6": "Exhibits",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._hidden_stack: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        style = (dict(attrs).get("style") or "").replace(" ", "").lower()
        hidden = "display:none" in style
        if tag in _SKIP_TAGS or hidden:
            self._skip_depth += 1
            self._hidden_stack.append(True)
        elif tag not in {"br", "hr", "img", "meta", "link", "input"}:
            self._hidden_stack.append(False)
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"br", "hr", "img", "meta", "link", "input"}:
            return
        if self._hidden_stack and self._hidden_stack.pop():
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)


# page numbers and running footers such as "Apple Inc. | 2025 Form 10-K | 15"
_PAGE_FURNITURE = re.compile(r"^(?:\d{1,3}|.{0,80}\|\s*(?:\d{4}\s+)?Form\s+10-[KQ]\s*\|\s*\d{1,3})$")


def html_to_text(html: str) -> str:
    """Convert filing HTML to normalized plain text: one block per line,
    internal whitespace collapsed, blank lines removed."""
    if "<" not in html:
        raw = html
    else:
        ext = _TextExtractor()
        ext.feed(html)
        ext.close()
        raw = "".join(ext.parts)
    lines = []
    for line in raw.replace("\r", "\n").split("\n"):
        line = re.sub(r"\s+", " ", line.replace("\xa0", " ")).strip()
        if line and not _PAGE_FURNITURE.match(line):
            lines.append(line)
    return "\n".join(lines)


@dataclass(frozen=True)
class Section:
    item: str
    title: str
    start: int
    end: int


@dataclass(frozen=True)
class Passage:
    passage_id: str
    item: str
    item_title: str
    index: int
    start: int
    end: int
    text: str


_ITEM_RE = re.compile(
    r"^(?:ITEM|Item)[ \t]+(\d\.\d{2}|\d{1,2}[A-C]?)[ \t]*[.:\-\u2014\u2013]?[ \t]*([^\n]{0,160})$",
    re.MULTILINE,
)
_TOC_SPAN = 200
_PART_RE = re.compile(r"^PART\s+(I{1,3}|IV)\b", re.MULTILINE | re.IGNORECASE)


def _part_at(text: str, pos: int, parts: list[tuple[int, str]]) -> str:
    current = "I"
    for p_pos, label in parts:
        if p_pos <= pos:
            current = label
        else:
            break
    return current


def split_items(text: str, form: str) -> list[Section]:
    """Split normalized filing text into item sections.

    Tables of contents (and cross-reference indexes) repeat every heading, so
    items are resolved in order, each taking its longest non-TOC-like heading
    after the previous item's heading.
    """
    form = form.upper()
    is_10q = form.startswith("10-Q")
    parts = [(m.start(), m.group(1).upper()) for m in _PART_RE.finditer(text)]
    matches = list(_ITEM_RE.finditer(text))
    if not matches:
        return [Section("FULL", "Full document", 0, len(text))]

    candidates: list[tuple[str, str, int, int]] = []
    for i, m in enumerate(matches):
        key = m.group(1).upper()
        if is_10q:
            key = f"{_part_at(text, m.start(), parts)}.{key}"
        nxt = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = m.group(2).strip().rstrip(".") or _default_title(key, form)
        candidates.append((key, title, m.start(), nxt))

    # Walk items in order of first appearance and pick, for each, the longest
    # non-TOC-like occurrence after the previously chosen heading (a TOC or
    # cross-reference entry spans only a title and a page number). Items with
    # tiny bodies ("Item 1B. None.") take their first occurrence after it.
    order: list[str] = []
    by_key: dict[str, list[tuple[str, str, int, int]]] = {}
    for cand in candidates:
        if cand[0] not in by_key:
            order.append(cand[0])
        by_key.setdefault(cand[0], []).append(cand)
    best: dict[str, tuple[str, str, int, int]] = {}
    prev = -1
    for key in order:
        after = [c for c in by_key[key] if c[2] > prev]
        if not after:
            continue
        real = [c for c in after if c[3] - c[2] >= _TOC_SPAN]
        pick = max(real, key=lambda c: c[3] - c[2]) if real else after[0]
        best[key] = pick
        prev = pick[2]
    chosen = sorted(best.values(), key=lambda c: c[2])
    sections = []
    for i, (key, title, start, _) in enumerate(chosen):
        end = chosen[i + 1][2] if i + 1 < len(chosen) else len(text)
        sections.append(Section(key, title, start, end))
    return sections


def _default_title(key: str, form: str) -> str:
    table = TEN_Q_ITEMS if form.startswith("10-Q") else TEN_K_ITEMS
    return table.get(key, "")


def make_passage_id(accession: str, item: str, index: int, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"{accession}:{item}:p{index:04d}:{digest}"


def split_passages(
    text: str,
    sections: list[Section],
    accession: str,
    max_chars: int = 1200,
) -> list[Passage]:
    """Split each section into paragraph-aligned passages (one paragraph each).

    A short single-line chunk (a heading) is merged with the following paragraph so that a
    risk-factor heading travels with its body. Passages never cross sections.
    """
    passages: list[Passage] = []
    for sec in sections:
        # line spans inside the section (skip the item heading line itself)
        spans: list[tuple[int, int]] = []
        pos = sec.start
        for line in text[sec.start : sec.end].split("\n"):
            s, e = pos, pos + len(line)
            pos = e + 1
            if line.strip() and not _PART_RE.match(line):
                spans.append((s, e))
        if spans and _ITEM_RE.match(text[spans[0][0] : spans[0][1]]):
            spans = spans[1:]
        idx = 0
        cur_start: int | None = None
        cur_end = 0
        for s, e in spans:
            if cur_start is None:
                cur_start, cur_end = s, e
                continue
            cur_len = cur_end - cur_start
            heading_like = cur_len < 250 and "\n" not in text[cur_start:cur_end]
            if heading_like:
                cur_end = e
                continue
            passages.append(_mk(text, sec, accession, idx, cur_start, cur_end))
            idx += 1
            cur_start, cur_end = s, e
        if cur_start is not None:
            passages.append(_mk(text, sec, accession, idx, cur_start, cur_end))
    return passages


def _mk(text: str, sec: Section, accession: str, idx: int, s: int, e: int) -> Passage:
    body = text[s:e]
    return Passage(
        passage_id=make_passage_id(accession, sec.item, idx, body),
        item=sec.item,
        item_title=sec.title,
        index=idx,
        start=s,
        end=e,
        text=body,
    )
