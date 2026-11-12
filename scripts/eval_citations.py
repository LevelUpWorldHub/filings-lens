#!/usr/bin/env python3
"""Score citation accuracy over hand-labeled fixture questions (offline).

python scripts/eval_citations.py [--backend mock] [--min-score 0.9]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from filings_lens.evaluation import run_eval  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(ROOT / "eval" / "questions.json"))
    ap.add_argument("--fixtures", default=str(ROOT / "tests" / "fixtures" / "edgar"))
    ap.add_argument("--backend", default="mock")
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rep = run_eval(Path(a.questions), Path(a.fixtures), a.backend)
    if a.json:
        print(json.dumps({"summary": rep.summary(), "overall": rep.overall, "rows": rep.rows}, indent=2))
    else:
        print(f"{'id':<5} {'status':<9} {'valid':<6} {'item':<6} {'evid':<6} {'refuse':<6}")
        fmt = lambda v: "-" if v is None else ("ok" if v else "FAIL")  # noqa: E731
        for r in rep.rows:
            print(
                f"{r['id']:<5} {r['status']:<9} {fmt(r['valid']):<6} {fmt(r['item_ok']):<6} "
                f"{fmt(r['evidence']):<6} {fmt(r['refusal_ok']):<6}"
            )
        print("summary:", rep.summary(), "overall:", rep.overall)
    return 0 if rep.overall >= a.min_score else 1


if __name__ == "__main__":
    sys.exit(main())
