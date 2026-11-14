"""Messages on the bar's front display, as the remote lists them (remotes with the Messages panel)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import DISPLAY_MESSAGE

UNNAMED = "default"  # the id of a message sent without one: one at a time
JITTER = timedelta(seconds=2)


def messages_installed(doc: dict[str, Any] | None) -> bool:
    """True when the remote lists the messages in course (even with none)."""
    box = ((doc or {}).get("extensions") or {}).get(DISPLAY_MESSAGE)
    return isinstance(box, dict) and isinstance(box.get("messages"), list)


def message_options(doc: dict[str, Any] | None) -> list[str]:
    """What the remote's show takes beyond the text and the length (stop_on_key, when_on)."""
    box = ((doc or {}).get("extensions") or {}).get(DISPLAY_MESSAGE)
    options = box.get("options") if isinstance(box, dict) else None
    return [o for o in options if isinstance(o, str)] if isinstance(options, list) else []


def message_list(doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    box = ((doc or {}).get("extensions") or {}).get(DISPLAY_MESSAGE) or {}
    items = box.get("messages") if isinstance(box, dict) else None
    return [m for m in items if isinstance(m, dict) and isinstance(m.get("id"), str)] if isinstance(items, list) else []


class MessageClock:
    """Turns remaining_ms into stable end times, so attributes do not change at every update."""

    def __init__(self) -> None:
        self._ends: dict[str, datetime] = {}

    def describe(self, doc: dict[str, Any] | None, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or dt_util.utcnow()
        ends: dict[str, datetime] = {}
        out = []
        for m in message_list(doc):
            end = None
            held = bool(m.get("held"))  # waits for the bar to be on: its time has not started
            if m.get("mode") == "duration" and not held:
                end = (now + timedelta(milliseconds=int(m.get("remaining_ms") or 0))).replace(microsecond=0)
                previous = self._ends.get(m["id"])
                end = previous if previous and abs(previous - end) < JITTER else end
                ends[m["id"]] = end
            out.append({
                "id": m["id"],
                "name": m["id"] if m.get("named", m["id"] != UNNAMED) else "",
                "text": m.get("text") or "",
                "mode": m.get("mode") or "passes",
                "passes_left": m.get("passes_left") if m.get("mode") == "passes" else None,
                "ends_at": end.isoformat() if end else None,
                "duration_s": int(m.get("remaining_ms") or 0) // 1000 if held and m.get("mode") == "duration" else None,
                "showing": bool(m.get("showing")),
                "when_on": bool(m.get("when_on")),
                "held": held,
            })
        self._ends = ends
        return out
