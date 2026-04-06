extends CanvasLayer

signal heatmap_toggled(enabled: bool)

var _last_snapshot: Dictionary = {}
var _last_seed_definition: Dictionary = {}
var _last_events: Array = []
var _transport_status: String = "Starting..."
var _transport_warning: String = ""

@onready var status_label: Label = $Root/TopBar/Margin/TopBarRow/StatusLabel
@onready var inspector_button: Button = $Root/TopBar/Margin/TopBarRow/InspectorButton
@onready var replay_button: Button = $Root/TopBar/Margin/TopBarRow/ReplayButton
@onready var heatmap_button: Button = $Root/TopBar/Margin/TopBarRow/HeatmapButton
@onready var inspector_panel: PanelContainer = $Root/AgentInspectorPanel
@onready var dashboard_panel: PanelContainer = $Root/VillageDashboard
@onready var replay_panel: PanelContainer = $Root/ReplayPanel


func _ready() -> void:
	heatmap_button.toggled.connect(_on_heatmap_toggled)
	inspector_button.toggled.connect(_on_inspector_toggled)
	replay_button.toggled.connect(_on_replay_toggled)
	_apply_panel_visibility()


func bind_world_state(snapshot: Dictionary, seed_definition: Dictionary, events: Array) -> void:
	_last_snapshot = snapshot.duplicate(true)
	_last_seed_definition = seed_definition.duplicate(true)
	_last_events = events.duplicate(true)
	_update_status_line()
	if dashboard_panel.has_method("bind_data"):
		dashboard_panel.call("bind_data", _last_snapshot, _last_seed_definition, _last_events)
	if replay_panel.has_method("bind_events"):
		replay_panel.call("bind_events", _last_events)


func show_selected_agent(agent_data: Dictionary) -> void:
	if inspector_panel.has_method("bind_agent"):
		inspector_panel.call("bind_agent", agent_data, _last_seed_definition)
	if agent_data.is_empty():
		inspector_button.button_pressed = false
	else:
		inspector_button.button_pressed = true
	_apply_panel_visibility()


func set_transport_warning(message: String) -> void:
	_transport_warning = message
	_update_status_line()


func set_transport_status(mode: String, detail: String) -> void:
	_transport_status = "%s: %s" % [mode.capitalize(), detail]
	if not detail.contains("No active seed found"):
		_transport_warning = ""
	_update_status_line()


func _on_heatmap_toggled(enabled: bool) -> void:
	heatmap_toggled.emit(enabled)


func _on_inspector_toggled(_enabled: bool) -> void:
	_apply_panel_visibility()


func _on_replay_toggled(_enabled: bool) -> void:
	_apply_panel_visibility()


func _apply_panel_visibility() -> void:
	inspector_panel.visible = inspector_button.button_pressed
	replay_panel.visible = replay_button.button_pressed


func _update_status_line() -> void:
	var tick := int(_last_snapshot.get("tick", 0))
	var agent_count := 0
	var agents_value: Variant = _last_snapshot.get("agents", [])
	if typeof(agents_value) == TYPE_ARRAY:
		agent_count = (agents_value as Array).size()
	var seed_label := str(_last_seed_definition.get("seed_id", "prototype"))
	var world_value: Variant = _last_snapshot.get("world", {})
	var size_label := "0x0"
	if typeof(world_value) == TYPE_DICTIONARY:
		var world: Dictionary = world_value
		size_label = "%dx%d" % [int(world.get("width", 0)), int(world.get("height", 0))]
	var parts := PackedStringArray()
	parts.append(_transport_status)
	parts.append("Tick %d" % tick)
	parts.append("Agents %d" % agent_count)
	parts.append("World %s" % size_label)
	parts.append("Seed %s" % seed_label)
	if not _transport_warning.is_empty():
		parts.append(_transport_warning)
	status_label.text = "   |   ".join(parts)
