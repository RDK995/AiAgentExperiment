extends SceneTree

const PresentationBoundaryValidator := preload("res://scripts/validation/presentation_boundary_validator.gd")
const PresentationSnapshotProjector := preload("res://scripts/presentation/presentation_snapshot_projector.gd")
const AgentVisualStateStore := preload("res://scripts/agents/agent_visual_state_store.gd")


func _initialize() -> void:
	_run_checks()
	quit(0)


func _run_checks() -> void:
	_check_valid_snapshot_is_accepted()
	_check_valid_seed_definition_is_accepted()
	_check_valid_stream_envelopes_are_accepted()
	_check_invalid_stream_envelope_is_rejected()
	_check_only_snapshot_contract_fields_are_accepted()
	_check_forbidden_authoritative_fields_are_rejected()
	_check_snapshot_missing_agents_is_rejected()
	_check_backend_agent_needs_field_is_accepted()
	_check_projection_discards_non_presentational_fields()
	_check_projection_keeps_debug_ui_fields()
	_check_projection_handles_missing_optional_agent_fields()
	_check_seed_projection_keeps_households_and_social_links()
	_check_projection_discards_agents_without_positions()
	_check_village_dashboard_binds_authoritative_daily_metrics()
	_check_visual_interpolation_does_not_mutate_authoritative_positions()
	_check_main_scene_structure_loads()


func _check_valid_snapshot_is_accepted() -> void:
	var snapshot := _sample_snapshot()
	var errors := PresentationBoundaryValidator.validate_snapshot(snapshot)
	assert(errors.is_empty(), "Expected a valid presentation snapshot.")


func _check_valid_seed_definition_is_accepted() -> void:
	var seed_definition := _sample_seed_definition()
	var errors := PresentationBoundaryValidator.validate_seed_definition(seed_definition)
	assert(errors.is_empty(), "Expected a valid client-facing seed definition.")


func _check_valid_stream_envelopes_are_accepted() -> void:
	var seed_errors := PresentationBoundaryValidator.validate_stream_envelope(
		{
			"message_type": "seed_definition",
			"seed_definition": _sample_seed_definition(),
		}
	)
	assert(seed_errors.is_empty(), "Expected a valid seed-definition stream envelope.")

	var snapshot_errors := PresentationBoundaryValidator.validate_stream_envelope(
		{
			"message_type": "snapshot_batch",
			"snapshot_batch": {
				"snapshot": _sample_snapshot(),
				"events": [
					{"event_id": "evt-1", "tick": 12, "event_type": "child_born", "actor_ids": ["agent-1"], "target_ids": [], "payload": {}}
				],
			},
		}
	)
	assert(snapshot_errors.is_empty(), "Expected a valid snapshot-batch stream envelope.")


func _check_invalid_stream_envelope_is_rejected() -> void:
	var errors := PresentationBoundaryValidator.validate_stream_envelope(
		{
			"message_type": "snapshot_batch",
			"snapshot_batch": {
				"events": [],
			},
		}
	)
	assert(not errors.is_empty(), "Expected malformed snapshot-batch envelopes to be rejected.")


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


func _check_snapshot_missing_agents_is_rejected() -> void:
	var snapshot := _sample_snapshot()
	snapshot.erase("agents")

	var errors := PresentationBoundaryValidator.validate_snapshot(snapshot)
	var found_agents_error := false
	for message in errors:
		if "missing 'agents'" in message:
			found_agents_error = true
			break

	assert(found_agents_error, "Expected snapshots missing 'agents' to be rejected.")


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
	first_agent["inventory"] = {"berries": 2}
	agents[0] = first_agent
	snapshot["agents"] = agents

	var errors := PresentationBoundaryValidator.validate_snapshot(snapshot)
	var found_inventory_error := false
	for message in errors:
		if "forbidden authoritative field 'inventory'" in message:
			found_inventory_error = true
			break

	assert(found_inventory_error, "Client validation should reject authoritative inventory fields.")


func _check_projection_keeps_debug_ui_fields() -> void:
	var projected := PresentationSnapshotProjector.project(_sample_snapshot())
	var projected_agent: Dictionary = projected["agents"][0]

	assert(projected_agent["stage_of_life"] == "adult", "Projected snapshot should keep stage_of_life for UI.")
	assert(projected_agent["household_id"] == "household-1", "Projected snapshot should keep household binding.")
	assert(projected_agent["current_goal"] == "Gather food", "Projected snapshot should keep compact goal text.")


func _check_projection_handles_missing_optional_agent_fields() -> void:
	var snapshot := _sample_snapshot()
	var agents: Array = snapshot["agents"]
	var first_agent: Dictionary = agents[0]
	first_agent.erase("partner_id")
	first_agent.erase("current_goal")
	first_agent.erase("needs")
	agents[0] = first_agent
	snapshot["agents"] = agents

	var errors := PresentationBoundaryValidator.validate_snapshot(snapshot)
	assert(errors.is_empty(), "Missing optional agent fields should degrade gracefully.")

	var projected := PresentationSnapshotProjector.project(snapshot)
	var projected_agent: Dictionary = projected["agents"][0]
	assert(projected_agent["partner_id"] == null, "Missing partner should project as null.")
	assert(projected_agent["current_goal"] == null, "Missing goal should project as null.")
	assert(projected_agent["needs"] == {}, "Missing needs should project to an empty dictionary.")


