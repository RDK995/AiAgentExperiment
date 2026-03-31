extends Node2D

const PresentationBoundaryValidator := preload("res://scripts/validation/presentation_boundary_validator.gd")
const PresentationSnapshotProjector := preload("res://scripts/presentation/presentation_snapshot_projector.gd")

@onready var snapshot_client: Node = $SnapshotClient
@onready var tile_world_renderer: Node2D = $TileWorldRenderer
@onready var agent_sprite_renderer: Node2D = $AgentSpriteRenderer

var _last_projected_snapshot: Dictionary = {}


func _ready() -> void:
	snapshot_client.snapshot_received.connect(_on_snapshot_received)
	snapshot_client.request_failed.connect(_on_request_failed)


func _on_snapshot_received(snapshot: Dictionary) -> void:
	var validation_errors := PresentationBoundaryValidator.validate_snapshot(snapshot)
	if validation_errors.size() > 0:
		for error_message in validation_errors:
			push_error("Presentation boundary violation: %s" % error_message)
		return

	_last_projected_snapshot = PresentationSnapshotProjector.project(snapshot)
	tile_world_renderer.render_snapshot(_last_projected_snapshot)
	agent_sprite_renderer.render_snapshot(_last_projected_snapshot)


func _on_request_failed(error_message: String) -> void:
	push_warning(error_message)


func get_last_projected_snapshot() -> Dictionary:
	return _last_projected_snapshot.duplicate(true)
