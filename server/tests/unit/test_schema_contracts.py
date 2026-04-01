"""Schema validation tests for agent snapshots, world events, and reflection outputs."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.cognition.reflection import ReflectionWorkflow
from app.db.enums import GoalType, StageOfLife
from app.cognition.output_parser import ReflectionOutputParser
from app.engine.world_state import AgentState
from app.schemas.agent import AgentStateSnapshot, MoodSchema, NeedsSchema
from app.schemas.event import WorldEventSchema
from app.schemas.memory import WorldEventRecord
from app.schemas.reflection import (
    BeliefUpdate,
    GoalUpdate,
    MemoryCandidate,
    ReflectionContext,
    ReflectionOutput,
    ReflectionResult,
)


def test_agent_state_snapshot_parses_valid_payload() -> None:
    """A valid detailed agent snapshot payload should parse successfully."""

    payload = {
        "agent_id": "agent-1",
        "name": "Villager 1",
        "stage_of_life": "adult",
        "tile_x": 3,
        "tile_y": 4,
        "current_action": "gather",
        "current_goal": "Store food",
        "needs": {
            "hunger": 20.0,
            "thirst": 15.0,
            "fatigue": 25.0,
            "warmth": 80.0,
            "health": 90.0,
            "stress": 10.0,
            "loneliness": 12.0,
            "safety": 88.0,
        },
        "mood": {
            "hope": 70.0,
            "grief": 5.0,
            "morale": 75.0,
            "shame": 2.0,
        },
    }

    snapshot = AgentStateSnapshot.model_validate(payload)

    assert snapshot.stage_of_life == StageOfLife.ADULT
    assert snapshot.needs == NeedsSchema.model_validate(payload["needs"])
    assert snapshot.mood == MoodSchema.model_validate(payload["mood"])
    assert snapshot.household_id is None
    assert snapshot.partner_id is None


def test_agent_state_snapshot_requires_nested_needs_and_mood() -> None:
    """Detailed agent snapshots should require the nested need and mood contracts."""

    with pytest.raises(ValidationError):
        AgentStateSnapshot.model_validate(
            {
                "agent_id": "agent-1",
                "name": "Villager 1",
                "stage_of_life": "adult",
                "tile_x": 3,
                "tile_y": 4,
                "needs": {
                    "hunger": 20.0,
                    "thirst": 15.0,
                    "fatigue": 25.0,
                    "warmth": 80.0,
                    "health": 90.0,
                    "stress": 10.0,
                    "loneliness": 12.0,
                    "safety": 88.0,
                },
            }
        )


def test_agent_state_snapshot_rejects_invalid_nested_need_shape() -> None:
    """Detailed agent snapshots should reject malformed nested need payloads."""

    with pytest.raises(ValidationError):
        AgentStateSnapshot.model_validate(
            {
                "agent_id": "agent-1",
                "name": "Villager 1",
                "stage_of_life": "adult",
                "tile_x": 3,
                "tile_y": 4,
                "needs": {
                    "hunger": "very hungry",
                    "thirst": 15.0,
                    "fatigue": 25.0,
                    "warmth": 80.0,
                    "health": 90.0,
                    "stress": 10.0,
                    "loneliness": 12.0,
                    "safety": 88.0,
                },
                "mood": {
                    "hope": 70.0,
                    "grief": 5.0,
                    "morale": 75.0,
                    "shame": 2.0,
                },
            }
        )


def test_agent_state_snapshot_missing_required_fields_fail_validation() -> None:
    """Detailed agent snapshots should fail when required top-level fields are missing."""

    with pytest.raises(ValidationError):
        AgentStateSnapshot.model_validate(
            {
                "agent_id": "agent-1",
                "stage_of_life": "adult",
                "tile_x": 3,
                "tile_y": 4,
                "needs": {
                    "hunger": 20.0,
                    "thirst": 15.0,
                    "fatigue": 25.0,
                    "warmth": 80.0,
                    "health": 90.0,
                    "stress": 10.0,
                    "loneliness": 12.0,
                    "safety": 88.0,
                },
                "mood": {
                    "hope": 70.0,
                    "grief": 5.0,
                    "morale": 75.0,
                    "shame": 2.0,
                },
            }
        )


def test_agent_state_snapshot_rejects_extra_fields() -> None:
    """Detailed agent snapshots should remain strict about undeclared fields."""

    with pytest.raises(ValidationError):
        AgentStateSnapshot.model_validate(
            {
                "agent_id": "agent-1",
                "name": "Villager 1",
                "stage_of_life": "adult",
                "tile_x": 3,
                "tile_y": 4,
                "needs": {
                    "hunger": 20.0,
                    "thirst": 15.0,
                    "fatigue": 25.0,
                    "warmth": 80.0,
                    "health": 90.0,
                    "stress": 10.0,
                    "loneliness": 12.0,
                    "safety": 88.0,
                },
                "mood": {
                    "hope": 70.0,
                    "grief": 5.0,
                    "morale": 75.0,
                    "shame": 2.0,
                },
                "inventory": {"berries": 3},
            }
        )


def test_agent_state_snapshot_serialization_shape_is_correct() -> None:
    """Detailed agent snapshots should serialize to the expected contract shape."""

    snapshot = AgentStateSnapshot(
        agent_id="agent-1",
        name="Villager 1",
        stage_of_life=StageOfLife.ADULT,
        tile_x=1,
        tile_y=2,
        needs=NeedsSchema(
            hunger=1.0,
            thirst=2.0,
            fatigue=3.0,
            warmth=4.0,
            health=5.0,
            stress=6.0,
            loneliness=7.0,
            safety=8.0,
        ),
        mood=MoodSchema(hope=60.0, grief=10.0, morale=55.0, shame=5.0),
    )

    dumped = snapshot.model_dump(mode="json")

    assert dumped == {
        "agent_id": "agent-1",
        "name": "Villager 1",
        "stage_of_life": "adult",
        "tile_x": 1,
        "tile_y": 2,
        "current_action": None,
        "current_goal": None,
        "needs": {
            "hunger": 1.0,
            "thirst": 2.0,
            "fatigue": 3.0,
            "warmth": 4.0,
            "health": 5.0,
            "stress": 6.0,
            "loneliness": 7.0,
            "safety": 8.0,
        },
        "mood": {
            "hope": 60.0,
            "grief": 10.0,
            "morale": 55.0,
            "shame": 5.0,
        },
        "household_id": None,
        "partner_id": None,
    }


def test_world_event_schema_parses_valid_payload() -> None:
    """A valid world-event payload should parse successfully."""

    payload = {
        "event_id": "event-1",
        "tick": 22,
        "event_type": "storm_warning",
        "actor_ids": ["agent-1"],
        "target_ids": ["agent-2", "agent-3"],
        "location_x": 4,
        "location_y": 6,
        "payload": {"severity": "high"},
    }

    event = WorldEventSchema.model_validate(payload)

    assert event.actor_ids == ["agent-1"]
    assert event.target_ids == ["agent-2", "agent-3"]
    assert event.payload == {"severity": "high"}


def test_world_event_schema_defaults_optional_location_fields() -> None:
    """World-event location fields should remain optional."""

    event = WorldEventSchema.model_validate(
        {
            "event_id": "event-1",
            "tick": 22,
            "event_type": "storm_warning",
            "actor_ids": [],
            "target_ids": [],
            "payload": {},
        }
    )

    assert event.location_x is None
    assert event.location_y is None


def test_world_event_schema_missing_required_fields_fail_validation() -> None:
    """World-event DTOs should fail when required contract fields are omitted."""

    with pytest.raises(ValidationError):
        WorldEventSchema.model_validate(
            {
                "event_id": "event-1",
                "tick": 22,
                "actor_ids": [],
                "target_ids": [],
                "payload": {},
            }
        )


def test_world_event_schema_rejects_invalid_list_and_payload_types() -> None:
    """World-event DTOs should reject malformed list and payload field types."""

    with pytest.raises(ValidationError):
        WorldEventSchema.model_validate(
            {
                "event_id": "event-1",
                "tick": 22,
                "event_type": "storm_warning",
                "actor_ids": "agent-1",
                "target_ids": [],
                "payload": [],
            }
        )


def test_world_event_schema_rejects_extra_fields() -> None:
    """World-event DTOs should reject undeclared transport fields."""

    with pytest.raises(ValidationError):
        WorldEventSchema.model_validate(
            {
                "event_id": "event-1",
                "tick": 22,
                "event_type": "storm_warning",
                "actor_ids": [],
                "target_ids": [],
                "payload": {},
                "authority_only": True,
            }
        )


def test_world_event_schema_payload_round_trips_cleanly() -> None:
    """World-event payloads should serialize without shape drift."""

    event = WorldEventSchema(
        event_id="event-1",
        tick=10,
        event_type="harvest",
        actor_ids=["agent-1"],
        target_ids=[],
        payload={"yield": 12, "weather": "clear"},
    )

    assert event.model_dump(mode="json")["payload"] == {"yield": 12, "weather": "clear"}


def test_world_event_schema_from_record_integrates_with_persistence_record_schema() -> None:
    """World-event DTOs should adapt cleanly from persisted record schemas."""

    record = WorldEventRecord(
        id=uuid.uuid4(),
        tick=33,
        event_type="festival",
        actor_ids=[uuid.uuid4()],
        target_ids=[uuid.uuid4()],
        location_x=7,
        location_y=8,
        payload={"attendance": 20},
    )

    event = WorldEventSchema.from_record(record)

    assert event.event_id == str(record.id)
    assert event.actor_ids == [str(record.actor_ids[0])]
    assert event.target_ids == [str(record.target_ids[0])]
    assert event.payload == {"attendance": 20}


def test_reflection_output_parses_valid_nested_payload() -> None:
    """A valid reflection output payload should parse all nested structures."""

    payload = {
        "summary": "The day went well overall.",
        "mood_delta": {"hope": 2.5, "morale": 1.0},
        "belief_updates": [
            {
                "subject_type": "agent",
                "subject_id": "agent-2",
                "predicate": "is_reliable",
                "object_value": "yes",
                "confidence_delta": 0.2,
            }
        ],
        "goal_updates": [
            {
                "action": "create",
                "goal_type": "safety",
                "title": "Repair the fence",
                "priority": 1.5,
                "horizon_days": 2,
            }
        ],
        "memory_candidates": [
            {
                "text": "Worked together during the storm.",
                "salience": 0.9,
                "valence": 0.4,
            }
        ],
        "tomorrow_intentions": ["Check the fence", "Speak with neighbors"],
    }

    output = ReflectionOutput.model_validate(payload)

    assert output.belief_updates == [BeliefUpdate.model_validate(payload["belief_updates"][0])]
    assert output.goal_updates == [GoalUpdate.model_validate(payload["goal_updates"][0])]
    assert output.memory_candidates == [MemoryCandidate.model_validate(payload["memory_candidates"][0])]
    assert output.goal_updates[0].goal_type == GoalType.SAFETY


def test_reflection_output_rejects_invalid_nested_shapes() -> None:
    """Invalid nested reflection payloads should fail validation."""

    with pytest.raises(ValidationError):
        ReflectionOutput.model_validate(
            {
                "summary": "Bad payload",
                "mood_delta": {"hope": 2.5},
                "belief_updates": [
                    {
                        "subject_type": "agent",
                        "predicate": "is_reliable",
                        "object_value": "yes",
                        "confidence_delta": 4.0,
                    }
                ],
                "goal_updates": [],
                "memory_candidates": [],
                "tomorrow_intentions": [],
            }
        )


def test_reflection_output_rejects_invalid_goal_action_and_mood_delta_shape() -> None:
    """Reflection output should reject invalid goal actions and malformed mood deltas."""

    with pytest.raises(ValidationError):
        ReflectionOutput.model_validate(
            {
                "summary": "Bad payload",
                "mood_delta": ["hope", 1.0],
                "belief_updates": [],
                "goal_updates": [
                    {
                        "action": "postpone",
                        "goal_type": "safety",
                        "title": "Repair the fence",
                        "priority": 1.0,
                        "horizon_days": 2,
                    }
                ],
                "memory_candidates": [],
                "tomorrow_intentions": [],
            }
        )


def test_reflection_output_rejects_extra_top_level_and_nested_fields() -> None:
    """Reflection DTOs should stay strict at both top-level and nested shapes."""

    with pytest.raises(ValidationError):
        ReflectionOutput.model_validate(
            {
                "summary": "Bad payload",
                "mood_delta": {"hope": 1.0},
                "belief_updates": [
                    {
                        "subject_type": "agent",
                        "predicate": "is_reliable",
                        "object_value": "yes",
                        "confidence_delta": 0.2,
                        "evidence": ["unexpected"],
                    }
                ],
                "goal_updates": [],
                "memory_candidates": [],
                "tomorrow_intentions": [],
                "planner_state": "forbidden",
            }
        )


def test_goal_update_rejects_invalid_priority_and_horizon() -> None:
    """Goal updates should reject invalid bounded numeric fields."""

    with pytest.raises(ValidationError):
        GoalUpdate.model_validate(
            {
                "action": "create",
                "goal_type": "family",
                "title": "Check on the household",
                "priority": -0.1,
                "horizon_days": -1,
            }
        )


def test_reflection_output_round_trips_through_dump_and_validate() -> None:
    """Reflection DTOs should remain stable across dump/validate round-trips."""

    original = ReflectionOutput(
        summary="A steady day with small wins.",
        mood_delta={"hope": 1.0, "morale": 0.25},
        belief_updates=[
            BeliefUpdate(
                subject_type="agent",
                subject_id="agent-4",
                predicate="is_helpful",
                object_value="likely",
                confidence_delta=0.15,
            )
        ],
        goal_updates=[
            GoalUpdate(
                action="create",
                goal_type=GoalType.FAMILY,
                title="Check on the household",
                priority=1.2,
                horizon_days=1,
            )
        ],
        memory_candidates=[
            MemoryCandidate(
                text="Shared a meal with neighbors.",
                salience=0.6,
                valence=0.4,
            )
        ],
        tomorrow_intentions=["Visit the granary"],
    )

    round_tripped = ReflectionOutput.model_validate(original.model_dump(mode="json"))

    assert round_tripped == original


def test_reflection_output_serialization_shape_is_correct() -> None:
    """Reflection output DTOs should serialize to the expected nested shape."""

    output = ReflectionOutput(
        summary="Plan for tomorrow is clearer.",
        mood_delta={"hope": 1.0, "morale": 0.5},
        belief_updates=[
            BeliefUpdate(
                subject_type="resource",
                predicate="located_at",
                object_value="river",
                confidence_delta=0.1,
            )
        ],
        goal_updates=[
            GoalUpdate(
                action="reprioritize",
                goal_type=GoalType.EXPLORATION,
                title="Search the western ridge",
                priority=2.0,
                horizon_days=3,
            )
        ],
        memory_candidates=[
            MemoryCandidate(
                text="Saw unusual tracks near the river.",
                salience=0.8,
                valence=-0.1,
            )
        ],
        tomorrow_intentions=["Visit the ridge"],
    )

    dumped = output.model_dump(mode="json")

    assert dumped["goal_updates"][0]["goal_type"] == "exploration"
    assert dumped["belief_updates"][0]["confidence_delta"] == 0.1
    assert dumped["memory_candidates"][0]["salience"] == 0.8
    assert dumped["tomorrow_intentions"] == ["Visit the ridge"]


def test_reflection_output_converts_to_legacy_reflection_result() -> None:
    """Structured reflection output should adapt into the current slow-loop contract."""

    output = ReflectionOutput(
        summary="Tomorrow needs a clearer plan.",
        mood_delta={"hope": 1.5},
        belief_updates=[
            BeliefUpdate(
                subject_type="agent",
                subject_id="agent-2",
                predicate="is_reliable",
                object_value="yes",
                confidence_delta=0.2,
            ),
            BeliefUpdate(
                subject_type="resource",
                predicate="located_at",
                object_value="river",
                confidence_delta=0.1,
            ),
        ],
        goal_updates=[
            GoalUpdate(
                action="create",
                goal_type=GoalType.SAFETY,
                title="Repair the fence",
                priority=1.0,
                horizon_days=2,
            )
        ],
        memory_candidates=[
            MemoryCandidate(
                text="Worked together during the storm.",
                salience=0.8,
                valence=0.3,
            )
        ],
        tomorrow_intentions=["Check the fence", "Talk to neighbors"],
    )

    result = output.to_reflection_result()

    assert result == ReflectionResult(
        goals=["Repair the fence"],
        beliefs=[
            "agent:agent-2:is_reliable:yes",
            "resource:located_at:river",
        ],
        memory_entries=["Worked together during the storm."],
        planner_hints=["Check the fence", "Talk to neighbors"],
    )


def test_reflection_output_parser_accepts_structured_and_legacy_outputs() -> None:
    """The parser should pass through legacy results and adapt structured outputs."""

    parser = ReflectionOutputParser()
    legacy = ReflectionResult(
        goals=["Keep the hearth lit"],
        beliefs=["resource:located_at:forest"],
        memory_entries=["Collected firewood before sunset."],
        planner_hints=["Gather more wood"],
    )
    structured = ReflectionOutput(
        summary="Tomorrow should focus on safety.",
        goal_updates=[
            GoalUpdate(
                action="create",
                goal_type=GoalType.SAFETY,
                title="Secure the workshop",
                priority=2.0,
                horizon_days=1,
            )
        ],
        memory_candidates=[
            MemoryCandidate(
                text="The workshop door was left open.",
                salience=0.9,
                valence=-0.2,
            )
        ],
        tomorrow_intentions=["Inspect the workshop"],
    )

    assert parser.parse(legacy) is legacy
    assert parser.parse(structured) == ReflectionResult(
        goals=["Secure the workshop"],
        beliefs=[],
        memory_entries=["The workshop door was left open."],
        planner_hints=["Inspect the workshop"],
    )


def test_reflection_workflow_routes_structured_output_through_parser() -> None:
    """The default reflection workflow should use the structured DTO path internally."""

    workflow = ReflectionWorkflow()
    agent = AgentState(agent_id="agent-1", name="Villager 1", x=1, y=2)
    context = ReflectionContext(
        agent_id="agent-1",
        trigger_reasons=["major_life_event"],
        autobiography="A difficult day with a strong ending.",
        recent_events=["storm", "community support"],
    )

    result = workflow.run(agent, context)

    assert result == ReflectionResult(
        goals=["Support village stability for Villager 1"],
        beliefs=["agent:agent-1:can_improve_outcomes_by_adapting_routines:yes"],
        memory_entries=["A difficult day with a strong ending."],
        planner_hints=["keep_routine"],
    )


def test_reflection_context_and_result_reject_extra_fields() -> None:
    """Reflection workflow input/output contracts should reject undeclared fields."""

    with pytest.raises(ValidationError):
        ReflectionContext.model_validate(
            {
                "agent_id": "agent-1",
                "trigger_reasons": ["major_life_event"],
                "autobiography": "A day in the village.",
                "recent_events": ["storm"],
                "beliefs": ["forbidden"],
            }
        )

    with pytest.raises(ValidationError):
        ReflectionResult.model_validate(
            {
                "goals": ["Support village stability"],
                "beliefs": ["agent:agent-1:is_reliable:yes"],
                "memory_entries": ["A strong memory."],
                "planner_hints": ["keep_routine"],
                "summary": "forbidden",
            }
        )
