extends RefCounted

class_name PresentationBoundaryValidator

const ALLOWED_SNAPSHOT_KEYS := [
	"tick",
	"world",
	"agents",
	"generated_at",
]
const ALLOWED_WORLD_KEYS := [
	"width",
	"height",
	"tiles",
	"structures",
	"markers",
]
const ALLOWED_AGENT_KEYS := [
	"agent_id",
	"name",
	"position",
	"needs",
	"current_action",
	"stage_of_life",
	"household_id",
	"partner_id",
	"current_goal",
]
const FORBIDDEN_SNAPSHOT_KEYS := [
	"inventories",
	"memory",
	"memories",
	"relationships",
	"pregnancies",
	"cognition",
]
const FORBIDDEN_AGENT_KEYS := [
	"inventory",
	"inventories",
	"memory",
	"memories",
	"relationship",
	"relationships",
	"pregnancy",
	"pregnancies",
	"cognition",
	"beliefs",
	"goals"
]


static func validate_snapshot(snapshot: Dictionary) -> PackedStringArray:
	var errors := PackedStringArray()

	for key in snapshot.keys():
		var key_string := str(key)
		if key_string in FORBIDDEN_SNAPSHOT_KEYS:
			errors.append("Snapshot contains forbidden authoritative field '%s'." % key_string)
		elif not key_string in ALLOWED_SNAPSHOT_KEYS:
			errors.append("Snapshot contains unsupported client-facing field '%s'." % key_string)

	if not snapshot.has("world"):
		errors.append("Snapshot is missing 'world'.")
	if not snapshot.has("agents"):
		errors.append("Snapshot is missing 'agents'.")

	var world_value: Variant = snapshot.get("world", {})
	if typeof(world_value) != TYPE_DICTIONARY:
		errors.append("'world' must be a dictionary.")
	else:
		var world: Dictionary = world_value
		for key in world.keys():
			var key_string := str(key)
			if not key_string in ALLOWED_WORLD_KEYS:
				errors.append("World contains unsupported client-facing field '%s'." % key_string)
		if typeof(world.get("tiles", [])) != TYPE_ARRAY:
			errors.append("'world.tiles' must be an array.")

	var agents_value: Variant = snapshot.get("agents", [])
	if typeof(agents_value) != TYPE_ARRAY:
		errors.append("'agents' must be an array.")
	else:
		var agents: Array = agents_value
		for index in range(agents.size()):
			var agent_value: Variant = agents[index]
			if typeof(agent_value) != TYPE_DICTIONARY:
				errors.append("Agent entry %d must be a dictionary." % index)
				continue

			var agent: Dictionary = agent_value
			for key in agent.keys():
				var key_string := str(key)
				if not key_string in ALLOWED_AGENT_KEYS and not key_string in FORBIDDEN_AGENT_KEYS:
					errors.append(
						"Agent entry %d contains unsupported client-facing field '%s'." % [
							index,
							key_string,
						]
					)
			for forbidden_key in FORBIDDEN_AGENT_KEYS:
				if agent.has(forbidden_key):
					errors.append(
						"Agent entry %d contains forbidden authoritative field '%s'." % [
							index,
							forbidden_key,
						]
					)

			var position_value: Variant = agent.get("position", {})
			if typeof(position_value) != TYPE_DICTIONARY:
				errors.append("Agent entry %d is missing a valid 'position'." % index)

	return errors


static func validate_seed_definition(seed_definition: Dictionary) -> PackedStringArray:
	var errors := PackedStringArray()
	var allowed_seed_keys := ["seed_id", "world", "agents", "households", "social_links"]

	for key in seed_definition.keys():
		var key_string := str(key)
		if not key_string in allowed_seed_keys:
			errors.append("Seed definition contains unsupported field '%s'." % key_string)

	var world_value: Variant = seed_definition.get("world", {})
	if typeof(world_value) != TYPE_DICTIONARY:
		errors.append("Seed definition is missing a valid 'world' block.")
	else:
		var world: Dictionary = world_value
		if typeof(world.get("tiles", [])) != TYPE_ARRAY:
			errors.append("Seed world must provide 'tiles' as an array.")
		if typeof(world.get("structures", [])) != TYPE_ARRAY:
			errors.append("Seed world must provide 'structures' as an array.")
		if typeof(world.get("markers", [])) != TYPE_ARRAY:
			errors.append("Seed world must provide 'markers' as an array.")

	var agents_value: Variant = seed_definition.get("agents", [])
	if typeof(agents_value) != TYPE_ARRAY:
		errors.append("Seed definition 'agents' must be an array.")

	var households_value: Variant = seed_definition.get("households", [])
	if typeof(households_value) != TYPE_ARRAY:
		errors.append("Seed definition 'households' must be an array.")

	var social_links_value: Variant = seed_definition.get("social_links", [])
	if typeof(social_links_value) != TYPE_ARRAY:
		errors.append("Seed definition 'social_links' must be an array.")

	return errors


static func validate_stream_envelope(envelope: Dictionary) -> PackedStringArray:
	var errors := PackedStringArray()
	var message_type := str(envelope.get("message_type", ""))
	if message_type.is_empty():
		errors.append("Stream envelope is missing 'message_type'.")
		return errors

	match message_type:
		"seed_definition":
			var seed_definition_value: Variant = envelope.get("seed_definition", {})
			if typeof(seed_definition_value) != TYPE_DICTIONARY:
				errors.append("Seed-definition envelope must provide 'seed_definition'.")
			else:
				errors.append_array(validate_seed_definition(seed_definition_value))
		"snapshot_batch":
			var batch_value: Variant = envelope.get("snapshot_batch", {})
			if typeof(batch_value) != TYPE_DICTIONARY:
				errors.append("Snapshot-batch envelope must provide 'snapshot_batch'.")
			else:
				var batch: Dictionary = batch_value
				var snapshot_value: Variant = batch.get("snapshot", {})
				var events_value: Variant = batch.get("events", [])
				if typeof(snapshot_value) != TYPE_DICTIONARY:
					errors.append("Snapshot batch must include a valid 'snapshot'.")
				else:
					errors.append_array(validate_snapshot(snapshot_value))
				if typeof(events_value) != TYPE_ARRAY:
					errors.append("Snapshot batch must include 'events' as an array.")
		"warning":
			if str(envelope.get("warning", "")).is_empty():
				errors.append("Warning envelope must provide 'warning'.")
		_:
			errors.append("Unsupported stream envelope type '%s'." % message_type)

	return errors
