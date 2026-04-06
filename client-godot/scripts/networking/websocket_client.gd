extends Node

signal seed_definition_received(seed_definition: Dictionary)
signal snapshot_batch_received(snapshot: Dictionary, events: Array)
signal transport_warning(message: String)
signal transport_status_changed(mode: String, detail: String)

@export var base_url: String = "http://127.0.0.1:8000"
@export var seed_id: String = "v1_village"
@export var seed_on_startup: bool = false
@export var seed_if_backend_unseeded: bool = true
@export var prefer_live_stream: bool = true
@export var stream_path: String = "/api/v1/world/stream"
@export var seed_definition_path: String = "/api/v1/world/seeds/%s"
@export var seed_world_path: String = "/api/v1/world/seed"
@export var snapshot_path: String = "/api/v1/world/snapshot"
@export var recent_events_path: String = "/api/v1/world/events/recent?limit=20"
@export var poll_interval_seconds: float = 1.0
@export var stream_poll_seconds: float = 0.25
@export var reconnect_interval_seconds: float = 3.0
@export var stale_stream_timeout_seconds: float = 4.0

var _seed_request: HTTPRequest
var _seed_world_request: HTTPRequest
var _snapshot_request: HTTPRequest
var _events_request: HTTPRequest
var _poll_timer: Timer
var _reconnect_timer: Timer
var _pending_snapshot: Dictionary = {}
var _websocket := WebSocketPeer.new()
var _transport_mode: String = "idle"
var _websocket_open_announced: bool = false
var _fallback_active: bool = false
var _seed_bootstrap_attempted: bool = false
var _last_live_message_time_msec: int = 0
var _websocket_connect_started_msec: int = 0


func _ready() -> void:
	_seed_request = _make_request("_on_seed_definition_completed")
	_seed_world_request = _make_request("_on_seed_world_completed")
	_snapshot_request = _make_request("_on_snapshot_completed")
	_events_request = _make_request("_on_events_completed")

	_poll_timer = Timer.new()
	_poll_timer.wait_time = poll_interval_seconds
	_poll_timer.autostart = false
	_poll_timer.timeout.connect(fetch_batch)
	add_child(_poll_timer)

	_reconnect_timer = Timer.new()
	_reconnect_timer.wait_time = reconnect_interval_seconds
	_reconnect_timer.autostart = false
	_reconnect_timer.timeout.connect(_attempt_live_reconnect)
	add_child(_reconnect_timer)

	if prefer_live_stream:
		_start_websocket_stream()
	else:
		_start_http_fallback("Live stream disabled, using HTTP snapshot polling.")


func _process(_delta: float) -> void:
	if _transport_mode != "websocket":
		return

	_websocket.poll()
	var state := _websocket.get_ready_state()
	if state == WebSocketPeer.STATE_OPEN:
		if not _websocket_open_announced:
			_websocket_open_announced = true
			_fallback_active = false
			_last_live_message_time_msec = Time.get_ticks_msec()
			_poll_timer.stop()
			_reconnect_timer.stop()
			transport_status_changed.emit("websocket", "Connected to live backend stream.")
		while _websocket.get_available_packet_count() > 0:
			var packet := _websocket.get_packet().get_string_from_utf8()
			_last_live_message_time_msec = Time.get_ticks_msec()
			_handle_websocket_packet(packet)
		if _stream_has_gone_stale():
			_restart_stalled_stream()
	elif state == WebSocketPeer.STATE_CONNECTING:
		if _connect_attempt_has_timed_out():
			_restart_stalled_stream()
	elif state == WebSocketPeer.STATE_CLOSED and not _fallback_active:
		_start_http_fallback("Live backend stream unavailable, using HTTP snapshot polling.")


func fetch_batch() -> void:
	var error := _snapshot_request.request("%s%s" % [base_url, snapshot_path])
	if error != OK:
		transport_warning.emit("Failed to request snapshot: %s" % error_string(error))


