extends PanelContainer

@onready var events_label: RichTextLabel = $Margin/VBox/Events


func bind_events(events: Array) -> void:
	var lines := PackedStringArray()
	for event_value in events:
		if typeof(event_value) != TYPE_DICTIONARY:
			continue
		var event: Dictionary = event_value
		lines.append(
			"[tick %d] %s" % [
				int(event.get("tick", 0)),
				str(event.get("event_type", "event")),
			]
		)
		if lines.size() >= 10:
			break

	events_label.text = "\n".join(lines) if lines.size() > 0 else "No recent events."
