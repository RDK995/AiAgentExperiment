extends Node2D

@export var tile_size: int = 24

var _enabled: bool = false
var _snapshot: Dictionary = {}


func set_overlay_enabled(enabled: bool) -> void:
	_enabled = enabled
	visible = enabled
	queue_redraw()


func set_snapshot(snapshot: Dictionary) -> void:
	_snapshot = snapshot.duplicate(true)
	queue_redraw()


func _draw() -> void:
	if not _enabled:
		return

	var agents_value: Variant = _snapshot.get("agents", [])
	if typeof(agents_value) != TYPE_ARRAY:
		return

	var agents: Array = agents_value
	for agent_value in agents:
		if typeof(agent_value) != TYPE_DICTIONARY:
			continue
		var agent: Dictionary = agent_value
		var needs_value: Variant = agent.get("needs", {})
		var position_value: Variant = agent.get("position", {})
		if typeof(needs_value) != TYPE_DICTIONARY or typeof(position_value) != TYPE_DICTIONARY:
			continue

		var needs: Dictionary = needs_value
		var position: Dictionary = position_value
		var hunger_ratio := clampf(float(needs.get("hunger", 0.0)) / 100.0, 0.0, 1.0)
		if hunger_ratio <= 0.0:
			continue
		draw_rect(
			Rect2(
				int(position.get("x", 0)) * tile_size,
				int(position.get("y", 0)) * tile_size,
				tile_size,
				tile_size
			),
			Color(1.0, 0.25, 0.18, 0.12 + (hunger_ratio * 0.35)),
			true
		)
