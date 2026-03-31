extends Node

signal snapshot_received(snapshot: Dictionary)
signal request_failed(error_message: String)

@export var base_url: String = "http://127.0.0.1:8000"
@export var snapshot_path: String = "/api/v1/world/snapshot"
@export var poll_interval_seconds: float = 1.0

var _http_request: HTTPRequest
var _poll_timer: Timer


func _ready() -> void:
	_http_request = HTTPRequest.new()
	add_child(_http_request)
	_http_request.request_completed.connect(_on_request_completed)

	_poll_timer = Timer.new()
	_poll_timer.wait_time = poll_interval_seconds
	_poll_timer.autostart = true
	_poll_timer.one_shot = false
	_poll_timer.timeout.connect(fetch_snapshot)
	add_child(_poll_timer)

	fetch_snapshot()


func fetch_snapshot() -> void:
	var error := _http_request.request("%s%s" % [base_url, snapshot_path])
	if error != OK:
		request_failed.emit("Failed to start snapshot request: %s" % error_string(error))


func _on_request_completed(
	_result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray
) -> void:
	if response_code != 200:
		request_failed.emit("Snapshot request failed with status %d" % response_code)
		return

	var json := JSON.new()
	var parse_error := json.parse(body.get_string_from_utf8())
	if parse_error != OK:
		request_failed.emit("Failed to parse snapshot JSON: %s" % json.get_error_message())
		return

	var payload: Variant = json.data
	if typeof(payload) != TYPE_DICTIONARY:
		request_failed.emit("Snapshot payload was not a dictionary.")
		return

	snapshot_received.emit(payload as Dictionary)
