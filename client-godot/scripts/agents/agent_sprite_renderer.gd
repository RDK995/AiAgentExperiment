extends Node2D

const AgentVisualStateStore := preload("res://scripts/agents/agent_visual_state_store.gd")

@export var tile_size: int = 32
@export var marker_radius: float = 10.0
@export_range(0.0, 1.0, 0.01) var interpolation_alpha: float = 0.35

var _snapshot: Dictionary = {}
var _visual_state_store: AgentVisualStateStore = AgentVisualStateStore.new()


func render_snapshot(snapshot: Dictionary) -> void:
	_snapshot = snapshot
	_visual_state_store.ingest_snapshot(snapshot, tile_size)
	queue_redraw()


func _process(_delta: float) -> void:
	_visual_state_store.advance_visuals(interpolation_alpha)
	queue_redraw()


func _draw() -> void:
	var agents_value: Variant = _snapshot.get("agents", [])
	if typeof(agents_value) != TYPE_ARRAY:
		return

	var agents: Array = agents_value
	for agent_data in agents:
		if typeof(agent_data) != TYPE_DICTIONARY:
			continue

		var position_value: Variant = agent_data.get("position", {})
		if typeof(position_value) != TYPE_DICTIONARY:
			continue

		var position_data: Dictionary = position_value
		var agent_id := str(agent_data.get("agent_id", ""))
		if agent_id.is_empty():
			continue

		var center: Vector2 = _visual_state_store.get_visual_position(agent_id)
		draw_circle(center, marker_radius, Color(0.89, 0.27, 0.23))


func get_visual_positions() -> Dictionary:
	return _visual_state_store.get_visual_positions()


func get_authoritative_positions() -> Dictionary:
	return _visual_state_store.get_authoritative_positions()
