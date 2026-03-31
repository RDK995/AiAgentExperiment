# Autonomous Village

Monorepo scaffold for an AI village simulator with a Godot client, a Python simulation backend, project docs, and ops tooling.

## Top-Level Layout

- `client-godot/`: Godot project for rendering, UI, and local interaction.
- `server/`: Authoritative simulation, cognition, memory, API, and telemetry services.
- `docs/`: Living design documents for architecture, rules, memory, API contracts, and prompts.
- `ops/`: Monitoring and observability stack placeholders.

## Initial Goal

This repository currently provides the base folder structure for:

- world simulation
- autonomous agent behavior
- memory and cognition pipelines
- social systems and family lifecycle mechanics
- telemetry, replay, and debugging

The next step is to flesh out the server runtime and connect the Godot client to the simulation API.
