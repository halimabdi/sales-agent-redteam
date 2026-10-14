"""Orchestrator: runs every (persona, attack_type) pair serially, saves a
transcript + judge verdict per pair, and aggregates a violation matrix and
human-readable summary.

Usage:
    python run_redteam.py          # full run: every persona x every attack type
    python run_redteam.py 3        # reduced run: first 3 pairs only, for a quick check
"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BASE_DIR, ".env"))

from attack_types import ATTACK_TYPES  # noqa: E402
from conversation_loop import run_conversation  # noqa: E402
from judge import VIOLATION_CHECKLIST, judge_transcript  # noqa: E402

RESULTS_DIR = os.environ.get("RESULTS_DIR", os.path.join(BASE_DIR, "results", "latest"))
TRANSCRIPTS_DIR = os.path.join(RESULTS_DIR, "transcripts")
VERDICTS_DIR = os.path.join(RESULTS_DIR, "verdicts")


def _load_personas():
    with open(os.path.join(BASE_DIR, "personas.json")) as f:
        return json.load(f)["personas"]


def _build_matrix(all_verdicts):
    rule_ids = list(VIOLATION_CHECKLIST.keys())
    matrix = {"rule_ids": rule_ids, "rows": []}
    for v in all_verdicts:
        row = {"persona_id": v["persona_id"], "attack_type": v["attack_type"]}
        by_rule = {vv["rule_id"]: vv["verdict"] for vv in v["verdicts"]}
        for rid in rule_ids:
            row[rid] = by_rule.get(rid, "missing")
        matrix["rows"].append(row)

    violation_counts = {rid: 0 for rid in rule_ids}
    for row in matrix["rows"]:
        for rid in rule_ids:
            if row[rid] == "violated":
                violation_counts[rid] += 1
    matrix["violation_counts"] = violation_counts
    matrix["total_conversations"] = len(all_verdicts)
    return matrix


def _render_summary(matrix, all_verdicts):
    lines = [
        "# Outbound sales agent red-team: violation matrix summary",
        "",
        f"{matrix['total_conversations']} conversations judged.",
        "",
        "## Violation counts by rule",
        "",
        "| Rule | Violated | Held | Not triggered | Inconclusive |",
        "|---|---|---|---|---|",
    ]
    for rid in matrix["rule_ids"]:
        counts = {"violated": 0, "held": 0, "not_triggered": 0, "inconclusive": 0, "missing": 0}
        for row in matrix["rows"]:
            counts[row[rid]] = counts.get(row[rid], 0) + 1
        lines.append(
            f"| {rid} | {counts['violated']} | {counts['held']} | "
            f"{counts['not_triggered']} | {counts['inconclusive']} |"
        )

    lines += ["", "## Violations, by transcript", ""]
    any_violation = False
    for v in all_verdicts:
        for vv in v["verdicts"]:
            if vv["verdict"] == "violated":
                any_violation = True
                lines.append(
                    f"- **{v['persona_id']} / {v['attack_type']} / {vv['rule_id']}**: "
                    f"{vv['rationale']} (quote: \"{vv['quote']}\")"
                )
    if not any_violation:
        lines.append("(none)")

    return "\n".join(lines) + "\n"


def main(limit_pairs=None):
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    os.makedirs(VERDICTS_DIR, exist_ok=True)

    personas = _load_personas()
    pairs = [(p, a) for p in personas for a in ATTACK_TYPES]
    if limit_pairs:
        pairs = pairs[:limit_pairs]

    all_verdicts = []
    for i, (persona, attack_key) in enumerate(pairs, 1):
        tag = f"{persona['id']}__{attack_key}"
        print(f"[{i}/{len(pairs)}] {tag}")

        transcript_record = run_conversation(persona, attack_key)
        with open(os.path.join(TRANSCRIPTS_DIR, f"{tag}.json"), "w") as f:
            json.dump(transcript_record, f, indent=2)

        verdict_record = judge_transcript(transcript_record)
        with open(os.path.join(VERDICTS_DIR, f"{tag}.json"), "w") as f:
            json.dump(verdict_record, f, indent=2)

        all_verdicts.append(verdict_record)

    matrix = _build_matrix(all_verdicts)
    with open(os.path.join(RESULTS_DIR, "violation_matrix.json"), "w") as f:
        json.dump(matrix, f, indent=2)

    summary = _render_summary(matrix, all_verdicts)
    with open(os.path.join(RESULTS_DIR, "SUMMARY.md"), "w") as f:
        f.write(summary)

    print(f"\nDone. {len(all_verdicts)} conversations judged.")
    print(f"Results: {RESULTS_DIR}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit_pairs=limit)
