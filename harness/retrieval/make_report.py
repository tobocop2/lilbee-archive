#!/usr/bin/env python3
"""Render EVIDENCE.md from the two probe outputs: metrics per side, fatal
invariant checks, and the baseline-vs-branch drift census."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

FUSION_TOLERANCE = 1e-6


def load_results(path: Path):
    """qid -> ordered [(source, chunk_index, score, distance, bm25)], plus answers."""
    ranked: dict[str, list[tuple]] = defaultdict(list)
    answers: dict[str, list[str]] = {}
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        qid = parts[0]
        if parts[1] == "answer":
            answers[qid] = parts[2:]
            continue
        source, chunk_index = parts[2], int(parts[3])
        score = float(parts[4]) if parts[4] else None
        distance = float(parts[5]) if len(parts) > 5 and parts[5] else None
        bm25 = float(parts[6]) if len(parts) > 6 and parts[6] else None
        ranked[qid].append((source, chunk_index, score, distance, bm25))
    return ranked, answers


def known_item_metrics(queries, ranked):
    hits_at_1 = hits_at_k = 0
    reciprocal_ranks = []
    total = 0
    for q in queries:
        if q["intent"] != "known_item":
            continue
        total += 1
        target = next(iter(q["qrels"]))
        rank = next(
            (i for i, row in enumerate(ranked.get(q["qid"], []), 1) if row[0] == target), None
        )
        if rank is not None:
            hits_at_k += 1
            reciprocal_ranks.append(1.0 / rank)
            if rank == 1:
                hits_at_1 += 1
        else:
            reciprocal_ranks.append(0.0)
    if total == 0:
        return None
    return {
        "queries": total,
        "success@1": hits_at_1 / total,
        "success@k": hits_at_k / total,
        "mrr": sum(reciprocal_ranks) / total,
    }


def check_invariants(queries, branch_ranked, branch_answers, baseline_ranked):
    """Fatal checks; returns a list of violation strings."""
    violations: list[str] = []
    for qid, rows in branch_ranked.items():
        for source, chunk_index, score, _, _ in rows:
            if score is None or not (0.0 <= score <= 1.0):
                violations.append(
                    f"INV_SCORE_RANGE {qid}: {source}#{chunk_index} score={score}"
                )
        # Dominance: strictly better on both provenance signals must not
        # score lower. Recomputed from output fields, not the fusion code.
        for i, a in enumerate(rows):
            for b in rows[i + 1 :]:
                if None in (a[2], b[2], a[3], b[3]):
                    continue
                a_bm25, b_bm25 = a[4] or 0.0, b[4] or 0.0
                if a[3] > b[3] and a_bm25 < b_bm25 and a[2] > b[2] + FUSION_TOLERANCE:
                    violations.append(
                        f"INV_DOMINANCE {qid}: {a[0]}#{a[1]} dominates worse yet scores higher "
                        f"than {b[0]}#{b[1]}"
                    )
    for q in queries:
        if q["intent"] == "known_item":
            target = next(iter(q["qrels"]))
            base_hit = any(r[0] == target for r in baseline_ranked.get(q["qid"], []))
            branch_hit = any(r[0] == target for r in branch_ranked.get(q["qid"], []))
            if base_hit and not branch_hit:
                violations.append(f"INV_KNOWN_ITEM_REGRESSION {q['qid']}: lost {target}")
        elif q["intent"] == "aggregate" and "oracle" in q:
            answer = branch_answers.get(q["qid"], [])
            numbers = {n for n in answer if n.isdigit()}
            expected = {str(q["oracle"]["chunks"]), str(q["oracle"]["sources"])}
            if answer and answer[0] != "UNSUPPORTED" and not expected <= numbers:
                violations.append(
                    f"INV_AGGREGATE_ORACLE {q['qid']}: expected {sorted(expected)} in answer, "
                    f"got numbers {sorted(numbers)}"
                )
    return violations


def drift_census(queries, baseline_ranked, branch_ranked):
    lines = []
    for q in queries:
        if q["intent"] == "aggregate":
            continue
        qid = q["qid"]
        base = [(r[0], r[1]) for r in baseline_ranked.get(qid, [])]
        branch = [(r[0], r[1]) for r in branch_ranked.get(qid, [])]
        added = [c for c in branch if c not in base]
        dropped = [c for c in base if c not in branch]
        if added or dropped or base != branch:
            lines.append(
                f"| {qid} | {q['intent']} | {len(added)} | {len(dropped)} | "
                f"{'yes' if base and branch and base != branch else 'no'} |"
            )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--branch", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    queries = [json.loads(line) for line in args.queries.read_text().splitlines() if line.strip()]
    baseline_ranked, _ = load_results(args.baseline)
    branch_ranked, branch_answers = load_results(args.branch)

    violations = check_invariants(queries, branch_ranked, branch_answers, baseline_ranked)
    base_metrics = known_item_metrics(queries, baseline_ranked)
    branch_metrics = known_item_metrics(queries, branch_ranked)
    census = drift_census(queries, baseline_ranked, branch_ranked)

    aggregates = [q for q in queries if q["intent"] == "aggregate"]
    agg_exact = sum(
        1
        for q in aggregates
        if "oracle" in q
        and {str(q["oracle"]["chunks"]), str(q["oracle"]["sources"])}
        <= set(branch_answers.get(q["qid"], []))
    )

    lines = ["# Retrieval sweep evidence", ""]
    lines.append(f"**Verdict: {'FAIL' if violations else 'PASS'}** "
                 f"({len(violations)} fatal violations)")
    lines.append("")
    if violations:
        lines.append("## Fatal violations")
        lines.extend(f"- `{v}`" for v in violations)
        lines.append("")
    lines.append("## Known-item metrics")
    lines.append("")
    lines.append("| side | queries | success@1 | success@k | MRR |")
    lines.append("| --- | --- | --- | --- | --- |")
    for side, metrics in (("baseline", base_metrics), ("branch", branch_metrics)):
        if metrics:
            lines.append(
                f"| {side} | {metrics['queries']} | {metrics['success@1']:.3f} "
                f"| {metrics['success@k']:.3f} | {metrics['mrr']:.3f} |"
            )
    lines.append("")
    lines.append("## Aggregates")
    lines.append("")
    lines.append(
        f"Branch answered {agg_exact}/{len(aggregates)} count questions with numbers exactly "
        f"matching the independent oracle. The baseline has no count capability."
    )
    lines.append("")
    lines.append("## Drift census (intentional ranking differences)")
    lines.append("")
    if census:
        lines.append("| qid | intent | added | dropped | reordered |")
        lines.append("| --- | --- | --- | --- | --- |")
        lines.extend(census)
    else:
        lines.append("No per-query differences.")
    args.out.write_text("\n".join(lines) + "\n")
    print(f"wrote {args.out}: {'FAIL' if violations else 'PASS'}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
