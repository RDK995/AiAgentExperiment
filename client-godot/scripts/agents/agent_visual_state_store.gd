extends RefCounted

class_name AgentVisualStateStore

var _authoritative_positions: Dictionary = {}
var _visual_positions: Dictionary = {}


func ingest_snapshot(snapshot: Dictionary, tile_size: int) -> void:
	var agents_value: Variant = snapshot.get("agents", [])
	if typeof(agents_value) != TYPE_ARRAY:
		return

	var agents: Array = agents_value
	for agent_value in agents:
		if typeof(agent_value) != TYPE_DICTIONARY:
			continue

		var agent: Dictionary = agent_value
		var agent_id := str(agent.get("agent_id", ""))
		var position_value: Variant = agent.get("position", {})
		if agent_id.is_empty() or typeof(position_value) != TYPE_DICTIONARY:
			continue

		var position: Dictionary = position_value
		var authoritative_pixel_position := _tile_to_pixel(
			int(position.get("x", 0)),
			int(position.get("y", 0)),
			tile_size
		)

		_authoritative_positions[agent_id] = authoritative_pixel_position
		if not _visual_positions.has(agent_id):
			_visual_positions[agent_id] = authoritative_pixel_position


func advance_visuals(alpha: float) -> void:
	var clamped_alpha := clampf(alpha, 0.0, 1.0)

	for agent_id in _authoritative_positions.keys():
		var target: Vector2 = _authoritative_positions[agent_id]
		var current: Vector2 = _visual_positions.get(agent_id, target)
		_visual_positions[agent_id] = current.lerp(target, clamped_alpha)


func get_visual_position(agent_id: String) -> Vector2:
	return _visual_positions.get(agent_id, Vector2.ZERO)


func get_authoritative_position(agent_id: String) -> Vector2:
	return _authoritative_positions.get(agent_id, Vector2.ZERO)


func get_visual_positions() -> Dictionary:
	return _visual_positions.duplicate(true)


func get_authoritative_positions() -> Dictionary:
	return _authoritative_positions.duplicate(true)


func _tile_to_pixel(x: int, y: int, tile_size: int) -> Vector2:
	return Vector2(
		x * tile_size + (tile_size / 2.0),
		y * tile_size + (tile_size / 2.0)
	)
