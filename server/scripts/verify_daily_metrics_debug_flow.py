"""Manual verification script for the daily metrics debug API flow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.api import DailyMetricsDebugResponse, DebugMetricsResponse


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for daily-metrics verification."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="daily-metrics-review-output.json",
        help="Path to write the verification JSON report.",
    )
    return parser


def build_report() -> dict[str, object]:
    """Exercise the daily metrics debug path used by dashboard/debug consumers."""

    app = create_app()
    with TestClient(app) as client:
        reset_response = client.post("/api/v1/admin/reset-world")
        before_daily_response = client.get("/api/v1/debug/metrics/daily?limit=3")
        before_debug_response = client.get("/api/v1/debug/metrics")

        advance_response = client.post("/api/v1/admin/advance-days/1")
        after_daily_response = client.get("/api/v1/debug/metrics/daily?limit=3")
        after_debug_response = client.get("/api/v1/debug/metrics")

    before_daily = DailyMetricsDebugResponse.model_validate(before_daily_response.json())
    before_debug = DebugMetricsResponse.model_validate(before_debug_response.json())
    after_daily = DailyMetricsDebugResponse.model_validate(after_daily_response.json())
    after_debug = DebugMetricsResponse.model_validate(after_debug_response.json())

    latest = after_daily.latest
    checks = {
        "reset_succeeded": reset_response.status_code == 200,
        "advance_day_succeeded": advance_response.status_code == 200,
        "daily_metrics_empty_before_rollover": before_daily.latest is None and before_daily.recent == [],
        "daily_metrics_present_after_rollover": latest is not None and len(after_daily.recent) >= 1,
        "debug_metrics_embed_latest_daily_snapshot": after_debug.latest_daily_metrics is not None,
        "debug_metrics_embed_recent_daily_history": len(after_debug.recent_daily_metrics) >= 1,
        "latest_and_recent_day_match": (
            latest is not None and after_daily.recent[-1].day_index == latest.day_index
        ),
        "population_metrics_exposed": latest is not None and latest.population.total_population >= 1,
        "welfare_metrics_exposed": latest is not None and latest.welfare.average_hunger >= 0.0,
        "social_metrics_exposed": latest is not None and latest.social.household_count >= 0,
        "economy_metrics_exposed": latest is not None and latest.economy.food_reserves >= 0,
        "cognition_metrics_exposed": latest is not None and latest.cognition.reflections_per_day >= 0,
        "dashboard_bind_fields_present": latest is not None
        and {
            "population",
            "welfare",
            "social",
            "economy",
            "cognition",
        }.issubset(latest.model_dump(mode="json").keys()),
    }

    return {
        "checks": checks,
        "admin_reset": reset_response.json(),
        "admin_advance_days": advance_response.json(),
        "before_rollover_daily_metrics": before_daily.model_dump(mode="json"),
        "before_rollover_debug_metrics": before_debug.model_dump(mode="json"),
        "after_rollover_daily_metrics": after_daily.model_dump(mode="json"),
        "after_rollover_debug_metrics": after_debug.model_dump(mode="json"),
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
