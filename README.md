# AiAgentExperiment

## Repository Layout

- `client-godot/`: Godot client project and game-facing content.
- `server/`: Python backend for simulation, cognition, and persistence.
- `docs/`: Architecture and design documentation.
- `ops/`: Observability and operational stack configs.

## Service Boundaries

The system is split into two clear runtime responsibilities:

1. **Godot client (`client-godot/`)**
   - Acts as the **renderer and user interface**.
   - Handles presentation, input capture, scene composition, and local UX behavior.
   - Does **not** own canonical world state.

2. **Python backend (`server/`)**
   - Acts as the **authoritative engine** for:
     - Simulation
     - Agent cognition/decision logic
     - Persistence and memory storage
   - Owns and validates canonical game/simulation state.
   - Exposes contracts consumed by the client.

The intended architecture keeps authoritative logic server-side while the Godot runtime remains focused on visualization and interaction.
