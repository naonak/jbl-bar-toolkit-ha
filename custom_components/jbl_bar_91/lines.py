"""One button per timer and per message on the bar, for dashboard lists.

Line N is the Nth timer (first to end first, a ringing one on top) or the Nth
message, as the remote lists them; pressing it cancels that timer or clears
that message. An empty line is unavailable, so dashboards hide it.

A dashboard entity row draws the entity's live name, so the name is the line's
text: the lines stay out of the entity registry (see unregistered). It only
changes when the line shows another timer or message, never with the time or
passes left.

The entity ids are suggested as button.jbl_timer_line_N / button.jbl_message_line_N
so that dashboard templates can name them in any language.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .coordinator import JblBarCoordinator
from .entity import JblBarEntity
from .messages import MessageClock
from .timers import TIMER, TimerClock

LINES = 8  # the remote runs at most 8 timers; messages beyond 8 stay on the summary sensor

TEXT = {
    "en": {"timer": "Timer", "ringing": "ringing", "ends": "ends at", "until": "until", "forever": "until cleared",
           "timer_line": "Timer line", "message_line": "Message line",
           "recent_timer": "Recent timer", "recent_message": "Recent message", "times": "{n} times"},
    "fr": {"timer": "Minuteur", "ringing": "sonne", "ends": "fin à", "until": "jusqu'à", "forever": "jusqu'à effacement",
           "timer_line": "Ligne de minuteur", "message_line": "Ligne de message",
           "recent_timer": "Minuteur récent", "recent_message": "Message récent", "times": "{n} fois"},
}


def texts(hass: HomeAssistant) -> dict[str, str]:
    return TEXT["fr"] if (hass.config.language or "").lower().startswith("fr") else TEXT["en"]


def timer_clock(coordinator: JblBarCoordinator) -> TimerClock:
    """One clock per bar, so that every timer entity shows the same end times."""
    clock = getattr(coordinator, "timer_clock", None)
    if clock is None:
        clock = coordinator.timer_clock = TimerClock()
    return clock


def message_clock(coordinator: JblBarCoordinator) -> MessageClock:
    clock = getattr(coordinator, "message_clock", None)
    if clock is None:
        clock = coordinator.message_clock = MessageClock()
    return clock


def _hhmm(iso: str | None) -> str:
    when = dt_util.parse_datetime(iso) if iso else None
    return dt_util.as_local(when).strftime("%H:%M") if when else ""


def timer_label(t: dict[str, Any], words: dict[str, str]) -> str:
    name = t["name"] or words["timer"]
    if t["ringing"]:
        return f"🔔 {name} – {words['ringing']}"
    return f"{name} – {words['ends']} {_hhmm(t['ends_at'])}" if t["ends_at"] else name


def message_label(m: dict[str, Any], words: dict[str, str]) -> str:
    label = m["text"] + (f" ({m['name']})" if m["name"] else "")
    if m["mode"] == "forever":
        return f"{label} – {words['forever']}"
    if m["mode"] == "duration" and m["ends_at"]:
        return f"{label} – {words['until']} {_hhmm(m['ends_at'])}"
    return label


def unregistered(entity: JblBarEntity) -> None:
    """Keep a line out of the entity registry.

    Dashboards name a registered entity from the registry (its device's name,
    then its own, as last recorded), not from its live state: the lines would
    show "JBL Bar 9.1 …" and could lag behind. Unregistered, a dashboard shows
    the live name. Such an entity has no device page entry and cannot be
    renamed from the UI, which these lines do not need.
    """
    entity._attr_unique_id = None
    entity._attr_device_info = None


class JblBarLine(JblBarEntity, ButtonEntity):
    """Line `index` (1-based) of the timers or messages."""

    _attr_has_entity_name = False
    kind = ""

    def __init__(self, coordinator: JblBarCoordinator, index: int) -> None:
        super().__init__(coordinator, f"{self.kind}_line_{index}")
        self._attr_translation_key = None
        self._index = index
        self.entity_id = f"button.jbl_{self.kind}_line_{index}"
        unregistered(self)

    def items(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def label(self, item: dict[str, Any], words: dict[str, str]) -> str:
        raise NotImplementedError

    def _item(self) -> dict[str, Any] | None:
        items = self.items()
        return items[self._index - 1] if len(items) >= self._index else None

    @property
    def available(self) -> bool:
        return super().available and self._item() is not None

    @property
    def name(self) -> str:
        words = texts(self.hass) if self.hass else TEXT["en"]
        item = self._item()
        return self.label(item, words) if item else f"{words[f'{self.kind}_line']} {self._index}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._item()
        return {"line": self._index, "id": item["id"] if item else None}


class JblBarTimerLine(JblBarLine):
    kind = "timer"
    _attr_icon = "mdi:timer-outline"

    def items(self) -> list[dict[str, Any]]:
        return timer_clock(self.coordinator).describe(self.state_doc)

    def label(self, item: dict[str, Any], words: dict[str, str]) -> str:
        return timer_label(item, words)

    @property
    def icon(self) -> str:
        item = self._item()
        return "mdi:bell-ring" if item and item["ringing"] else "mdi:timer-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Also the timer's end and full length, for live countdowns and progress bars.

        Neither moves with the time (only +1 min changes them), so the state is
        not rewritten every poll.
        """
        item = self._item() or {}
        return {**super().extra_state_attributes, "name": item.get("name"), "ringing": bool(item.get("ringing")),
                "ends_at": item.get("ends_at"), "duration_s": item.get("duration_s")}

    async def async_press(self) -> None:
        if item := self._item():
            await self.extension_action(TIMER, "cancel", {"id": item["id"]}, "timer_unsupported")


class JblBarMessageLine(JblBarLine):
    kind = "message"

    def items(self) -> list[dict[str, Any]]:
        return message_clock(self.coordinator).describe(self.state_doc)

    def label(self, item: dict[str, Any], words: dict[str, str]) -> str:
        return message_label(item, words)

    @property
    def icon(self) -> str:
        item = self._item()
        return "mdi:message-text" if item and item["showing"] else "mdi:message-text-clock-outline"

    async def async_press(self) -> None:
        if item := self._item():
            await self.display_action("cancel", {"id": item["id"]})
