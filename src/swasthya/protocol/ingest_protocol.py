"""Deterministically build `graph.json` from `disease_triage_matrix.json`.

Nodes are conditions, symptoms, warning signs and tiers. Edges connect a
symptom or warning sign to the condition(s) it participates in, and connect
each condition to the tier(s) it can resolve to.

Run directly to (re)write the committed `graph.json`:

    python -m swasthya.protocol.ingest_protocol

Run with --check in CI (architecture.md loop L10): regenerates the graph in
memory and diffs it against the committed file without writing anything,
exiting nonzero if they differ. A protocol edit that was not followed by a
regenerated, committed `graph.json` fails the build.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MATRIX_PATH = Path(__file__).parent / "disease_triage_matrix.json"
GRAPH_PATH = Path(__file__).parent / "graph.json"


def _node(node_id: str, node_type: str, label: str) -> dict[str, str]:
    return {"id": node_id, "type": node_type, "label": label}


def _edge(source: str, target: str, relation: str) -> dict[str, str]:
    return {"source": source, "target": target, "relation": relation}


def build_graph(matrix: dict[str, Any]) -> dict[str, Any]:
    """Pure function: matrix dict in, graph dict out. No I/O, no randomness."""
    nodes: dict[str, dict[str, str]] = {}
    edges: list[dict[str, str]] = []

    for tier in matrix["tier_order_low_to_high_acuity"]:
        tier_node_id = f"tier:{tier}"
        nodes[tier_node_id] = _node(tier_node_id, "tier", tier)

    for condition in matrix["conditions"]:
        condition_id = f"condition:{condition['id']}"
        nodes[condition_id] = _node(condition_id, "condition", condition["name"])

        for symptom in condition["required_symptoms"]:
            symptom_id = f"symptom:{symptom}"
            nodes[symptom_id] = _node(symptom_id, "symptom", symptom)
            edges.append(_edge(symptom_id, condition_id, "required_symptom"))

        for symptom in condition.get("supporting_symptoms", []):
            symptom_id = f"symptom:{symptom}"
            nodes[symptom_id] = _node(symptom_id, "symptom", symptom)
            edges.append(_edge(symptom_id, condition_id, "supporting_symptom"))

        for warning_sign in condition.get("warning_signs", []):
            warning_id = f"warning_sign:{warning_sign}"
            nodes[warning_id] = _node(warning_id, "warning_sign", warning_sign)
            edges.append(_edge(warning_id, condition_id, "warning_sign"))

        base_tier_id = f"tier:{condition['tier']}"
        edges.append(_edge(condition_id, base_tier_id, "resolves_to_tier"))

        escalated_tier = condition.get("escalated_tier")
        if escalated_tier and escalated_tier != condition["tier"]:
            escalated_tier_id = f"tier:{escalated_tier}"
            edges.append(_edge(condition_id, escalated_tier_id, "escalates_to_tier"))

    sorted_nodes = sorted(nodes.values(), key=lambda n: n["id"])
    sorted_edges = sorted(edges, key=lambda e: (e["source"], e["target"], e["relation"]))

    return {
        "protocol_version": matrix["protocol_version"],
        "node_count": len(sorted_nodes),
        "edge_count": len(sorted_edges),
        "nodes": sorted_nodes,
        "edges": sorted_edges,
    }


def _load_matrix() -> dict[str, Any]:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def _dumps(graph: dict[str, Any]) -> str:
    return json.dumps(graph, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def _diff_summary(committed: dict[str, Any], regenerated: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    committed_nodes = {n["id"] for n in committed.get("nodes", [])}
    regenerated_nodes = {n["id"] for n in regenerated.get("nodes", [])}
    only_committed = sorted(committed_nodes - regenerated_nodes)
    only_regenerated = sorted(regenerated_nodes - committed_nodes)
    if only_committed:
        lines.append(f"nodes only in committed graph.json: {only_committed}")
    if only_regenerated:
        lines.append(f"nodes only in regenerated graph: {only_regenerated}")

    committed_edges = {(e["source"], e["target"], e["relation"]) for e in committed.get("edges", [])}
    regenerated_edges = {(e["source"], e["target"], e["relation"]) for e in regenerated.get("edges", [])}
    only_committed_e = sorted(committed_edges - regenerated_edges)
    only_regenerated_e = sorted(regenerated_edges - committed_edges)
    if only_committed_e:
        lines.append(f"edges only in committed graph.json: {only_committed_e}")
    if only_regenerated_e:
        lines.append(f"edges only in regenerated graph: {only_regenerated_e}")

    if committed.get("protocol_version") != regenerated.get("protocol_version"):
        lines.append(
            f"protocol_version mismatch: committed={committed.get('protocol_version')!r} "
            f"regenerated={regenerated.get('protocol_version')!r}"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Regenerate in memory and diff against the committed graph.json; "
        "exit nonzero on mismatch. Does not write any file.",
    )
    args = parser.parse_args(argv)

    matrix = _load_matrix()
    regenerated = build_graph(matrix)

    if args.check:
        if not GRAPH_PATH.exists():
            print(f"FAIL: {GRAPH_PATH} does not exist. Run without --check to generate it.")
            return 1
        committed = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
        if committed == regenerated:
            print(f"OK: {GRAPH_PATH} matches disease_triage_matrix.json.")
            return 0
        print(f"FAIL: {GRAPH_PATH} is stale relative to disease_triage_matrix.json.")
        for line in _diff_summary(committed, regenerated):
            print(f"  - {line}")
        print("Run `python -m swasthya.protocol.ingest_protocol` and commit the result.")
        return 1

    GRAPH_PATH.write_text(_dumps(regenerated), encoding="utf-8")
    print(f"Wrote {GRAPH_PATH} ({regenerated['node_count']} nodes, {regenerated['edge_count']} edges).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