func _start_websocket_stream() -> void:
	_transport_mode = "websocket"
	_websocket_open_announced = false
	_last_live_message_time_msec = 0
	_websocket_connect_started_msec = Time.get_ticks_msec()
	_websocket = WebSocketPeer.new()
	var connect_error := _websocket.connect_to_url(_build_stream_url())
	if connect_error != OK:
		_start_http_fallback("Failed to open live backend stream, using HTTP snapshot polling.")
		return
	transport_status_changed.emit("connecting", "Connecting to live backend stream...")


func _start_http_fallback(message: String) -> void:
	_fallback_active = true
	_transport_mode = "http"
	transport_warning.emit(message)
	transport_status_changed.emit("http", "Using HTTP snapshot polling.")
	if prefer_live_stream and _reconnect_timer.is_stopped():
		_reconnect_timer.start()
	_fetch_seed_definition()
	if seed_on_startup:
		_request_seed_world()
	else:
		_poll_timer.start()
		fetch_batch()


func _attempt_live_reconnect() -> void:
	if not prefer_live_stream or not _fallback_active:
		return
	if _transport_mode != "http":
		return
	transport_status_changed.emit("connecting", "Retrying live backend stream...")
	_start_websocket_stream()


func _restart_stalled_stream() -> void:
	transport_warning.emit("Live backend stream stalled, reconnecting...")
	transport_status_changed.emit("connecting", "Live stream stalled, reconnecting...")
	_websocket.close()
	_websocket_connect_started_msec = 0
	_start_http_fallback("Live backend stream stalled, using HTTP snapshot polling.")


func _handle_websocket_packet(packet: String) -> void:
	var json := JSON.new()
	var parse_error := json.parse(packet)
	if parse_error != OK:
		transport_warning.emit("Failed to parse live backend message: %s" % json.get_error_message())
		return

	var payload: Variant = json.data
	if typeof(payload) != TYPE_DICTIONARY:
		transport_warning.emit("Live backend payload was not a dictionary.")
		return

	var envelope: Dictionary = payload
	match str(envelope.get("message_type", "")):
		"seed_definition":
			var seed_definition: Variant = envelope.get("seed_definition", {})
			if typeof(seed_definition) == TYPE_DICTIONARY:
				seed_definition_received.emit(seed_definition)
		"snapshot_batch":
			var batch_value: Variant = envelope.get("snapshot_batch", {})
			if typeof(batch_value) != TYPE_DICTIONARY:
				return
			var batch: Dictionary = batch_value
			var snapshot_value: Variant = batch.get("snapshot", {})
			var events_value: Variant = batch.get("events", [])
			var snapshot: Dictionary = {}
			if typeof(snapshot_value) == TYPE_DICTIONARY:
				snapshot = snapshot_value
			var events: Array = []
			if typeof(events_value) == TYPE_ARRAY:
				events = events_value
			snapshot_batch_received.emit(snapshot, events)
		"warning":
			var warning_message := str(envelope.get("warning", "Backend stream warning."))
			if seed_if_backend_unseeded and _should_bootstrap_missing_seed(warning_message):
				_bootstrap_missing_seed()
			transport_warning.emit(warning_message)
		_:
			transport_warning.emit("Ignoring unsupported live backend message.")


func _fetch_seed_definition() -> void:
	var path := seed_definition_path % seed_id
	var error := _seed_request.request("%s%s" % [base_url, path])
	if error != OK:
		transport_warning.emit("Failed to request seed definition: %s" % error_string(error))


func _request_seed_world() -> void:
	var headers := PackedStringArray(["Content-Type: application/json"])
	var body := JSON.stringify({"seed_id": seed_id})
	var error := _seed_world_request.request(
		"%s%s" % [base_url, seed_world_path],
		headers,
		HTTPClient.METHOD_POST,
		body
	)
	if error != OK:
		transport_warning.emit("Failed to request world seed: %s" % error_string(error))


