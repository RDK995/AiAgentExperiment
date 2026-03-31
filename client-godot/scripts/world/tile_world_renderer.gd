extends Node2D

@export var tile_size: int = 32

var _snapshot: Dictionary = {}


func render_snapshot(snapshot: Dictionary) -> void:
	_snapshot = snapshot
	queue_redraw()


func _draw() -> void:
	var world_value: Variant = _snapshot.get("world", {})
	if typeof(world_value) != TYPE_DICTIONARY:
		return

	var world: Dictionary = world_value
	var tiles_value: Variant = world.get("tiles", [])
	if typeof(tiles_value) != TYPE_ARRAY:
		return

	var tiles: Array = tiles_value
	for tile_data in tiles:
		if typeof(tile_data) != TYPE_DICTIONARY:
			continue

		var x: int = int(tile_data.get("x", 0))
		var y: int = int(tile_data.get("y", 0))
		var terrain: String = str(tile_data.get("terrain", "grass"))
		draw_rect(
			Rect2(x * tile_size, y * tile_size, tile_size, tile_size),
			_color_for_terrain(terrain),
			true
		)
		draw_rect(
			Rect2(x * tile_size, y * tile_size, tile_size, tile_size),
			Color(0.1, 0.1, 0.1, 0.25),
			false,
			1.0
		)


func _color_for_terrain(terrain: String) -> Color:
	match terrain:
		"path":
			return Color(0.76, 0.66, 0.45)
		"water":
			return Color(0.25, 0.45, 0.84)
		_:
			return Color(0.45, 0.71, 0.39)
