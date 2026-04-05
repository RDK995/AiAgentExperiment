extends Node

const PresentationBoundaryValidator := preload("res://scripts/validation/presentation_boundary_validator.gd")
const PresentationSnapshotProjector := preload("res://scripts/presentation/presentation_snapshot_projector.gd")

@onready var transport: Node = $WebsocketClient
@onready var world_root: Node2D = $WorldRoot
@onready var hud: CanvasLayer = $HUD

var _seed_definition: Dictionary = {}
var _snapshot: Dictionary = {}
var _recent_events: Array = []
var _selected_agent_id: String = ""


func _ready() -> void:
	transport.seed_definition_received.connect(_on_seed_definition_received)
	transport.snapshot_batch_received.connect(_on_snapshot_batch_received)
	transport.transport_warning.connect(_on_transport_warning)
	if transport.has_signal("transport_status_changed"):
		transport.transport_status_changed.connect(_on_transport_status_changed)
	world_root.agent_selected.connect(_on_agent_selected)
	hud.heatmap_toggled.connect(_on_heatmap_toggled)


func _on_seed_definition_received(seed_definition: Dictionary) -> void:
	var errors := PresentationBoundaryValidator.validate_seed_definition(seed_definition)
	if errors.size() > 0:
		for error_message in errors:
			push_error("Seed definition validation failed: %s" % error_message)
		return

	_seed_definition = PresentationSnapshotProjector.project_seed_definition(seed_definition)
	world_root.apply_seed_definition(_seed_definition)
	hud.bind_world_state(_snapshot, _seed_definition, _recent_events)
	_refresh_selected_agent()


func _on_snapshot_batch_received(snapshot: Dictionary, events: Array) -> void:
	var errors := PresentationBoundaryValidator.validate_snapshot(snapshot)
	if errors.size() > 0:
		for error_message in errors:
			push_error("Snapshot validation failed: %s" % error_message)
		return

	_snapshot = PresentationSnapshotProjector.project(snapshot)
	_recent_events = events.duplicate(true)
	world_root.apply_snapshot(_snapshot)
	hud.bind_world_state(_snapshot, _seed_definition, _recent_events)
	_refresh_selected_agent()


func _on_transport_warning(message: String) -> void:
	push_warning(message)
	hud.set_transport_warning(message)


func _on_transport_status_changed(mode: String, detail: String) -> void:
	if hud.has_method("set_transport_status"):
		hud.call("set_transport_status", mode, detail)


func _on_agent_selected(agent_id: String) -> void:
	_selected_agent_id = agent_id
	_refresh_selected_agent()


func _on_heatmap_toggled(enabled: bool) -> void:
	world_root.set_heatmap_enabled(enabled)


func _refresh_selected_agent() -> void:
	if _snapshot.is_empty() or _selected_agent_id.is_empty():
		hud.show_selected_agent({})
		return
	var agent := _find_agent(_selected_agent_id)
	if agent.is_empty():
		_selected_agent_id = ""
	hud.show_selected_agent(agent)


func _find_agent(agent_id: String) -> Dictionary:
	var agents_value: Variant = _snapshot.get("agents", [])
	if typeof(agents_value) != TYPE_ARRAY:
		return {}
	var agents: Array = agents_value
	for agent_value in agents:
		if typeof(agent_value) != TYPE_DICTIONARY:
			continue
		var agent: Dictionary = agent_value
		if str(agent.get("agent_id", "")) == agent_id:
			return agent
	return {}
