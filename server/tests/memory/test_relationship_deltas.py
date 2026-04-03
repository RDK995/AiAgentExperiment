"""Focused tests for rule-based relationship deltas from important events."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.memory.relationships import RelationshipDeltaUpdater
from app.schemas.event import EventType, SimulationEvent


def _event(event_type: EventType, *, actor_ids: list[str], target_ids: list[str], **payload) -> SimulationEvent:
    return SimulationEvent(
        type=event_type,
        tick=20,
        sim_time=datetime(2000, 1, 1, 10, 0, tzinfo=timezone.utc),
        actor_ids=actor_ids,
        target_ids=target_ids,
        payload=payload,
    )


def test_generous_gift_while_starving_updates_target_relationship_metrics() -> None:
    """A starvation-context gift should create the intended trust/obligation/admiration jump."""

    updater = RelationshipDeltaUpdater()

    deltas = updater.deltas_for(
        _event(
            EventType.GIFT_GIVEN,
            actor_ids=["agent-b"],
            target_ids=["agent-a"],
            target_was_starving=True,
        )
    )

    assert len(deltas) == 2
    target_view = next(delta for delta in deltas if delta.source_agent_id == "agent-a")
    assert target_view.target_agent_id == "agent-b"
    assert target_view.trust == pytest.approx(0.18)
    assert target_view.obligation == pytest.approx(0.22)
    assert target_view.admiration == pytest.approx(0.08)


def test_public_insult_updates_resentment_trust_and_fear() -> None:
    """Public insults should create a clear negative directional relationship delta."""

    updater = RelationshipDeltaUpdater()

    deltas = updater.deltas_for(
        _event(
            EventType.INSULT_SPOKEN,
            actor_ids=["agent-b"],
            target_ids=["agent-a"],
            public=True,
        )
    )

    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.source_agent_id == "agent-a"
    assert delta.target_agent_id == "agent-b"
    assert delta.resentment == pytest.approx(0.17)
    assert delta.trust == pytest.approx(-0.10)
    assert delta.fear == pytest.approx(0.03)


def test_unsupported_event_types_do_not_emit_relationship_deltas() -> None:
    """Routine non-social events should not invent relationship changes."""

    updater = RelationshipDeltaUpdater()

    deltas = updater.deltas_for(
        _event(
            EventType.AGENT_DRANK,
            actor_ids=["agent-a"],
            target_ids=[],
        )
    )

    assert deltas == []


def test_proposal_acceptance_creates_bidirectional_positive_relationship_deltas() -> None:
    """Proposal acceptance should improve both directed relationship views symmetrically."""

    updater = RelationshipDeltaUpdater()

    deltas = updater.deltas_for(
        _event(
            EventType.PROPOSAL_ACCEPTED,
            actor_ids=["agent-a"],
            target_ids=["agent-b"],
        )
    )

    assert len(deltas) == 2
    assert {(delta.source_agent_id, delta.target_agent_id) for delta in deltas} == {
        ("agent-a", "agent-b"),
        ("agent-b", "agent-a"),
    }
    assert all(delta.trust == pytest.approx(0.12) for delta in deltas)
    assert all(delta.attraction == pytest.approx(0.15) for delta in deltas)
    assert all(delta.familiarity == pytest.approx(0.08) for delta in deltas)
