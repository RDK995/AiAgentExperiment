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
]
const ALLOWED_AGENT_KEYS := [
	"agent_id",
	"name",
	"position",
	"needs",
	"current_action",
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
