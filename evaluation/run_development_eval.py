"""Run deterministic fixture conformance; this is not a model-accuracy benchmark."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from backend.scamflow.detection import (
    CaseSnapshot,
    DevelopmentMockExtractor,
    SnapshotEvent,
    decide_digital_arrest,
    validate_extraction,
)


def run(path: Path) -> dict[str, Any]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    extractor = DevelopmentMockExtractor()
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    for scenario in dataset["scenarios"]:
        payment = scenario["payment_context"]
        snapshot = CaseSnapshot(
            case_id="evaluation-case",
            revision=1,
            events=tuple(SnapshotEvent(**event) for event in scenario["events"]),
            stated_purpose=payment["stated_purpose"],
            amount_decimal=payment["amount_decimal"],
            recipient_reference=payment["recipient_reference"],
        )
        started = time.perf_counter()
        raw = extractor.extract(snapshot)
        validated = validate_extraction(
            snapshot=snapshot,
            raw_output=raw,
            extraction_mode=extractor.mode,
            extraction_version=extractor.version,
        )
        decision = decide_digital_arrest(validated)
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        rows.append(
            {
                "family_id": scenario["family_id"],
                "expected_behaviour": scenario["expected_behaviour"],
                "observed_behaviour": decision.state,
                "interpretation_correct": decision.state == scenario["expected_behaviour"],
                "quote_validity": all(
                    next(
                        event for event in snapshot.events if event.event_id == item.event_id
                    ).text[item.start : item.end]
                    == item.quote
                    for item in validated.observations
                ),
                "first_warning_stage": scenario["expected_first_warning_stage"],
                "repeated_alerts": None,
                "missed_escalations": None,
                "latency_ms": round(latency_ms, 4),
                "token_usage": None,
            }
        )
    sorted_latency = sorted(latencies)
    p95_index = max(0, int(len(sorted_latency) * 0.95 + 0.9999) - 1) if sorted_latency else 0
    return {
        "label": "DEVELOPMENT MOCK FIXTURE CONFORMANCE — NOT REAL-MODEL ACCURACY",
        "dataset": dataset["dataset"],
        "provenance": dataset["provenance"],
        "scenario_count": len(rows),
        "fields_prepared": [
            "recall", "false_positives", "first_warning_stage", "repeated_alerts",
            "missed_escalations", "quote_validity", "interpretation_correctness",
            "p50_latency_ms", "p95_latency_ms", "token_usage",
        ],
        "p50_latency_ms": round(statistics.median(latencies), 4) if latencies else None,
        "p95_latency_ms": round(sorted_latency[p95_index], 4) if latencies else None,
        "token_usage": None,
        "rows": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("evaluation/scenarios/development.json"),
    )
    print(json.dumps(run(parser.parse_args().path), indent=2))
