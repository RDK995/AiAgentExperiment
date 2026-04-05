"""Focused tests for staged reflection workflow execution and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid

import pytest

from app.cognition.belief_updater import BeliefUpdater
from app.cognition.goal_updater import GoalUpdater
from app.cognition.output_parser import ReflectionOutputParser, ReflectionParseError
from app.cognition.prompt_builder import ReflectionPromptBuilder
from app.cognition.reflection import ReflectionWorkflow
from app.cognition.validation import ReflectionValidationError, ReflectionValidator
from app.db.enums import StageOfLife
from app.engine.world_state import AgentState, ResourceNodeState, WorldState
from app.memory.writer import MemoryWriter
from app.schemas.reflection import ReflectionContext, ReflectionOutput


@dataclass(slots=True)
class RecordingLLMClient:
    """Capture prompts while returning a predetermined model output."""

    output: str
    prompts: list[str] = field(default_factory=list)

    def generate(self, prompt: str, **_: object) -> str:
        self.prompts.append(prompt)
        return self.output


class ExplodingMemoryWriter(MemoryWriter):
    """Force persistence failure after validation succeeds."""

    def write(self, agent: AgentState, memory_entries: list[str]) -> None:
        raise RuntimeError("boom")


class ExplodingLLMClient:
    """Force model adapter failure before parsing or persistence."""

    def generate(self, prompt: str, **_: object) -> str:
        raise RuntimeError("model offline")


def _agent() -> AgentState:
    return AgentState(
        agent_id="agent-1",
        name="Ari",
        x=1,
        y=2,
        hunger=91.0,
        health=50.0,
        stage_of_life=StageOfLife.ADULT,
        partner_id="agent-2",
    )


def _world() -> WorldState:
    return WorldState(
        width=3,
        height=3,
        agents=[
            _agent(),
            AgentState(agent_id="agent-2", name="Bea", x=2, y=2),
        ],
        resources=[ResourceNodeState(resource_type="berries", x=1, y=1, quantity=3)],
    )


def _context() -> ReflectionContext:
    return ReflectionContext(
        agent_id="agent-1",
        trigger_reasons=["severe_hunger_or_injury"],
        autobiography="Ari has kept calm under pressure.",
        recent_events=["agent-2 gave me berries.", "The granary was low."],
        goals=["Store grain before winter"],
        relationships=["agent-2"],
    )


def test_reflection_workflow_executes_stages_in_order_and_persists_valid_output() -> None:
    """A valid run should complete the full staged workflow and mutate only allowed state."""

    client = RecordingLLMClient(
        ReflectionOutput(
            summary="Ari should focus on recovery.",
            mood_delta={"morale": 1.0},
            belief_updates=[
                {
                    "subject_type": "agent",
                    "subject_id": "agent-1",
                    "predicate": "can_improve_outcomes_by_adapting_routines",
                    "object_value": "yes",
                    "confidence_delta": 0.2,
                }
            ],
            goal_updates=[
                {
                    "action": "create",
                    "goal_type": "safety",
                    "title": "Recover before taking risks",
                    "priority": 0.9,
                    "horizon_days": 1,
                }
            ],
            memory_candidates=[{"text": "agent-2 gave me berries.", "salience": 0.9, "valence": 0.2}],
            tomorrow_intentions=["keep_routine"],
        ).model_dump_json()
    )
    workflow = ReflectionWorkflow(llm_client=client)
    world = _world()
    agent = world.agents[0]

    execution = workflow.execute(
        agent,
        world,
        _context(),
        validator=ReflectionValidator(),
        goal_updater=GoalUpdater(),
        belief_updater=BeliefUpdater(),
        memory_writer=MemoryWriter(),
    )

    assert execution.success is True
    assert execution.completed_stages == [
        "load_state",
        "retrieve_context",
        "build_prompt",
        "call_model",
        "parse_json",
        "validate",
        "persist_updates",
        "emit_planner_hints",
    ]
    assert execution.failure_stage is None
    assert "Agent:\nAri, adult" in client.prompts[0]
    assert "Current goals:\nStore grain before winter" in client.prompts[0]
    assert "Important relationships:\nagent-2" in client.prompts[0]
    assert "Relevant memories:\nagent-2 gave me berries. | The granary was low." in client.prompts[0]
    assert agent.current_goal == "Recover before taking risks"
    assert agent.beliefs == ["agent:agent-1:can_improve_outcomes_by_adapting_routines:yes"]
    assert agent.memories[-1] == "agent-2 gave me berries."
    assert agent.pending_planner_hints == ["keep_routine"]


def test_reflection_workflow_rejects_malformed_json_before_persistence() -> None:
    """Malformed model output should fail at parse_json with no state mutation."""

    workflow = ReflectionWorkflow(llm_client=RecordingLLMClient("{not-json"))
    world = _world()
    agent = world.agents[0]

    execution = workflow.execute(
        agent,
        world,
        _context(),
        validator=ReflectionValidator(),
        goal_updater=GoalUpdater(),
        belief_updater=BeliefUpdater(),
        memory_writer=MemoryWriter(),
    )

    assert execution.success is False
    assert execution.failure_stage == "parse_json"
    assert agent.pending_planner_hints == []
    assert agent.memories == []


def test_reflection_prompt_builder_includes_expected_sections_compactly_and_deterministically() -> None:
    """Agent-facing prompt construction should be stable and avoid uncontrolled dumps."""

    agent = _agent()
    prompt = ReflectionPromptBuilder().build_for_agent(
        agent,
        ReflectionContext(
            agent_id="agent-1",
            trigger_reasons=["day_rollover"],
            autobiography="Ari stayed focused through a difficult harvest.",
            recent_events=[
                "agent-2 gave me berries.",
                "The granary was low.",
                "A child was born.",
                "The roof leaked.",
                "The field recovered.",
                "This should be trimmed.",
            ],
            goals=["Store grain before winter", "Repair the roof", "Visit partner", "Extra goal"],
            relationships=["agent-2", "agent-3", "agent-4", "agent-5", "agent-6", "agent-7"],
        ),
    )

    assert prompt == ReflectionPromptBuilder().build_for_agent(
        agent,
        ReflectionContext(
            agent_id="agent-1",
            trigger_reasons=["day_rollover"],
            autobiography="Ari stayed focused through a difficult harvest.",
            recent_events=[
                "agent-2 gave me berries.",
                "The granary was low.",
                "A child was born.",
                "The roof leaked.",
                "The field recovered.",
                "This should be trimmed.",
            ],
            goals=["Store grain before winter", "Repair the roof", "Visit partner", "Extra goal"],
            relationships=["agent-2", "agent-3", "agent-4", "agent-5", "agent-6", "agent-7"],
        ),
    )
    assert "Rules:\n- Do not invent impossible world facts." in prompt
    assert "Output valid JSON only." in prompt
    assert "Agent:\nAri, adult" in prompt
    assert "Current needs:\nhunger=91.0, thirst=0.0, fatigue=0.0, health=50.0, stress=0.0, morale=50.0" in prompt
    assert "Current goals:\nStore grain before winter, Repair the roof, Visit partner" in prompt
    assert "Extra goal" not in prompt
    assert "Important relationships:\nagent-2, agent-3, agent-4, agent-5, agent-6" in prompt
    assert "agent-7" not in prompt
    assert "Relevant memories:\nagent-2 gave me berries. | The granary was low. | A child was born. | The roof leaked. | The field recovered." in prompt
    assert "This should be trimmed." not in prompt
    assert "Autobiographical summary:\nAri stayed focused through a difficult harvest." in prompt


def test_reflection_validator_rejects_kinship_changes_invented_entities_and_bad_hints() -> None:
    """Validation should block unsafe reflection changes before they reach persistence."""

    validator = ReflectionValidator()
    world = _world()
    agent = world.agents[0]

    with pytest.raises(ReflectionValidationError, match="kinship"):
        validator.validate_output(
            ReflectionOutput.model_validate(
                {
                    "summary": "bad",
                    "mood_delta": {},
                    "belief_updates": [
                        {
                            "subject_type": "agent",
                            "subject_id": "agent-1",
                            "predicate": "is_parent_of",
                            "object_value": "agent-2",
                            "confidence_delta": 0.1,
                        }
                    ],
                    "goal_updates": [
                        {
                            "action": "create",
                            "goal_type": "family",
                            "title": "Keep family safe",
                            "priority": 0.8,
                            "horizon_days": 1,
                        }
                    ],
                    "memory_candidates": [{"text": "bad", "salience": 0.5, "valence": 0.0}],
                    "tomorrow_intentions": ["keep_routine"],
                }
            ),
            agent=agent,
            world=world,
        )

    with pytest.raises(ReflectionValidationError, match="unknown resource"):
        validator.validate_output(
            ReflectionOutput.model_validate(
                {
                    "summary": "bad",
                    "mood_delta": {},
                    "belief_updates": [
                        {
                            "subject_type": "resource",
                            "predicate": "is_scarce",
                            "object_value": "gold",
                            "confidence_delta": 0.1,
                        }
                    ],
                    "goal_updates": [
                        {
                            "action": "create",
                            "goal_type": "wealth",
                            "title": "Gather food",
                            "priority": 0.7,
                            "horizon_days": 1,
                        }
                    ],
                    "memory_candidates": [{"text": "bad", "salience": 0.5, "valence": 0.0}],
                    "tomorrow_intentions": ["build_tower"],
                }
            ),
            agent=agent,
            world=world,
        )


def test_reflection_validator_rejects_out_of_bounds_mood_and_goal_priority() -> None:
    """Numeric bounds should be enforced before persistence is attempted."""

    validator = ReflectionValidator()
    world = _world()
    agent = world.agents[0]

    with pytest.raises(ReflectionValidationError, match="out of bounds"):
        validator.validate_output(
            ReflectionOutput.model_validate(
                {
                    "summary": "bad",
                    "mood_delta": {"morale": 11.0},
                    "belief_updates": [],
                    "goal_updates": [
                        {
                            "action": "create",
                            "goal_type": "family",
                            "title": "Stay safe",
                            "priority": 0.5,
                            "horizon_days": 1,
                        }
                    ],
                    "memory_candidates": [{"text": "bad", "salience": 0.5, "valence": 0.0}],
                    "tomorrow_intentions": ["keep_routine"],
                }
            ),
            agent=agent,
            world=world,
        )

    with pytest.raises(ReflectionValidationError, match="priority"):
        validator.validate_output(
            ReflectionOutput.model_validate(
                {
                    "summary": "bad",
                    "mood_delta": {},
                    "belief_updates": [],
                    "goal_updates": [
                        {
                            "action": "create",
                            "goal_type": "family",
                            "title": "Stay safe",
                            "priority": 1.2,
                            "horizon_days": 1,
                        }
                    ],
                    "memory_candidates": [{"text": "bad", "salience": 0.5, "valence": 0.0}],
                    "tomorrow_intentions": ["keep_routine"],
                }
            ),
            agent=agent,
            world=world,
        )

    with pytest.raises(ReflectionValidationError, match="Too many goal updates"):
        validator.validate_output(
            ReflectionOutput.model_validate(
                {
                    "summary": "busy",
                    "mood_delta": {},
                    "belief_updates": [],
                    "goal_updates": [
                        {"action": "create", "goal_type": "family", "title": "one", "priority": 0.2, "horizon_days": 1},
                        {"action": "create", "goal_type": "family", "title": "two", "priority": 0.3, "horizon_days": 1},
                        {"action": "create", "goal_type": "family", "title": "three", "priority": 0.4, "horizon_days": 1},
                        {"action": "create", "goal_type": "family", "title": "four", "priority": 0.5, "horizon_days": 1},
                    ],
                    "memory_candidates": [{"text": "busy", "salience": 0.5, "valence": 0.0}],
                    "tomorrow_intentions": ["keep_routine"],
                }
            ),
            agent=agent,
            world=world,
        )


def test_reflection_workflow_rolls_back_and_emits_no_hints_when_persistence_fails() -> None:
    """Persistence failure should prevent planner hints and restore prior agent state."""

    workflow = ReflectionWorkflow()
    world = _world()
    agent = world.agents[0]

    execution = workflow.execute(
        agent,
        world,
        _context(),
        validator=ReflectionValidator(),
        goal_updater=GoalUpdater(),
        belief_updater=BeliefUpdater(),
        memory_writer=ExplodingMemoryWriter(),
    )

    assert execution.success is False
    assert execution.failure_stage == "persist_updates"
    assert agent.current_goal == "Maintain daily routine"
    assert agent.beliefs == []
    assert agent.memories == []
    assert agent.pending_planner_hints == []


def test_reflection_output_parser_rejects_malformed_json_cleanly() -> None:
    """The JSON parsing layer should fail loudly on malformed model output."""

    with pytest.raises(ReflectionParseError):
        ReflectionOutputParser().parse_output("{not-json")


def test_reflection_output_parser_accepts_valid_structured_json() -> None:
    """Well-formed model JSON should parse into the structured reflection DTO."""

    parsed = ReflectionOutputParser().parse_output(
        ReflectionOutput(
            summary="Ari should recover steadily.",
            mood_delta={"morale": 1.0},
            belief_updates=[
                {
                    "subject_type": "agent",
                    "subject_id": "agent-1",
                    "predicate": "can_improve_outcomes_by_adapting_routines",
                    "object_value": "yes",
                    "confidence_delta": 0.2,
                }
            ],
            goal_updates=[
                {
                    "action": "create",
                    "goal_type": "safety",
                    "title": "Recover before taking risks",
                    "priority": 0.9,
                    "horizon_days": 1,
                }
            ],
            memory_candidates=[{"text": "agent-2 gave me berries.", "salience": 0.9, "valence": 0.2}],
            tomorrow_intentions=["keep_routine"],
        ).model_dump_json()
    )

    assert parsed.summary == "Ari should recover steadily."
    assert parsed.mood_delta == {"morale": 1.0}
    assert parsed.goal_updates[0].title == "Recover before taking risks"
    assert parsed.memory_candidates[0].text == "agent-2 gave me berries."
    assert parsed.tomorrow_intentions == ["keep_routine"]


def test_reflection_output_parser_rejects_structurally_invalid_json_cleanly() -> None:
    """Schema-invalid JSON should fail at the parsing layer before validation."""

    with pytest.raises(ReflectionParseError):
        ReflectionOutputParser().parse_output(
            '{"summary": "invalid", "memory_candidates": [{"text": "oops", "salience": 2.0, "valence": 0.0}]}'
        )


def test_reflection_validator_accepts_valid_constrained_output() -> None:
    """A bounded output that references only known state should pass validation unchanged."""

    validator = ReflectionValidator()
    world = _world()
    agent = world.agents[0]

    output = ReflectionOutput.model_validate(
        {
            "summary": "good",
            "mood_delta": {"morale": 2.0, "grief": -1.0},
            "belief_updates": [
                {
                    "subject_type": "agent",
                    "subject_id": "agent-2",
                    "predicate": "is_part_of_my_support_network",
                    "object_value": "yes",
                    "confidence_delta": 0.2,
                },
                {
                    "subject_type": "resource",
                    "predicate": "is_scarce",
                    "object_value": "berries",
                    "confidence_delta": 0.1,
                },
            ],
            "goal_updates": [
                {
                    "action": "create",
                    "goal_type": "safety",
                    "title": "Recover before taking risks",
                    "priority": 0.8,
                    "horizon_days": 1,
                }
            ],
            "memory_candidates": [{"text": "agent-2 helped me recover.", "salience": 0.7, "valence": 0.3}],
            "tomorrow_intentions": ["visit_partner"],
        }
    )

    assert validator.validate_output(output, agent=agent, world=world) is output


def test_reflection_validator_accepts_persistent_uuid_agent_subject_ids() -> None:
    """Persistence-backed relationship ids should be accepted as valid agent belief subjects."""

    validator = ReflectionValidator()
    world = _world()
    agent = world.agents[0]
    persistent_related_id = str(uuid.uuid4())

    output = ReflectionOutput.model_validate(
        {
            "summary": "good",
            "mood_delta": {},
            "belief_updates": [
                {
                    "subject_type": "agent",
                    "subject_id": persistent_related_id,
                    "predicate": "is_part_of_my_support_network",
                    "object_value": "yes",
                    "confidence_delta": 0.15,
                }
            ],
            "goal_updates": [
                {
                    "action": "create",
                    "goal_type": "safety",
                    "title": "Recover before taking risks",
                    "priority": 0.8,
                    "horizon_days": 1,
                }
            ],
            "memory_candidates": [{"text": "agent-2 helped me recover.", "salience": 0.7, "valence": 0.3}],
            "tomorrow_intentions": ["keep_routine"],
        }
    )

    assert validator.validate_output(output, agent=agent, world=world) is output


def test_reflection_validator_accepts_existing_fast_loop_planner_hints() -> None:
    """Reflection validation should stay compatible with fast-loop hint literals still in use."""

    validator = ReflectionValidator()
    world = _world()
    agent = world.agents[0]

    output = ReflectionOutput.model_validate(
        {
            "summary": "good",
            "mood_delta": {},
            "belief_updates": [
                {
                    "subject_type": "agent",
                    "subject_id": "agent-1",
                    "predicate": "can_improve_outcomes_by_adapting_routines",
                    "object_value": "yes",
                    "confidence_delta": 0.1,
                }
            ],
            "goal_updates": [
                {
                    "action": "create",
                    "goal_type": "safety",
                    "title": "Recover before taking risks",
                    "priority": 0.8,
                    "horizon_days": 1,
                }
            ],
            "memory_candidates": [{"text": "I should recover.", "salience": 0.7, "valence": 0.1}],
            "tomorrow_intentions": ["eat_soon", "drink_soon"],
        }
    )

    assert validator.validate_output(output, agent=agent, world=world) is output


def test_reflection_validator_rejects_context_incompatible_planner_hints() -> None:
    """Planner hints that require missing context should be rejected explicitly."""

    validator = ReflectionValidator()

    partnerless_world = _world()
    partnerless_agent = partnerless_world.agents[0]
    partnerless_agent.partner_id = None
    with pytest.raises(ReflectionValidationError, match="current partner"):
        validator.validate_output(
            ReflectionOutput.model_validate(
                {
                    "summary": "bad",
                    "mood_delta": {},
                    "belief_updates": [],
                    "goal_updates": [
                        {
                            "action": "create",
                            "goal_type": "safety",
                            "title": "Recover",
                            "priority": 0.6,
                            "horizon_days": 1,
                        }
                    ],
                    "memory_candidates": [{"text": "bad", "salience": 0.5, "valence": 0.0}],
                    "tomorrow_intentions": ["visit_partner"],
                }
            ),
            agent=partnerless_agent,
            world=partnerless_world,
        )

    resource_free_world = _world()
    resource_free_world.resources = []
    with pytest.raises(ReflectionValidationError, match="known resources"):
        validator.validate_output(
            ReflectionOutput.model_validate(
                {
                    "summary": "bad",
                    "mood_delta": {},
                    "belief_updates": [],
                    "goal_updates": [
                        {
                            "action": "create",
                            "goal_type": "safety",
                            "title": "Recover",
                            "priority": 0.6,
                            "horizon_days": 1,
                        }
                    ],
                    "memory_candidates": [{"text": "bad", "salience": 0.5, "valence": 0.0}],
                    "tomorrow_intentions": ["gather_resources"],
                }
            ),
            agent=resource_free_world.agents[0],
            world=resource_free_world,
        )

    unknown_agent_world = _world()
    with pytest.raises(ReflectionValidationError, match="unknown agent"):
        validator.validate_output(
            ReflectionOutput.model_validate(
                {
                    "summary": "bad",
                    "mood_delta": {},
                    "belief_updates": [],
                    "goal_updates": [
                        {
                            "action": "create",
                            "goal_type": "safety",
                            "title": "Recover",
                            "priority": 0.6,
                            "horizon_days": 1,
                        }
                    ],
                    "memory_candidates": [{"text": "bad", "salience": 0.5, "valence": 0.0}],
                    "tomorrow_intentions": ["avoid_agent_missing-agent"],
                }
            ),
            agent=unknown_agent_world.agents[0],
            world=unknown_agent_world,
        )


def test_reflection_workflow_surfaces_model_adapter_failures_at_call_stage() -> None:
    """Model adapter failures should stop the workflow at call_model with no mutation."""

    workflow = ReflectionWorkflow(llm_client=ExplodingLLMClient())
    world = _world()
    agent = world.agents[0]

    execution = workflow.execute(
        agent,
        world,
        _context(),
        validator=ReflectionValidator(),
        goal_updater=GoalUpdater(),
        belief_updater=BeliefUpdater(),
        memory_writer=MemoryWriter(),
    )

    assert execution.success is False
    assert execution.completed_stages == ["load_state", "retrieve_context", "build_prompt"]
    assert execution.failure_stage == "call_model"
    assert execution.validation_errors == []
    assert agent.current_goal == "Maintain daily routine"
    assert agent.beliefs == []
    assert agent.memories == []
    assert agent.pending_planner_hints == []


def test_reflection_workflow_stops_before_persistence_when_validation_fails() -> None:
    """Validation failures should prevent persistence and planner-hint emission."""

    workflow = ReflectionWorkflow(
        llm_client=RecordingLLMClient(
            ReflectionOutput(
                summary="bad",
                mood_delta={},
                belief_updates=[],
                goal_updates=[],
                memory_candidates=[],
                tomorrow_intentions=["keep_routine"],
            ).model_dump_json()
        )
    )
    world = _world()
    agent = world.agents[0]

    execution = workflow.execute(
        agent,
        world,
        _context(),
        validator=ReflectionValidator(),
        goal_updater=GoalUpdater(),
        belief_updater=BeliefUpdater(),
        memory_writer=MemoryWriter(),
    )

    assert execution.success is False
    assert execution.completed_stages == [
        "load_state",
        "retrieve_context",
        "build_prompt",
        "call_model",
        "parse_json",
    ]
    assert execution.failure_stage == "validate"
    assert execution.validation_errors
    assert agent.current_goal == "Maintain daily routine"
    assert agent.beliefs == []
    assert agent.memories == []
    assert agent.pending_planner_hints == []
