"""Run a fixed question set through both agents and save the answers, so later runs (after
poisoning or hardening) can be compared with a known-good baseline.

Usage: python tests/baseline.py
Output: evidence/baseline-<state>-<timestamp>.json
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agents"))

import claims_analyst  # noqa: E402
import member_help  # noqa: E402


QUESTIONS = json.loads((ROOT / "tests" / "questions.json").read_text(encoding="utf-8"))


def main():
    out = []
    for agent, mod in (("member_help", member_help), ("claims_analyst", claims_analyst)):
        for item in QUESTIONS[agent]:
            print(f"\n=== {agent}: {item['q']}")
            tr = mod.ask(item["q"])
            out.append({"agent": agent, "question": item["q"], "expected_contains": item["expect"],
                        "answer": tr["answer"], "matched": all(e.lower() in tr["answer"].lower() for e in item["expect"]),
                        "routing": tr["routing"], "tool_calls": tr["tool_calls"]})
    path = ROOT / "evidence" / f"baseline-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    hits = sum(o["matched"] for o in out)
    print(f"\n{hits}/{len(out)} answers contained the expected facts. Saved {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
