extends Node2D

signal agent_selected(agent_id: String)

const AgentSpriteScene := preload("res://scenes/agents/AgentSprite.tscn")
const BuildingScene := preload("res://scenes/buildings/Building.tscn")

@export var tile_size: int = 24
@export var selection_radius: float = 18.0

@onready var buildings_layer: Node2D = $BuildingsLayer
@onready var agents_layer: Node2D = $AgentsLayer
@onready var heatmap_overlay: Node2D = $HeatmapOverlay

var _seed_definition: Dictionary = {}
var _snapshot: Dictionary = {}
var _building_nodes: Dictionary = {}
var _agent_nodes: Dictionary = {}
var _selected_agent_id: String = ""


func apply_seed_definition(seed_definition: Dictionary) -> void:
	_seed_definition = seed_definition.duplicate(true)
	_reconcile_buildings()
	queue_redraw()


func apply_snapshot(snapshot: Dictionary) -> void:
	_snapshot = snapshot.duplicate(true)
	_reconcile_agents()
	if heatmap_overlay.has_method("set_snapshot"):
		heatmap_overlay.call("set_snapshot", _snapshot)
	queue_redraw()


func set_heatmap_enabled(enabled: bool) -> void:
	if heatmap_overlay.has_method("set_overlay_enabled"):
		heatmap_overlay.call("set_overlay_enabled", enabled)


func _reconcile_buildings() -> void:
	var structures := _get_seed_structures()
	var valid_ids: Dictionary = {}
	for structure in structures:
		var structure_id := str(structure.get("structure_id", ""))
		if structure_id.is_empty():
			continue
		valid_ids[structure_id] = true
		var node: Node2D = _building_nodes.get(structure_id)
		if node == null:
			node = BuildingScene.instantiate()
			node.name = structure_id
			buildings_layer.add_child(node)
			_building_nodes[structure_id] = node
		if node.has_method("apply_structure"):
			node.call("apply_structure", structure, tile_size)

	for structure_id in _building_nodes.keys():
		if valid_ids.has(structure_id):
			continue
		var stale_node: Node = _building_nodes[structure_id]
		stale_node.queue_free()
		_building_nodes.erase(structure_id)


func _reconcile_agents() -> void:
	var agents_value: Variant = _snapshot.get("agents", [])
	if typeof(agents_value) != TYPE_ARRAY:
		return

	var agents: Array = agents_value
	var valid_ids: Dictionary = {}
	for agent_value in agents:
		if typeof(agent_value) != TYPE_DICTIONARY:
			continue
		var agent: Dictionary = agent_value
		var agent_id := str(agent.get("agent_id", ""))
		if agent_id.is_empty():
			continue
		valid_ids[agent_id] = true
		var node: Node2D = _agent_nodes.get(agent_id)
		if node == null:
			node = AgentSpriteScene.instantiate()
			node.name = agent_id
			agents_layer.add_child(node)
			_agent_nodes[agent_id] = node
		if node.has_method("apply_agent_snapshot"):
			node.call("apply_agent_snapshot", agent, tile_size)
		if node.has_method("set_selected"):
			node.call("set_selected", agent_id == _selected_agent_id)

	for agent_id in _agent_nodes.keys():
		if valid_ids.has(agent_id):
			continue
		var stale_node: Node = _agent_nodes[agent_id]
		stale_node.queue_free()
		_agent_nodes.erase(agent_id)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		var mouse_event := event as InputEventMouseButton
		var selected_id := _agent_at_point(mouse_event.position)
		if not selected_id.is_empty():
			_selected_agent_id = selected_id
			for agent_id in _agent_nodes.keys():
				var node: Node = _agent_nodes[agent_id]
				if node.has_method("set_selected"):
					node.call("set_selected", agent_id == _selected_agent_id)
			agent_selected.emit(selected_id)


func _draw() -> void:
	var world_data := _get_world_data()
	var tiles_value: Variant = world_data.get("tiles", [])
	if typeof(tiles_value) != TYPE_ARRAY:
		return

	var tiles: Array = tiles_value
	for tile_value in tiles:
		if typeof(tile_value) != TYPE_DICTIONARY:
			continue
		var tile: Dictionary = tile_value
		var x := int(tile.get("x", 0))
		var y := int(tile.get("y", 0))
		var terrain := str(tile.get("terrain", "grass"))
		var rect := Rect2(x * tile_size, y * tile_size, tile_size, tile_size)
		draw_rect(rect, _color_for_terrain(terrain), true)
		draw_rect(rect, Color(0.1, 0.1, 0.1, 0.1), false, 1.0)

	var markers := _get_seed_markers()
	for marker in markers:
		var marker_position := Vector2(
			int(marker.get("x", 0)) * tile_size + (tile_size / 2.0),
			int(marker.get("y", 0)) * tile_size + (tile_size / 2.0)
		)
		draw_circle(marker_position, 5.0, _color_for_marker(str(marker.get("marker_type", "marker"))))


func _agent_at_point(point: Vector2) -> String:
	var best_id := ""
	var best_distance := selection_radius
	for agent_id in _agent_nodes.keys():
		var node: Node2D = _agent_nodes[agent_id]
		var distance := node.position.distance_to(point)
		if distance <= best_distance:
			best_distance = distance
			best_id = agent_id
	return best_id


func _get_world_data() -> Dictionary:
	if _seed_definition.has("world"):
		return _seed_definition.get("world", {})
	var snapshot_world: Variant = _snapshot.get("world", {})
	return snapshot_world if typeof(snapshot_world) == TYPE_DICTIONARY else {}


func _get_seed_structures() -> Array:
	var world_data: Variant = _seed_definition.get("world", {})
	if typeof(world_data) != TYPE_DICTIONARY:
		return []
	var world_dictionary: Dictionary = world_data
	var structures_value: Variant = world_dictionary.get("structures", [])
	if typeof(structures_value) != TYPE_ARRAY:
		return []
	return structures_value


func _get_seed_markers() -> Array:
	var world_data: Variant = _seed_definition.get("world", {})
	if typeof(world_data) != TYPE_DICTIONARY:
		return []
	var world_dictionary: Dictionary = world_data
	var markers_value: Variant = world_dictionary.get("markers", [])
	if typeof(markers_value) != TYPE_ARRAY:
		return []
	return markers_value


func _color_for_terrain(terrain: String) -> Color:
	match terrain:
		"path":
			return Color(0.76, 0.66, 0.45)
		"water":
			return Color(0.25, 0.45, 0.84)
		"forest":
			return Color(0.20, 0.42, 0.22)
		_:
			return Color(0.45, 0.71, 0.39)


func _color_for_marker(marker_type: String) -> Color:
	match marker_type:
		"berries":
			return Color(0.74, 0.15, 0.34)
		"river_edge":
			return Color(0.25, 0.45, 0.84)
		"forest":
			return Color(0.18, 0.32, 0.18)
		_:
			return Color(0.85, 0.85, 0.85)
