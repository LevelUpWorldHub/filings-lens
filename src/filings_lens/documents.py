"""Fetch + parse a filing into passages."""

from __future__ import annotations

from dataclasses import dataclass

from filings_lens.edgar import EdgarClient
from filings_lens.models import Citation, Filing
from filings_lens.parse import (
    PARSER_VERSION,
    Passage,
    Section,
    html_to_text,
    split_items,
    split_passages,
)


@dataclass
class ParsedFiling:
    filing: Filing
    text: str
    sections: list[Section]
    passages: list[Passage]

    def passages_for(self, items: list[str] | None) -> list[Passage]:
        if not items:
            return list(self.passages)
        wanted = {i.upper() for i in items}
        return [p for p in self.passages if p.item.upper() in wanted]

    def passage(self, passage_id: str) -> Passage:
        for p in self.passages:
            if p.passage_id == passage_id:
                return p
        raise KeyError(passage_id)

    def cite(self, passage: Passage, start: int | None = None, end: int | None = None) -> Citation:
        """Build a citation for ``passage`` (or a sub-span given as absolute offsets)."""
        s = passage.start if start is None else start
        e = passage.end if end is None else end
        if not (passage.start <= s < e <= passage.end):
            raise ValueError("citation span outside passage")
        f = self.filing
        return Citation(
            cik=f.cik,
            company=f.company,
            accession=f.accession,
            form=f.form,
            filing_date=f.filing_date,
            item=passage.item,
            item_title=passage.item_title,
            passage_id=passage.passage_id,
            start=s,
            end=e,
            quote=self.text[s:e],
            source_url=f.document_url,
            parser_version=PARSER_VERSION,
        )


def parse_filing(filing: Filing, html: str) -> ParsedFiling:
    text = html_to_text(html)
    sections = split_items(text, filing.form)
    passages = split_passages(text, sections, filing.accession)
    return ParsedFiling(filing=filing, text=text, sections=sections, passages=passages)


def load_filing(client: EdgarClient, filing: Filing) -> ParsedFiling:
    return parse_filing(filing, client.primary_document(filing))


def verify_citation(doc: ParsedFiling, c: Citation) -> bool:
    """True iff the citation's quote is exactly the cited span of the document."""
    return (
        c.accession == doc.filing.accession
        and 0 <= c.start < c.end <= len(doc.text)
        and doc.text[c.start : c.end] == c.quote
    )
