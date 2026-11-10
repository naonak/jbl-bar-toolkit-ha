"""Timers on the bar's front display (remote extension bar91.timer).

The remote reports each timer's time left (remaining_ms) in every state; this
module turns it into an end time that stays put between updates, so entities
do not change every second.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
import unicodedata

from homeassistant.util import dt as dt_util

TIMER = "bar91.timer"
TIMER_SOUNDS = ["off", "unless_tv", "always"]
TIMER_VOLUME_DEFAULT = 10
TIMER_RING_DEFAULT = 30  # seconds
JITTER = timedelta(seconds=2)  # end times closer than this are the same


def timers_installed(doc: dict[str, Any] | None) -> bool:
    """True when the remote has timers (its state carries the extension, even with none running)."""
    return isinstance(((doc or {}).get("extensions") or {}).get(TIMER), dict)


def timer_list(doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    timers = (((doc or {}).get("extensions") or {}).get(TIMER) or {}).get("timers")
    return [t for t in timers if isinstance(t, dict) and isinstance(t.get("id"), str)] if isinstance(timers, list) else []


def fold_name(name: str) -> str:
    """As the remote writes names: upper case, no accents, single spaces."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("Œ", "OE").replace("œ", "oe")
    return " ".join(text.upper().split())


class TimerClock:
    """Turns remaining_ms into stable end times."""

    def __init__(self) -> None:
        self._ends: dict[str, datetime] = {}

    def ends(self, doc: dict[str, Any] | None, now: datetime | None = None) -> dict[str, datetime]:
        now = now or dt_util.utcnow()
        current: dict[str, datetime] = {}
        for t in timer_list(doc):
            if t.get("ringing"):
                continue
            end = (now + timedelta(milliseconds=int(t.get("remaining_ms") or 0))).replace(microsecond=0)
            previous = self._ends.get(t["id"])
            current[t["id"]] = previous if previous and abs(previous - end) < JITTER else end
        self._ends = current
        return current

    def describe(self, doc: dict[str, Any] | None) -> list[dict[str, Any]]:
        """The timers for entity attributes and dashboards, first to end first."""
        ends = self.ends(doc)
        out = []
        for t in timer_list(doc):
            end = ends.get(t["id"])
            out.append({
                "id": t["id"], "name": t.get("text") or "", "ringing": bool(t.get("ringing")),
                "ends_at": end.isoformat() if end else None, "countdown": bool(t.get("countdown")),
                "sound": t.get("sound") or "off",
                # Start to end, time added included (remotes with +1 min); for progress bars.
                "duration_s": int(t["duration_ms"]) // 1000 if isinstance(t.get("duration_ms"), int) else None,
            })
        out.sort(key=lambda t: (not t["ringing"], t["ends_at"] or ""))
        return out
