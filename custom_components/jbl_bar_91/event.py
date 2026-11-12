"""Events for automations: timers and messages on the bar's front display.

Each update is compared with the previous one, so an event fires once per
change. Nothing fires for what is already there when Home Assistant starts,
nor while the remote cannot be reached.

Timer events: started, ringing, finished (it rang, then a key, a cancel or the
ring's end stopped it) and cancelled (stopped before ringing). Message events:
shown (a new message, showing or waiting its turn) and ended.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import JblBarConfigEntry, JblBarCoordinator
from .entity import JblBarEntity
from .messages import message_list, messages_installed
from .timers import timer_list, timers_installed


async def async_setup_entry(hass: HomeAssistant, entry: JblBarConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    entities: list[EventEntity] = []
    if timers_installed(coordinator.data):
        entities.append(JblBarTimerEvents(coordinator, "timer_events"))
    if messages_installed(coordinator.data):
        entities.append(JblBarMessageEvents(coordinator, "message_events"))
    add(entities)


class JblBarChangeEvents(JblBarEntity, EventEntity):
    """Fires an event per change between two states of the remote."""

    def __init__(self, coordinator: JblBarCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._last: dict[str, dict[str, Any]] | None = None

    def snapshot(self) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    def changes(self, before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.last_update_success:
            self._last = self.snapshot()

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self.coordinator.last_update_success:
            return  # unreachable: no "ended" for everything
        now = self.snapshot()
        changes = self.changes(self._last, now) if self._last is not None else []
        self._last = now
        for event_type, data in changes:
            # One state per event: automations see each one, not only the last.
            self._trigger_event(event_type, data)
            self.async_write_ha_state()
        if not changes:
            self.async_write_ha_state()


class JblBarTimerEvents(JblBarChangeEvents):
    _attr_event_types = ["started", "ringing", "finished", "cancelled"]
    _attr_icon = "mdi:timer-alert-outline"

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {t["id"]: {"id": t["id"], "name": t.get("text") or "", "ringing": bool(t.get("ringing"))} for t in timer_list(self.state_doc)}

    def changes(self, before, after):
        out = []
        for tid, t in after.items():
            data = {"id": tid, "name": t["name"]}
            if tid not in before:
                out.append(("started", data))
            if t["ringing"] and not (before.get(tid) or {}).get("ringing"):
                out.append(("ringing", data))
        for tid, t in before.items():
            if tid not in after:
                out.append(("finished" if t["ringing"] else "cancelled", {"id": tid, "name": t["name"]}))
        return out


class JblBarMessageEvents(JblBarChangeEvents):
    _attr_event_types = ["shown", "ended"]
    _attr_icon = "mdi:message-alert-outline"

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {m["id"]: {"id": m["id"], "text": m.get("text") or "", "named": bool(m.get("named", m["id"] != "default"))}
                for m in message_list(self.state_doc)}

    def changes(self, before, after):
        out = []
        for mid, m in after.items():
            if mid not in before or before[mid]["text"] != m["text"]:
                out.append(("shown", dict(m)))
        for mid, m in before.items():
            if mid not in after:
                out.append(("ended", dict(m)))
        return out
