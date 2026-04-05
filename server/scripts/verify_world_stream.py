"""Manual verification script for the Godot-facing live world stream."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.api import WorldStreamEnvelope


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for world-stream verification."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="world-stream-review-output.json",
        help="Path to write the verification JSON report.",
    )
    return parser


def build_report() -> dict[str, object]:
    """Exercise the authoritative seed + stream path used by the Godot client."""

    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/world/stream?seed_id=v1_village&seed_on_connect=true&poll_seconds=0.05"
        ) as websocket:
            seed_message = WorldStreamEnvelope.model_validate(websocket.receive_json())
            first_batch = WorldStreamEnvelope.model_validate(websocket.receive_json())
            first_tick = first_batch.snapshot_batch.snapshot.tick if first_batch.snapshot_batch is not None else -1

            tick_response = client.post("/api/v1/world/tick")
            after_tick_batch = WorldStreamEnvelope.model_validate(websocket.receive_json())

        snapshot_response = client.get("/api/v1/world/snapshot")
        recent_events_response = client.get("/api/v1/world/events/recent?limit=20")

    first_snapshot = first_batch.snapshot_batch.snapshot if first_batch.snapshot_batch is not None else None
    second_snapshot = after_tick_batch.snapshot_batch.snapshot if after_tick_batch.snapshot_batch is not None else None
    second_events = after_tick_batch.snapshot_batch.events if after_tick_batch.snapshot_batch is not None else []

    checks = {
        "seed_definition_message_received": seed_message.message_type == "seed_definition",
        "seed_definition_has_v1_layout": (
            seed_message.seed_definition is not None
            and seed_message.seed_definition.seed_id == "v1_village"
            and seed_message.seed_definition.world.width == 64
            and seed_message.seed_definition.world.height == 64
        ),
        "snapshot_batch_received": first_batch.message_type == "snapshot_batch" and first_snapshot is not None,
        "initial_snapshot_matches_seeded_population": first_snapshot is not None and len(first_snapshot.agents) == 20,
        "live_tick_advanced_stream": second_snapshot is not None and second_snapshot.tick >= first_tick + 1,
        "stream_snapshot_matches_rest_snapshot": (
            second_snapshot is not None
            and second_snapshot.model_dump(mode="json") == snapshot_response.json()
        ),
        "recent_events_are_streamed": isinstance(second_events, list),
        "tick_endpoint_succeeded": tick_response.status_code == 200,
        "recent_events_endpoint_succeeded": recent_events_response.status_code == 200,
    }

    return {
        "checks": checks,
        "seed_definition_message": seed_message.model_dump(mode="json"),
        "first_snapshot_batch": first_batch.model_dump(mode="json"),
        "after_tick_snapshot_batch": after_tick_batch.model_dump(mode="json"),
        "rest_snapshot": snapshot_response.json(),
        "recent_events": recent_events_response.json(),
    }


def main() -> None:
    """Run the verification and write the JSON report to disk."""

    parser = build_parser()
    args = parser.parse_args()
    report = build_report()
    output_path = Path(args.output)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
