extends PanelContainer

@onready var title_label: Label = $Margin/VBox/Title
@onready var stats_label: Label = $Margin/VBox/Stats


func bind_data(snapshot: Dictionary, seed_definition: Dictionary, events: Array, debug_metrics: Dictionary = {}) -> void:
	title_label.text = "Village Overview"

	var preferred_daily_metrics: Dictionary = {}
	var current_value: Variant = debug_metrics.get("current", {})
	if typeof(current_value) == TYPE_DICTIONARY:
		preferred_daily_metrics = current_value
	if preferred_daily_metrics.is_empty():
		var latest_value: Variant = debug_metrics.get("latest", {})
		if typeof(latest_value) == TYPE_DICTIONARY:
			preferred_daily_metrics = latest_value

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
	if not preferred_daily_metrics.is_empty():
		var population_value: Variant = preferred_daily_metrics.get("population", {})
		var welfare_value: Variant = preferred_daily_metrics.get("welfare", {})
		var social_value: Variant = preferred_daily_metrics.get("social", {})
		var economy_value: Variant = preferred_daily_metrics.get("economy", {})
		var cognition_value: Variant = preferred_daily_metrics.get("cognition", {})
		var population: Dictionary = population_value if typeof(population_value) == TYPE_DICTIONARY else {}
		var welfare: Dictionary = welfare_value if typeof(welfare_value) == TYPE_DICTIONARY else {}
		var social: Dictionary = social_value if typeof(social_value) == TYPE_DICTIONARY else {}
		var economy: Dictionary = economy_value if typeof(economy_value) == TYPE_DICTIONARY else {}
		var cognition: Dictionary = cognition_value if typeof(cognition_value) == TYPE_DICTIONARY else {}
		var age_distribution_value: Variant = population.get("age_distribution", {})
		var age_distribution: Dictionary = age_distribution_value if typeof(age_distribution_value) == TYPE_DICTIONARY else {}
		stats_label.text = "Population %d\nAdults %d   Adolescents %d   Children %d\nHouseholds %d   Active bonds %d\nAvg hunger %.1f   Avg stress %.1f\nFood %d   Water %d   Wood %d\nBirths %d   Deaths %d   Gifts %d\nMeals/day %d   Reflections/day %d" % [
			int(population.get("total_population", agents.size())),
			int(age_distribution.get("adult", adult_count)),
			int(age_distribution.get("adolescent", adolescent_count)),
			int(age_distribution.get("child", child_count)) + int(age_distribution.get("infant", 0)),
			int(social.get("household_count", households.size())),
			int(social.get("active_bonds", 0)),
			float(welfare.get("average_hunger", average_hunger)),
			float(welfare.get("average_stress", 0.0)),
			int(economy.get("food_reserves", 0)),
			int(economy.get("water_reserves", 0)),
			int(economy.get("wood_stock", 0)),
			int(population.get("births", birth_count)),
			int(population.get("deaths", death_count)),
			int(social.get("gifts_per_day", 0)),
			int(economy.get("cooked_meals_per_day", 0)),
			int(cognition.get("reflections_per_day", 0)),
		]
		return

	stats_label.text = "Population %d\nAdults %d   Adolescents %d   Children %d\nHouseholds %d   Structures %d\nAverage hunger %.1f\nRecent births %d   deaths %d" % [
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
