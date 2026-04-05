extends Node2D

@export var tile_size: int = 24
@export var marker_radius: float = 9.0
@export var interpolation_speed: float = 10.0

var _agent_data: Dictionary = {}
var _target_position: Vector2 = Vector2.ZERO
var _initialized: bool = false
var _selected: bool = false

@onready var label_node: Label = $Label


func apply_agent_snapshot(agent_data: Dictionary, new_tile_size: int) -> void:
	_agent_data = agent_data.duplicate(true)
	tile_size = new_tile_size
	_target_position = _tile_to_pixel(_agent_data.get("position", {}))
	if not _initialized:
		position = _target_position
		_initialized = true
	label_node.text = str(_agent_data.get("name", "Agent"))
	label_node.position = Vector2(-16, -24)
	queue_redraw()


func set_selected(is_selected: bool) -> void:
	_selected = is_selected
	queue_redraw()


func get_agent_id() -> String:
	return str(_agent_data.get("agent_id", ""))


func get_target_position() -> Vector2:
	return _target_position


func _process(delta: float) -> void:
	if not _initialized:
		return
	var alpha := clampf(delta * interpolation_speed, 0.0, 1.0)
	position = position.lerp(_target_position, alpha)


func _draw() -> void:
	if _agent_data.is_empty():
		return

	var base_color := _color_for_stage(str(_agent_data.get("stage_of_life", "adult")))
	if _selected:
		draw_circle(Vector2.ZERO, marker_radius + 5.0, Color(1.0, 0.95, 0.55, 0.25))
	draw_circle(Vector2.ZERO, marker_radius, base_color)
	draw_arc(Vector2.ZERO, marker_radius + 2.0, 0.0, TAU, 24, Color(0.12, 0.12, 0.12, 0.7), 2.0)


func _tile_to_pixel(position_data: Variant) -> Vector2:
	if typeof(position_data) != TYPE_DICTIONARY:
		return Vector2.ZERO
	var position_dictionary: Dictionary = position_data
	return Vector2(
		int(position_dictionary.get("x", 0)) * tile_size + (tile_size / 2.0),
		int(position_dictionary.get("y", 0)) * tile_size + (tile_size / 2.0)
	)


func _color_for_stage(stage_of_life: String) -> Color:
	match stage_of_life:
		"child":
			return Color(0.94, 0.66, 0.36)
		"adolescent":
			return Color(0.89, 0.42, 0.37)
		"elder":
			return Color(0.70, 0.65, 0.82)
		_:
			return Color(0.85, 0.24, 0.22)
