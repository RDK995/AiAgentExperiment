"""Simulation clock helpers for authoritative tick advancement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(slots=True, frozen=True)
class SimTick:
    """A single authoritative simulation tick."""

    tick: int
    at: datetime
    previous_day_index: int
    day_index: int

    @property
    def day_rolled_over(self) -> bool:
        """Whether this tick crossed a day boundary."""

        return self.day_index != self.previous_day_index


class SimulationClock:
    """Authoritative simulation clock with fixed tick intervals."""

    def __init__(
        self,
        start_time: datetime | None = None,
        tick_interval: timedelta = timedelta(seconds=1),
    ) -> None:
        self._current_time = start_time or datetime(2000, 1, 1, 6, 0, tzinfo=timezone.utc)
        self._tick_interval = tick_interval
        self._tick = 0

    @property
    def current_time(self) -> datetime:
        """Current simulation time."""

        return self._current_time

    @property
    def tick(self) -> int:
        """Current simulation tick index."""

        return self._tick

    def advance(self) -> SimTick:
        """Advance the simulation by one fixed interval."""

        previous_day_index = self._day_index(self._current_time)
        self._current_time += self._tick_interval
        self._tick += 1
        day_index = self._day_index(self._current_time)
        return SimTick(
            tick=self._tick,
            at=self._current_time,
            previous_day_index=previous_day_index,
            day_index=day_index,
        )

    @staticmethod
    def _day_index(moment: datetime) -> int:
        """Collapse a timestamp into a day index for rollover detection."""

        return moment.toordinal()
