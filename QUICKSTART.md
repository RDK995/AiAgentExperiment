# Quickstart

This is the shortest practical guide to run, test, and work on Autonomous Village.

For system context, read:

- [README.md](/Users/ryankenny/Projects/AiAgentExperiment/README.md)
- [ARCHITECTURE.md](/Users/ryankenny/Projects/AiAgentExperiment/ARCHITECTURE.md)

## What You Need

- Python 3.10+
- Godot 4.6 if you want to run the client

## Backend: Run Locally

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload
```

Backend defaults:

- host: `0.0.0.0`
- port: `8000`
- database: local SQLite at `./autonomous_village.db`

Optional env file:

```bash
cp ../.env.example .env
```

## Backend: Useful Endpoints

Health:

```bash
curl http://127.0.0.1:8000/health
```

Snapshot:

```bash
curl http://127.0.0.1:8000/api/v1/world/snapshot
```

Step one tick:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/world/tick
```

Recent world events:

```bash
curl http://127.0.0.1:8000/api/v1/world/events/recent
```

Debug metrics:

```bash
curl http://127.0.0.1:8000/api/v1/debug/metrics
curl http://127.0.0.1:8000/api/v1/debug/metrics/daily
```

Reset or seed world:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/admin/reset-world
curl -X POST http://127.0.0.1:8000/api/v1/world/seed -H 'Content-Type: application/json' -d '{"seed_id":"v1_village"}'
```

## Godot Client: Run Locally

Open:

- [client-godot/project.godot](/Users/ryankenny/Projects/AiAgentExperiment/client-godot/project.godot)

Run the project. The main scene is:

- [client-godot/scenes/Main.tscn](/Users/ryankenny/Projects/AiAgentExperiment/client-godot/scenes/Main.tscn)

Expected behavior:

1. backend starts on `localhost:8000`
2. Godot connects to the live world stream, or falls back to HTTP polling
3. world, inspector, replay, and dashboard populate from backend state

## Tests

Run the full backend suite:

```bash
cd server
pytest -q
```

Run a few high-value focused slices:

```bash
pytest tests/integration/test_runtime_and_world_api_integration.py -q
pytest tests/integration/test_endpoint_layer_api.py -q
pytest tests/telemetry/test_daily_metrics.py -q
pytest tests/social/test_reproduction.py -q
pytest tests/agents/test_action_catalog.py -q
```

## Verification Scripts

Run one-shot flow verifiers from the repo root:

```bash
PYTHONPATH=server python server/scripts/verify_world_stream.py --output world-stream-review-output.json
PYTHONPATH=server python server/scripts/verify_action_catalog_flow.py --output action-catalog-review-output.json
PYTHONPATH=server python server/scripts/verify_reproduction_flow.py --output reproduction-review-output.json
PYTHONPATH=server python server/scripts/verify_daily_metrics_debug_flow.py --output daily-metrics-review-output.json
```

## Where To Start Reading

If you are new to the codebase, start here:

1. [server/app/main.py](/Users/ryankenny/Projects/AiAgentExperiment/server/app/main.py)
2. [server/app/engine/tick_loop.py](/Users/ryankenny/Projects/AiAgentExperiment/server/app/engine/tick_loop.py)
3. [server/app/engine/world_loop.py](/Users/ryankenny/Projects/AiAgentExperiment/server/app/engine/world_loop.py)
4. [server/app/agents/runtime.py](/Users/ryankenny/Projects/AiAgentExperiment/server/app/agents/runtime.py)
5. [server/app/api/routes_world.py](/Users/ryankenny/Projects/AiAgentExperiment/server/app/api/routes_world.py)
6. [client-godot/scripts/networking/snapshot_consumer.gd](/Users/ryankenny/Projects/AiAgentExperiment/client-godot/scripts/networking/snapshot_consumer.gd)

## Important Boundary

Keep this rule in mind when making changes:

- **backend = authoritative simulation**
- **Godot = presentation only**

If a feature needs “real” state, expose it from the backend. Do not invent simulation truth in the client.
