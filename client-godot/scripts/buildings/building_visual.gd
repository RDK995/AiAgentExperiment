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
	label_node.position = Vector2(0, -18)
	queue_redraw()


func _draw() -> void:
	if _structure.is_empty():
		return

	var width_tiles := int(_structure.get("width", 1))
	var height_tiles := int(_structure.get("height", 1))
	var rect := Rect2(0, 0, width_tiles * tile_size, height_tiles * tile_size)
	draw_rect(rect, _color_for_structure(str(_structure.get("structure_type", "building"))), true)
	draw_rect(rect, Color(0.08, 0.08, 0.08, 0.7), false, 2.0)


func _color_for_structure(structure_type: String) -> Color:
	match structure_type:
		"house":
			return Color(0.78, 0.58, 0.38)
		"village_center":
			return Color(0.89, 0.79, 0.41)
		"well":
			return Color(0.43, 0.63, 0.82)
		"farm_plot":
			return Color(0.45, 0.34, 0.19)
		"storage_hut":
			return Color(0.62, 0.46, 0.28)
		"cooking_area":
			return Color(0.74, 0.44, 0.34)
		"graveyard":
			return Color(0.47, 0.49, 0.52)
		_:
			return Color(0.58, 0.58, 0.58)
