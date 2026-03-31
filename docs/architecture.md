# Architecture

The simulation runs as a server-authoritative system.

- The Godot client renders the village and player-facing tools.
- The Python backend owns world state, agent cognition, memory, and simulation ticks.
- Telemetry and replay services support debugging and balancing.