func _on_seed_definition_completed(
	_result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	var payload: Dictionary = _parse_json_dictionary(response_code, body, "seed definition") as Dictionary
	if payload.is_empty():
		return
	seed_definition_received.emit(payload)


func _on_seed_world_completed(
	_result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	var payload: Dictionary = _parse_json_dictionary(response_code, body, "world seed") as Dictionary
	if payload.is_empty():
		return
	_seed_bootstrap_attempted = true
	if _transport_mode == "websocket":
		transport_status_changed.emit("websocket", "Bootstrapped fixed seed %s." % seed_id)
		return
	_poll_timer.start()
	fetch_batch()


func _on_snapshot_completed(
	_result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	var payload: Dictionary = _parse_json_dictionary(response_code, body, "snapshot") as Dictionary
	if payload.is_empty():
		return
	_pending_snapshot = payload
	var error := _events_request.request("%s%s" % [base_url, recent_events_path])
	if error != OK:
		transport_warning.emit("Failed to request recent events: %s" % error_string(error))
		snapshot_batch_received.emit(_pending_snapshot, [])


func _on_events_completed(
	_result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	var payload: Dictionary = _parse_json_dictionary(response_code, body, "recent events") as Dictionary
	if payload.is_empty():
		snapshot_batch_received.emit(_pending_snapshot, [])
		return

	var events_value: Variant = payload.get("events", [])
	var events: Array = []
	if typeof(events_value) == TYPE_ARRAY:
		events = events_value
	snapshot_batch_received.emit(_pending_snapshot, events)


func _parse_json_dictionary(response_code: int, body: PackedByteArray, label: String) -> Dictionary:
	if response_code != 200:
		transport_warning.emit("%s request failed with status %d" % [label.capitalize(), response_code])
		return {}

	var json: JSON = JSON.new()
	var parse_error: int = json.parse(body.get_string_from_utf8())
	if parse_error != OK:
		transport_warning.emit("Failed to parse %s JSON: %s" % [label, json.get_error_message()])
		return {}

	var payload: Variant = json.data
	if typeof(payload) != TYPE_DICTIONARY:
		transport_warning.emit("%s payload was not a dictionary." % label.capitalize())
		return {}
	return payload as Dictionary


func _build_stream_url() -> String:
	var websocket_base := base_url
	if websocket_base.begins_with("https://"):
		websocket_base = websocket_base.replacen("https://", "wss://")
	elif websocket_base.begins_with("http://"):
		websocket_base = websocket_base.replacen("http://", "ws://")
	var seed_flag := "true" if seed_on_startup else "false"
	return "%s%s?seed_id=%s&seed_on_connect=%s&poll_seconds=%.2f" % [
		websocket_base,
		stream_path,
		seed_id.uri_encode(),
		seed_flag,
		stream_poll_seconds,
	]


func _stream_has_gone_stale() -> bool:
	if stale_stream_timeout_seconds <= 0.0:
		return false
	if _last_live_message_time_msec <= 0:
		return false
	var elapsed_seconds := float(Time.get_ticks_msec() - _last_live_message_time_msec) / 1000.0
	return elapsed_seconds >= stale_stream_timeout_seconds


func _connect_attempt_has_timed_out() -> bool:
	if stale_stream_timeout_seconds <= 0.0:
		return false
	if _websocket_connect_started_msec <= 0:
		return false
	var elapsed_seconds := float(Time.get_ticks_msec() - _websocket_connect_started_msec) / 1000.0
	return elapsed_seconds >= stale_stream_timeout_seconds


func _should_bootstrap_missing_seed(message: String) -> bool:
	if _seed_bootstrap_attempted:
		return false
	return message.contains("No fixed world seed is active on the backend")


func _bootstrap_missing_seed() -> void:
	_seed_bootstrap_attempted = true
	transport_status_changed.emit("connecting", "No active seed found, requesting %s..." % seed_id)
	_request_seed_world()


func _make_request(callback_name: String) -> HTTPRequest:
	var request := HTTPRequest.new()
	add_child(request)
	request.request_completed.connect(Callable(self, callback_name))
	return request
