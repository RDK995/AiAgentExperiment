extends PanelContainer

var _selected_agent_id: String = ""

@onready var title_label: Label = $Margin/VBox/Title
@onready var summary_label: Label = $Margin/VBox/Summary
@onready var needs_label: Label = $Margin/VBox/Needs
@onready var social_label: Label = $Margin/VBox/Social


func bind_agent(agent_data: Dictionary, seed_definition: Dictionary) -> void:
	if agent_data.is_empty():
		_selected_agent_id = ""
		title_label.text = "Agent Inspector"
		summary_label.text = "Select an agent in the world to open a focused profile."
		needs_label.text = ""
		social_label.text = ""
		return

	_selected_agent_id = str(agent_data.get("agent_id", ""))
	title_label.text = "%s (%s)" % [
		str(agent_data.get("name", "Unknown")),
		str(agent_data.get("stage_of_life", "adult")),
	]
	summary_label.text = "Current action: %s\nCurrent goal: %s\nHousehold: %s" % [
		str(agent_data.get("current_action", "idle")),
		str(agent_data.get("current_goal", "n/a")),
		str(agent_data.get("household_id", "unassigned")),
	]

	var needs_value: Variant = agent_data.get("needs", {})
	if typeof(needs_value) == TYPE_DICTIONARY:
		var needs: Dictionary = needs_value
		needs_label.text = "Hunger %.1f\nThirst %.1f\nFatigue %.1f" % [
			float(needs.get("hunger", 0.0)),
			float(needs.get("thirst", 0.0)),
			float(needs.get("fatigue", 0.0)),
		]
	else:
		needs_label.text = "Needs unavailable"

	var partner_id := str(agent_data.get("partner_id", ""))
	var seed_links := _social_links_for_agent(_selected_agent_id, seed_definition)
	var social_lines := PackedStringArray()
	if not partner_id.is_empty():
		social_lines.append("Partner: %s" % partner_id)
	for link in seed_links:
		var link_note := str(link.get("note", ""))
		if link_note.is_empty():
			social_lines.append(str(link.get("kind", "link")).capitalize())
		else:
			social_lines.append("%s: %s" % [str(link.get("kind", "link")).capitalize(), link_note])
	social_label.text = "\n".join(social_lines) if social_lines.size() > 0 else "No seeded social notes for this agent yet."


func _social_links_for_agent(agent_id: String, seed_definition: Dictionary) -> Array:
	var links_value: Variant = seed_definition.get("social_links", [])
	if typeof(links_value) != TYPE_ARRAY:
		return []

	var matching_links: Array = []
	var links: Array = links_value
	for link_value in links:
		if typeof(link_value) != TYPE_DICTIONARY:
			continue
		var link: Dictionary = link_value
		var agent_ids: Array = link.get("agent_ids", [])
		if agent_id in agent_ids:
			matching_links.append(link)
	return matching_links
