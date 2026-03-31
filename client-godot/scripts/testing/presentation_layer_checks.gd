extends SceneTree

const PresentationBoundaryValidator := preload("res://scripts/validation/presentation_boundary_validator.gd")
const PresentationSnapshotProjector := preload("res://scripts/presentation/presentation_snapshot_projector.gd")
const AgentVisualStateStore := preload("res://scripts/agents/agent_visual_state_store.gd")


func _initialize() -> void:
	_run_checks()
	quit(0)


func _run_checks() -> void:
	_check_valid_snapshot_is_accepted()
	_check_only_snapshot_contract_fields_are_accepted()
	_check_forbidden_authoritative_fields_are_rejected()
	_check_backend_agent_needs_field_is_accepted()
	_check_projection_discards_non_presentational_fields()
	_check_visual_interpolation_does_not_mutate_authoritative_positions()


func _check_valid_snapshot_is_accepted() -> void:
	var snapshot := _sample_snapshot()
	var errors := PresentationBoundaryValidator.validate_snapshot(snapshot)
	assert(errors.is_empty(), "Expected a valid presentation snapshot.")


func _check_forbidden_authoritative_fields_are_rejected() -> void:
	var snapshot := _sample_snapshot()
	var agents: Array = snapshot["agents"]
	var first_agent: Dictionary = agents[0]
	first_agent["inventory"] = {"berries": 4}
	agents[0] = first_agent
	snapshot["agents"] = agents

	var errors := PresentationBoundaryValidator.validate_snapshot(snapshot)
	var found_inventory_error := false
	for message in errors:
		if "forbidden authoritative field 'inventory'" in message:
			found_inventory_error = true
			break

	assert(found_inventory_error, "Expected forbidden authoritative agent fields to be rejected.")


func _check_only_snapshot_contract_fields_are_accepted() -> void:
	var snapshot := _sample_snapshot()
	snapshot["memory"] = [{"text": "forbidden"}]

	var errors := PresentationBoundaryValidator.validate_snapshot(snapshot)
	var found_contract_error := false
	for message in errors:
		if "forbidden authoritative field 'memory'" in message:
			found_contract_error = true
			break

	assert(found_contract_error, "Expected client to reject non-contract snapshot fields.")


func _check_backend_agent_needs_field_is_accepted() -> void:
	var snapshot := _sample_snapshot()
	var agents: Array = snapshot["agents"]
	var first_agent: Dictionary = agents[0]
	first_agent["needs"] = {
		"hunger": 10.0,
		"thirst": 20.0,
		"fatigue": 30.0,
	}
	agents[0] = first_agent
	snapshot["agents"] = agents

	var errors := PresentationBoundaryValidator.validate_snapshot(snapshot)
	assert(errors.is_empty(), "Expected backend agent 'needs' field to be accepted.")


func _check_projection_discards_non_presentational_fields() -> void:
	var snapshot := _sample_snapshot()
	var agents: Array = snapshot["agents"]
	var first_agent: Dictionary = agents[0]
	first_agent["needs"] = {"hunger": 10.0}
	agents[0] = first_agent
	snapshot["agents"] = agents

	var projected := PresentationSnapshotProjector.project(snapshot)
	var projected_agent: Dictionary = projected["agents"][0]

	assert(not projected_agent.has("needs"), "Projected client snapshot should discard non-render fields.")
	assert(projected_agent["position"]["x"] == 2, "Projected snapshot should keep render coordinates.")


func _check_visual_interpolation_does_not_mutate_authoritative_positions() -> void:
	var store = AgentVisualStateStore.new()
	var first_snapshot := _sample_snapshot()
	store.ingest_snapshot(first_snapshot, 32)

	var second_snapshot := _sample_snapshot()
	var second_agents: Array = second_snapshot["agents"]
	var second_agent: Dictionary = second_agents[0]
	second_agent["position"] = {"x": 4, "y": 6}
	second_agents[0] = second_agent
	second_snapshot["agents"] = second_agents
	store.ingest_snapshot(second_snapshot, 32)

	var authoritative_before: Dictionary = store.get_authoritative_positions()
	store.advance_visuals(0.25)
	var authoritative_after: Dictionary = store.get_authoritative_positions()
	var visual_after: Dictionary = store.get_visual_positions()

	assert(
		authoritative_before == authoritative_after,
		"Interpolation must not mutate authoritative client snapshot positions."
	)
	assert(
		visual_after["agent-1"] != authoritative_after["agent-1"],
		"Visual interpolation should move toward authority without becoming authority immediately."
	)


func _sample_snapshot() -> Dictionary:
	return {
		"tick": 12,
		"generated_at": "2026-03-31T20:00:00Z",
		"world": {
			"width": 16,
			"height": 12,
			"tiles": [
				{"x": 0, "y": 0, "terrain": "grass", "walkable": true},
				{"x": 1, "y": 0, "terrain": "path", "walkable": true},
			],
		},
		"agents": [
			{
				"agent_id": "agent-1",
				"name": "Villager 1",
				"position": {"x": 2, "y": 6},
				"current_action": "walking",
			}
		],
	}
