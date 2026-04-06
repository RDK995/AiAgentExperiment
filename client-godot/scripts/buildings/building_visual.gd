extends Node2D

@export var tile_size: int = 24

var _structure: Dictionary = {}

@onready var label_node: Label = $Label


func apply_structure(structure: Dictionary, new_tile_size: int) -> void:
	_structure = structure.duplicate(true)
	tile_size = new_tile_size
	position = Vector2(
		int(_structure.get("x", 0)) * tile_size,
		int(_structure.get("y", 0)) * tile_size
	)
	label_node.text = str(_structure.get("label", _structure.get("structure_type", "building")))
	label_node.position = Vector2(4, -18)
	label_node.modulate = Color(0.95, 0.96, 0.88, 0.72)
	label_node.visible = _should_show_label(str(_structure.get("structure_type", "building")))
	queue_redraw()


func _draw() -> void:
	if _structure.is_empty():
		return

	var width_tiles := int(_structure.get("width", 1))
	var height_tiles := int(_structure.get("height", 1))
	var rect := Rect2(0, 0, width_tiles * tile_size, height_tiles * tile_size)
	var structure_type := str(_structure.get("structure_type", "building"))
	var fill_color := _color_for_structure(structure_type)
	draw_rect(Rect2(3, 5, rect.size.x, rect.size.y), Color(0.0, 0.0, 0.0, 0.18), true)
	draw_rect(rect, fill_color, true)
	draw_rect(Rect2(rect.position, Vector2(rect.size.x, maxf(4.0, rect.size.y * 0.35))), fill_color.lightened(0.18), true)
	draw_rect(rect, Color(0.11, 0.10, 0.08, 0.72), false, 2.0)
	if structure_type == "house":
		var roof := PackedVector2Array([
			Vector2(0, 0),
			Vector2(rect.size.x * 0.5, -6),
			Vector2(rect.size.x, 0),
		])
		draw_colored_polygon(roof, Color(0.60, 0.29, 0.22, 0.95))


func _color_for_structure(structure_type: String) -> Color:
	match structure_type:
		"house":
			return Color(0.78, 0.58, 0.38)
		"village_center":
			return Color(0.77, 0.63, 0.33)
		"well":
			return Color(0.53, 0.67, 0.82)
		"farm_plot":
			return Color(0.34, 0.25, 0.15)
		"storage_hut":
			return Color(0.56, 0.42, 0.25)
		"cooking_area":
			return Color(0.59, 0.31, 0.23)
		"graveyard":
			return Color(0.48, 0.51, 0.56)
		_:
			return Color(0.58, 0.58, 0.58)


func _should_show_label(structure_type: String) -> bool:
	return structure_type in ["village_center", "well", "storage_hut", "cooking_area", "graveyard"]
