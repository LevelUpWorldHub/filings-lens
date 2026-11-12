from __future__ import annotations

from filings_lens.parse import html_to_text, make_passage_id, split_items, split_passages


def test_html_to_text_blocks_hidden_and_furniture():
    html = (
        "<html><head><title>t</title></head><body>"
        "<div style='display: none'><ix:header>HIDDEN</ix:header>also hidden</div>"
        "<p>Hello&nbsp;  <b>world</b>.</p><p>12</p>"
        "<p>Apple Inc. | 2025 Form 10-K | 15</p><table><tr><td>a</td><td>b</td></tr></table>"
        "<script>var x=1</script></body></html>"
    )
    assert html_to_text(html) == "Hello world.\na b"


SAMPLE = "\n".join(
    [
        "FORM 10-K",
        "Item 1.",
        "Item 1A.",
        "Item 7.",
        "PART I",
        "Item 1. Business",
        "The Company designs widgets. " * 10,
        "Item 1A. Risk Factors",
        "Competition is intense.",
        "The Company faces aggressive price competition in every market it serves. " * 5,
        "Supply chains can be disrupted.",
        "Disruptions at suppliers can adversely affect results of operations and margins. " * 5,
        "PART II",
        "Item 7. Management's Discussion and Analysis",
        "Net sales increased due to higher widget volume. " * 6,
    ]
)


def test_split_items_skips_toc():
    secs = split_items(SAMPLE, "10-K")
    assert [s.item for s in secs] == ["1", "1A", "7"]
    assert SAMPLE[secs[1].start :].startswith("Item 1A. Risk Factors")
    assert secs[1].title == "Risk Factors"


def test_split_items_10q_is_part_aware():
    text = "\n".join(
        [
            "PART I",
            "Item 1. Financial Statements",
            "x" * 50,
            "Item 2. MD&A",
            "y" * 50,
            "PART II",
            "Item 1. Legal Proceedings",
            "z" * 50,
            "Item 1A. Risk Factors",
            "w" * 50,
        ]
    )
    assert [s.item for s in split_items(text, "10-Q")] == ["I.1", "I.2", "II.1", "II.1A"]


def test_split_items_8k():
    text = (
        "FORM 8-K\nItem 2.02 Results of Operations and Financial Condition.\n"
        "On Oct 30 results.\nItem 9.01 Exhibits\n99.1"
    )
    assert [s.item for s in split_items(text, "8-K")] == ["2.02", "9.01"]


def test_no_items_means_full_document():
    assert [s.item for s in split_items("just some text", "10-K")] == ["FULL"]


def test_passages_offsets_and_stable_ids():
    secs = split_items(SAMPLE, "10-K")
    ps = split_passages(SAMPLE, secs, "0000000000-25-000001")
    assert ps, "expected passages"
    for p in ps:
        assert SAMPLE[p.start : p.end] == p.text
        assert p.passage_id == make_passage_id("0000000000-25-000001", p.item, p.index, p.text)
        assert not p.text.startswith("Item ")
    rf = [p for p in ps if p.item == "1A"]
    # heading travels with its body
    assert rf[0].text.startswith("Competition is intense.\nThe Company faces")
    assert len(rf) == 2
    again = split_passages(SAMPLE, split_items(SAMPLE, "10-K"), "0000000000-25-000001")
    assert [p.passage_id for p in again] == [p.passage_id for p in ps]


def test_passages_never_cross_sections():
    secs = split_items(SAMPLE, "10-K")
    for p in split_passages(SAMPLE, secs, "a"):
        sec = next(s for s in secs if s.item == p.item)
        assert sec.start <= p.start < p.end <= sec.end


def test_real_fixture_sections(tenk_2025, tenq_2025, eightk):
    keys = [s.item for s in tenk_2025.sections]
    assert keys[:4] == ["1", "1A", "1B", "1C"]
    assert "7" in keys and keys[-1] == "16"  # TOC entries never win
    assert {"I.2", "II.1", "II.1A"} <= {s.item for s in tenq_2025.sections}
    assert [s.item for s in eightk.sections][:1] == ["2.02"]
    for doc in (tenk_2025, tenq_2025, eightk):
        for p in doc.passages:
            assert doc.text[p.start : p.end] == p.text