func _check_seed_projection_keeps_households_and_social_links() -> void:
	var projected := PresentationSnapshotProjector.project_seed_definition(_sample_seed_definition())
	assert((projected.get("households", []) as Array).size() == 1, "Seed projection should keep households for the dashboard.")
	assert((projected.get("social_links", []) as Array).size() == 1, "Seed projection should keep social links for the inspector.")


func _check_projection_discards_agents_without_positions() -> void:
	var snapshot := _sample_snapshot()
	var agents: Array = snapshot["agents"]
	var first_agent: Dictionary = agents[0]
	first_agent.erase("position")
	agents[0] = first_agent
	snapshot["agents"] = agents

	var projected := PresentationSnapshotProjector.project(snapshot)
	assert((projected.get("agents", []) as Array).is_empty(), "Projection should skip malformed agents without valid positions.")


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


func _check_village_dashboard_binds_authoritative_daily_metrics() -> void:
	var dashboard_scene := load("res://scenes/ui/VillageDashboard.tscn")
	var dashboard := dashboard_scene.instantiate()
	dashboard.call("bind_data", _sample_snapshot(), _sample_seed_definition(), [], _sample_debug_metrics())
	var stats_label: Label = dashboard.get_node("Margin/VBox/Stats")
	assert(stats_label.text.contains("Food 18"), "Dashboard should render authoritative food reserves from debug metrics.")
	assert(stats_label.text.contains("Reflections/day 2"), "Dashboard should render cognition metrics from the backend.")
	dashboard.queue_free()


func _check_main_scene_structure_loads() -> void:
	var main_scene := load("res://scenes/Main.tscn")
	var instance := main_scene.instantiate()
	assert(instance.has_node("WebsocketClient"), "Main scene should contain the transport node.")
	assert(instance.has_node("WorldRoot"), "Main scene should contain the world root.")
	assert(instance.has_node("HUD"), "Main scene should contain the HUD.")
	instance.queue_free()


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
				"stage_of_life": "adult",
				"household_id": "household-1",
				"partner_id": "agent-2",
				"current_goal": "Gather food",
				"needs": {
					"hunger": 10.0,
					"thirst": 20.0,
					"fatigue": 30.0
				},
				"current_action": "walking",
			}
		],
	}


func _sample_seed_definition() -> Dictionary:
	return {
		"seed_id": "v1_village",
		"world": {
			"width": 64,
			"height": 64,
			"tiles": [
				{"x": 0, "y": 0, "terrain": "forest", "walkable": true},
				{"x": 1, "y": 0, "terrain": "grass", "walkable": true}
			],
			"structures": [
				{"structure_id": "house-1", "structure_type": "house", "x": 10, "y": 12, "width": 3, "height": 3}
			],
			"markers": [
				{"marker_id": "berries-west", "marker_type": "berries", "x": 2, "y": 24, "label": "Berry Patch"}
			]
		},
		"agents": [
			{
				"agent_id": "agent-1",
				"name": "Villager 1",
				"stage_of_life": "adult",
				"sex": "female",
				"household_id": "household-1",
				"home_structure_id": "house-1",
				"position": {"x": 10, "y": 12}
			}
		],
		"households": [
			{"household_id": "household-1", "home_structure_id": "house-1", "member_ids": ["agent-1"]}
		],
		"social_links": [
			{"kind": "bonded_pair", "agent_ids": ["agent-1", "agent-2"]}
		]
	}


func _sample_debug_metrics() -> Dictionary:
	return {
		"latest": {
			"day_index": 730121,
			"finalized_at": "2026-04-06T00:00:00Z",
			"population": {
				"total_population": 20,
				"births": 1,
				"deaths": 0,
				"infant_survival_rate": 1.0,
				"age_distribution": {"adult": 12, "adolescent": 4, "child": 3, "infant": 1}
			},
			"welfare": {
				"average_hunger": 4.5,
				"average_thirst": 3.0,
				"average_stress": 2.5,
				"starvation_count": 0,
				"illness_count": null
			},
			"social": {
				"active_bonds": 2,
				"household_count": 4,
				"mean_trust": 0.58,
				"conflict_events": 1,
				"gifts_per_day": 3
			},
			"economy": {
				"food_reserves": 18,
				"water_reserves": 9,
				"crop_yield": 2,
				"wood_stock": 7,
				"cooked_meals_per_day": 4
			},
			"cognition": {
				"reflections_per_day": 2,
				"average_memories_retrieved": 5.0,
				"invalid_model_outputs": 0,
				"mean_token_cost_per_day": 0.0
			}
		},
		"recent": []
	}
