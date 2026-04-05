"""Print a deterministic world-seed summary for local validation/debugging."""

from __future__ import annotations

import argparse
import json

from app.services.world_seed_service import WorldSeedService


def main() -> None:
    parser = argparse.ArgumentParser(description="Load and summarize one world seed.")
    parser.add_argument("--seed-id", default="v1_village")
    args = parser.parse_args()

    service = WorldSeedService()
    seed = service.load_seed_definition(args.seed_id)
    print(
        json.dumps(
            {
                "seed_id": seed.seed_id,
                "world": {
                    "width": seed.world.width,
                    "height": seed.world.height,
                    "structure_count": len(seed.world.structures),
                    "marker_count": len(seed.world.markers),
                    "tile_count": len(seed.world.tiles),
                },
                "population": len(seed.agents),
                "households": len(seed.households),
                "social_links": len(seed.social_links),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
