extends RefCounted

class_name PresentationSnapshotProjector


static func project(snapshot: Dictionary) -> Dictionary:
	var projected_world := _project_world(snapshot.get("world", {}))
	var projected_agents := _project_agents(snapshot.get("agents", []))

	return {
		"tick": int(snapshot.get("tick", 0)),
		"generated_at": snapshot.get("generated_at", ""),
		"world": projected_world,
		"agents": projected_agents,
	}


static func _project_world(world_value: Variant) -> Dictionary:
	if typeof(world_value) != TYPE_DICTIONARY:
		return {
			"width": 0,
			"height": 0,
			"tiles": [],
		}

	var world: Dictionary = world_value
	var tiles_value: Variant = world.get("tiles", [])
	var projected_tiles: Array[Dictionary] = []

	if typeof(tiles_value) == TYPE_ARRAY:
		var tiles: Array = tiles_value
		for tile_value in tiles:
			if typeof(tile_value) != TYPE_DICTIONARY:
				continue

			var tile: Dictionary = tile_value
			projected_tiles.append(
				{
					"x": int(tile.get("x", 0)),
					"y": int(tile.get("y", 0)),
					"terrain": str(tile.get("terrain", "grass")),
					"walkable": bool(tile.get("walkable", true)),
				}
			)

	return {
		"width": int(world.get("width", 0)),
		"height": int(world.get("height", 0)),
		"tiles": projected_tiles,
	}


static func _project_agents(agents_value: Variant) -> Array[Dictionary]:
	var projected_agents: Array[Dictionary] = []

	if typeof(agents_value) != TYPE_ARRAY:
		return projected_agents

	var agents: Array = agents_value
	for agent_value in agents:
		if typeof(agent_value) != TYPE_DICTIONARY:
			continue

		var agent: Dictionary = agent_value
		var position_value: Variant = agent.get("position", {})
		if typeof(position_value) != TYPE_DICTIONARY:
			continue

		var position: Dictionary = position_value
		projected_agents.append(
			{
				"agent_id": str(agent.get("agent_id", "")),
				"name": str(agent.get("name", "")),
				"position": {
					"x": int(position.get("x", 0)),
					"y": int(position.get("y", 0)),
				},
				"current_action": str(agent.get("current_action", "idle")),
			}
		)

	return projected_agents
