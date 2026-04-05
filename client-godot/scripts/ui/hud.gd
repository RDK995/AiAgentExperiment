extends CanvasLayer

signal heatmap_toggled(enabled: bool)

var _last_snapshot: Dictionary = {}
var _last_seed_definition: Dictionary = {}
var _last_events: Array = []
var _transport_status: String = "Starting..."

@onready var status_label: Label = $Root/Margin/TopBar/StatusLabel
@onready var heatmap_button: Button = $Root/Margin/TopBar/HeatmapButton
@onready var inspector_panel: PanelContainer = $Root/Margin/Panels/AgentInspectorPanel
@onready var dashboard_panel: PanelContainer = $Root/Margin/Panels/VillageDashboard
@onready var replay_panel: PanelContainer = $Root/Margin/Panels/ReplayPanel


func _ready() -> void:
	heatmap_button.toggled.connect(_on_heatmap_toggled)


func bind_world_state(snapshot: Dictionary, seed_definition: Dictionary, events: Array) -> void:
	_last_snapshot = snapshot.duplicate(true)
	_last_seed_definition = seed_definition.duplicate(true)
	_last_events = events.duplicate(true)
	status_label.text = "%s | Tick %d | Agents %d | Seed %s" % [
		_transport_status,
		int(snapshot.get("tick", 0)),
		((snapshot.get("agents", []) as Array).size()),
		str(seed_definition.get("seed_id", "prototype")),
	]
	if dashboard_panel.has_method("bind_data"):
		dashboard_panel.call("bind_data", _last_snapshot, _last_seed_definition, _last_events)
	if replay_panel.has_method("bind_events"):
		replay_panel.call("bind_events", _last_events)


func show_selected_agent(agent_data: Dictionary) -> void:
	if inspector_panel.has_method("bind_agent"):
		inspector_panel.call("bind_agent", agent_data, _last_seed_definition)


func set_transport_warning(message: String) -> void:
	_transport_status = message
	status_label.text = message


func set_transport_status(mode: String, detail: String) -> void:
	_transport_status = "%s: %s" % [mode.capitalize(), detail]
	if not _last_snapshot.is_empty() or not _last_seed_definition.is_empty():
		bind_world_state(_last_snapshot, _last_seed_definition, _last_events)
	else:
		status_label.text = _transport_status


func _on_heatmap_toggled(enabled: bool) -> void:
	heatmap_toggled.emit(enabled)
