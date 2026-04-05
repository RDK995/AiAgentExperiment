# Godot Live Stream Smoke Checklist

Use this after starting the backend and opening the Godot client.

## Backend

Run:

```bash
cd /Users/ryankenny/Projects/AiAgentExperiment/server
uvicorn app.main:app --reload
```

Optional backend-only verification:

```bash
PYTHONPATH=server python server/scripts/verify_world_stream.py --output world-stream-review-output.json
```

Expected:
- a `seed_definition` stream message arrives first
- a `snapshot_batch` message arrives next
- after one tick, a later stream message shows a higher tick

## Godot

Open:
- [project.godot](/Users/ryankenny/Projects/AiAgentExperiment/client-godot/project.godot)

Run:
- [Main.tscn](/Users/ryankenny/Projects/AiAgentExperiment/client-godot/scenes/Main.tscn)

## What to verify

1. Transport status
- HUD shows a live websocket status such as `Websocket: Connected to live backend stream.`
- If websocket is unavailable, HUD shows the HTTP polling fallback warning instead of silently failing

2. Seed/bootstrap
- World renders the fixed `v1_village` layout
- Buildings and markers appear in stable deterministic positions
- Initial population renders as 20 agents

3. Snapshot updates
- Trigger one or more backend ticks
- Agent positions update from backend snapshots
- Movement is visually interpolated, not simulated client-side

4. Inspector
- Click an agent
- Inspector shows:
  - name
  - stage
  - action
  - goal
  - household
  - needs
  - partner/social summary when available
- Selection persists across later snapshot batches

5. Dashboard
- Dashboard shows:
  - population counts
  - household count
  - structure count
  - average hunger
  - recent births/deaths from recent events

6. Replay panel
- Replay panel updates after backend ticks
- New event rows show recent event types and ticks

7. Heatmap
- Toggle heatmap from the HUD
- Overlay updates without changing authoritative state

8. Reseed safety
- Re-hit the world seed route or restart the backend
- Client re-renders the reseeded world cleanly
- Removed/recreated visuals reconcile without stale entities lingering

## Good failure checks

- Stop the backend after client startup:
  - client should show a transport warning rather than inventing state
- Break websocket connectivity but keep HTTP endpoints up:
  - client should fall back to polling
  - world, HUD, inspector, and replay should still update from backend snapshots

## Pass criteria

- Client renders only backend-provided state
- Stream or fallback transport updates all major presentation panels
- Interpolation remains visual only
- No stale entity leaks after reseed or later snapshot reconciliation
