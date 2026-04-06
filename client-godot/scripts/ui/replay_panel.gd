extends PanelContainer

@onready var events_label: RichTextLabel = $Margin/VBox/Events


func bind_events(events: Array) -> void:
	var lines := PackedStringArray()
	for event_value in events:
		if typeof(event_value) != TYPE_DICTIONARY:
			continue
		var event: Dictionary = event_value
		var event_type := str(event.get("event_type", "event")).replace("_", " ")
		lines.append("Tick %d   %s" % [int(event.get("tick", 0)), event_type.capitalize()])
		if lines.size() >= 10:
			break

	events_label.text = "\n".join(lines) if lines.size() > 0 else "No recent village events yet."
