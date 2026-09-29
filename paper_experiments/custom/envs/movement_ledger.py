"""MovementLedgerEnv - per-step movement log for MobilitySpace runs.

The disaster-mobility study (AgentSociety 2 paper Sec. 7.7) compares DAILY
completed movements with empirical mobility indices. MobilitySpace (2.8.2) only
exports de-duplicated trajectory points without timestamps, so this companion
module snapshots every person's status and AOI once per simulation step.

It never touches MobilitySpace itself: during the per-step society checkpoint
(``to_workspace``, run for env modules in config order) it reads the sibling
file ``<run_dir>/env/<source_module>/state/ENV_STATE.json`` that MobilitySpace
has just written. List this module AFTER MobilitySpace in ``env_modules``.

Output (in <run_dir>/env/MovementLedgerEnv/):
- ``movement_events.jsonl``: one row per completed move (person arrives and is
  idle at a different AOI than its last idle AOI) and per departure from home.
- ``movement_daily.json``: completed moves and home departures per simulated day.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from agentsociety2.env import EnvBase, tool
from agentsociety2.storage.workspace_state import atomic_write_text


class MovementLedgerEnv(EnvBase):
    """Logs completed movements and home departures per simulated day from MobilitySpace checkpoints."""

    def __init__(self, source_module: str = "MobilitySpace"):
        super().__init__()
        self.source_module = source_module
        self._last_idle_aoi: Dict[str, Optional[int]] = {}
        self._last_status: Dict[str, str] = {}
        self._home_aoi: Dict[str, Optional[int]] = {}
        self._daily_moves: Dict[str, int] = defaultdict(int)
        self._daily_departures: Dict[str, int] = defaultdict(int)
        self._last_logged_t: Optional[str] = None

    @classmethod
    def description(cls) -> str:
        return "Movement ledger: counts completed moves and home departures per simulated day."

    @classmethod
    def init_description(cls) -> str:
        return """MovementLedgerEnv: per-day movement counts for a MobilitySpace run.

**Constructor kwargs:** **source_module** (str): the MobilitySpace module type whose
checkpoint is read (default "MobilitySpace"). Place this module after MobilitySpace
in env_modules. Agents do not need to call it.
"""

    @tool(readonly=True, kind="statistics")
    async def get_movement_counts(self) -> Dict[str, Any]:
        """Return the number of completed movements and of departures from home for every simulated day so far."""
        return {"status": "success", "completed_moves_by_day": dict(self._daily_moves),
                "home_departures_by_day": dict(self._daily_departures)}

    async def step(self, tick: int, t: datetime):
        self.t = t

    def _snapshot(self) -> None:
        if self._workspace_root is None or getattr(self, "t", None) is None:
            return
        stamp = self.t.isoformat()
        if stamp == self._last_logged_t:  # one snapshot per simulation step
            return
        src = Path(self._workspace_root).parent / self.source_module / "state" / "ENV_STATE.json"
        if not src.is_file():
            return
        try:
            persons = json.loads(src.read_text(encoding="utf-8")).get("persons", {})
        except (json.JSONDecodeError, OSError):
            return  # file mid-replace; the next step will catch up
        self._last_logged_t = stamp
        day = self.t.date().isoformat()
        events = []
        for pid, p in persons.items():
            pos = p.get("position") or {}
            status = p.get("status", "idle")
            aoi = pos.get("aoi_id") if pos.get("kind") == "aoi" else None
            self._home_aoi.setdefault(pid, p.get("home_aoi"))
            prev_status = self._last_status.get(pid, "idle")
            prev_aoi = self._last_idle_aoi.get(pid)
            # Left home since the last snapshot: now moving, or already idle elsewhere
            # (a trip that started and ended within one step).
            left_home = (prev_status == "idle" and prev_aoi is not None and prev_aoi == self._home_aoi[pid]
                         and (status == "moving" or (aoi is not None and aoi != prev_aoi)))
            if left_home:
                self._daily_departures[day] += 1
                events.append({"t": stamp, "person_id": int(pid), "event": "home_departure"})
            if status == "idle" and aoi is not None:
                if prev_aoi is not None and aoi != prev_aoi:
                    self._daily_moves[day] += 1
                    events.append({"t": stamp, "person_id": int(pid), "event": "completed_move",
                                   "from_aoi": prev_aoi, "to_aoi": aoi})
                self._last_idle_aoi[pid] = aoi
            self._last_status[pid] = status
        root = Path(self._workspace_root)
        if events:
            with open(root / "movement_events.jsonl", "a", encoding="utf-8") as f:
                for e in events:
                    f.write(json.dumps(e) + "\n")
        atomic_write_text(root / "movement_daily.json", json.dumps({
            "completed_moves_by_day": dict(sorted(self._daily_moves.items())),
            "home_departures_by_day": dict(sorted(self._daily_departures.items())),
        }, indent=2))

    async def to_workspace(self, workspace_path: Path | None = None) -> None:
        await super().to_workspace(workspace_path)
        self._snapshot()
