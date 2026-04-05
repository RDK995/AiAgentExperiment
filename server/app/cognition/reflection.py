"""Deterministic reflection workflow stubs for the agent slow loop."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.cognition.llm_client import ReflectionLLMClient
from app.cognition.output_parser import ReflectionOutputParser, ReflectionParseError
from app.cognition.prompt_builder import ReflectionPromptBuilder
from app.cognition.validation import ReflectionValidationError, ReflectionValidator
from app.cognition.belief_updater import BeliefUpdater
from app.cognition.goal_updater import GoalUpdater
from app.engine.world_state import AgentState, WorldState
from app.memory.writer import MemoryWriter
from app.schemas.reflection import (
    ReflectionContext,
    ReflectionOutput,
    ReflectionResult,
)


@dataclass(slots=True)
class ReflectionExecution:
    """Recorded outcome for one staged reflection workflow run."""

    agent_id: str
    success: bool
    completed_stages: list[str] = field(default_factory=list)
    failure_stage: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    result: ReflectionResult | None = None
    planner_hints: list[str] = field(default_factory=list)


class ReflectionWorkflow:
    """Prototype reflection workflow returning structured placeholder outputs."""

    def __init__(
        self,
        *,
        prompt_builder: ReflectionPromptBuilder | None = None,
        llm_client: ReflectionLLMClient | None = None,
        output_parser: ReflectionOutputParser | None = None,
    ) -> None:
        self._prompt_builder = prompt_builder or ReflectionPromptBuilder()
        self._llm_client = llm_client or ReflectionLLMClient()
        self._output_parser = output_parser or ReflectionOutputParser()

    def run(self, agent: AgentState, context: ReflectionContext) -> ReflectionResult:
        """Build prompt, call the model adapter, and parse structured JSON."""

        prompt = self._prompt_builder.build_for_agent(agent, context)
        raw_output = self._llm_client.generate(prompt, agent=agent, context=context)
        return self._output_parser.parse(raw_output)

    def execute(
        self,
        agent: AgentState,
        world: WorldState,
        context: ReflectionContext,
        *,
        validator: ReflectionValidator,
        goal_updater: GoalUpdater,
        belief_updater: BeliefUpdater,
        memory_writer: MemoryWriter,
    ) -> ReflectionExecution:
        """Run the full staged reflection workflow including validation and persistence."""

        execution = ReflectionExecution(
            agent_id=agent.agent_id,
            success=False,
            completed_stages=[],
        )
        snapshot = self._snapshot_agent(agent)
        current_stage = "load_state"
        try:
            execution.completed_stages.append("load_state")
            current_stage = "retrieve_context"
            execution.completed_stages.append("retrieve_context")
            if type(self).run is not ReflectionWorkflow.run:
                execution.completed_stages.extend(["build_prompt", "call_model", "parse_json"])
                validated_result = validator.validate(self.run(agent, context))
                execution.completed_stages.append("validate")
                goal_updater.apply(agent, validated_result.goals)
                belief_updater.apply(agent, validated_result.beliefs)
                memory_writer.write(agent, validated_result.memory_entries)
                execution.completed_stages.append("persist_updates")
                agent.pending_planner_hints = list(validated_result.planner_hints)
                execution.completed_stages.append("emit_planner_hints")
                execution.success = True
                execution.result = validated_result
                execution.planner_hints = list(validated_result.planner_hints)
                return execution

            current_stage = "build_prompt"
            prompt = self._prompt_builder.build_for_agent(agent, context)
            execution.completed_stages.append("build_prompt")
            current_stage = "call_model"
            raw_output = self._llm_client.generate(prompt, agent=agent, context=context)
            execution.completed_stages.append("call_model")
            current_stage = "parse_json"
            parsed_output = self._output_parser.parse_output(raw_output)
            execution.completed_stages.append("parse_json")
            current_stage = "validate"
            validated_output = validator.validate_output(parsed_output, agent=agent, world=world)
            execution.completed_stages.append("validate")
            current_stage = "persist_updates"
            self._persist_updates(
                agent,
                validated_output,
                goal_updater=goal_updater,
                belief_updater=belief_updater,
                memory_writer=memory_writer,
            )
            execution.completed_stages.append("persist_updates")
            agent.pending_planner_hints = list(validated_output.tomorrow_intentions)
            execution.completed_stages.append("emit_planner_hints")
            execution.success = True
            execution.result = validated_output.to_reflection_result()
            execution.planner_hints = list(validated_output.tomorrow_intentions)
            return execution
        except ReflectionParseError:
            self._restore_agent(agent, snapshot)
            execution.failure_stage = "parse_json"
            return execution
        except ReflectionValidationError as exc:
            self._restore_agent(agent, snapshot)
            execution.failure_stage = "validate"
            execution.validation_errors = [str(exc)]
            return execution
        except Exception:
            self._restore_agent(agent, snapshot)
            execution.failure_stage = current_stage
            return execution

    @staticmethod
    def _persist_updates(
        agent: AgentState,
        output: ReflectionOutput,
        *,
        goal_updater: GoalUpdater,
        belief_updater: BeliefUpdater,
        memory_writer: MemoryWriter,
    ) -> None:
        result = output.to_reflection_result()
        goal_updater.apply(agent, result.goals)
        belief_updater.apply(agent, result.beliefs)
        memory_writer.write(agent, result.memory_entries)
        for field_name, delta in output.mood_delta.items():
            current_value = getattr(agent, field_name)
            setattr(agent, field_name, max(0.0, min(100.0, current_value + delta)))

    @staticmethod
    def _snapshot_agent(agent: AgentState) -> dict[str, object]:
        return {
            "current_goal": agent.current_goal,
            "beliefs": list(agent.beliefs),
            "memories": list(agent.memories),
            "pending_planner_hints": list(agent.pending_planner_hints),
            "morale": agent.morale,
            "hope": agent.hope,
            "grief": agent.grief,
            "shame": agent.shame,
        }

    @staticmethod
    def _restore_agent(agent: AgentState, snapshot: dict[str, object]) -> None:
        agent.current_goal = snapshot["current_goal"]  # type: ignore[assignment]
        agent.beliefs = list(snapshot["beliefs"])  # type: ignore[arg-type]
        agent.memories = list(snapshot["memories"])  # type: ignore[arg-type]
        agent.pending_planner_hints = list(snapshot["pending_planner_hints"])  # type: ignore[arg-type]
        agent.morale = float(snapshot["morale"])
        agent.hope = float(snapshot["hope"])
        agent.grief = float(snapshot["grief"])
        agent.shame = float(snapshot["shame"])
