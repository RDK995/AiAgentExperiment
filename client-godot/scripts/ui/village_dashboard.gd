extends PanelContainer

@onready var title_label: Label = $Margin/VBox/Title
@onready var stats_label: Label = $Margin/VBox/Stats


func bind_data(snapshot: Dictionary, seed_definition: Dictionary, events: Array) -> void:
	title_label.text = "Village Dashboard"

	var agents_value: Variant = snapshot.get("agents", [])
	var agents: Array = agents_value if typeof(agents_value) == TYPE_ARRAY else []
	var households := {}
	var adult_count := 0
	var adolescent_count := 0
	var child_count := 0
	var total_hunger := 0.0

	for agent_value in agents:
		if typeof(agent_value) != TYPE_DICTIONARY:
			continue
		var agent: Dictionary = agent_value
		var household_id := str(agent.get("household_id", ""))
		if not household_id.is_empty():
			households[household_id] = true
		match str(agent.get("stage_of_life", "adult")):
			"child":
				child_count += 1
			"adolescent":
				adolescent_count += 1
			_:
				adult_count += 1
		var needs_value: Variant = agent.get("needs", {})
		if typeof(needs_value) == TYPE_DICTIONARY:
			total_hunger += float((needs_value as Dictionary).get("hunger", 0.0))

	var birth_count := 0
	var death_count := 0
	for event_value in events:
		if typeof(event_value) != TYPE_DICTIONARY:
			continue
		var event_type := str((event_value as Dictionary).get("event_type", ""))
		if event_type == "child_born":
			birth_count += 1
		elif event_type == "agent_died" or event_type == "death":
			death_count += 1

	var structures_count := 0
	var world_value: Variant = seed_definition.get("world", {})
	if typeof(world_value) == TYPE_DICTIONARY:
		structures_count = ((world_value as Dictionary).get("structures", []) as Array).size()

	var average_hunger: float = total_hunger / max(1.0, float(agents.size()))
	stats_label.text = "Population: %d\nAdults: %d  Adolescents: %d  Children: %d\nHouseholds: %d\nStructures: %d\nAvg hunger: %.1f\nRecent births: %d  deaths: %d" % [
		agents.size(),
		adult_count,
		adolescent_count,
		child_count,
		households.size(),
		structures_count,
		average_hunger,
		birth_count,
		death_count,
	]
