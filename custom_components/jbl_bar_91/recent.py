"""Recent timers and messages, to start again in one press.

Every timer and message that shows up on the bar is remembered, wherever it
came from (the page, Home Assistant, an automation): as it was when first
seen, so the timer's full length and the message's whole count or duration.
The last RECENT of each, most recent first, without repeats, are kept in
Home Assistant's storage, so they survive a restart.

Each is a button (button.jbl_recent_timer_N, button.jbl_recent_message_N)
named after it; pressing it starts that timer or shows that message again.
An empty slot is unavailable, so a dashboard hides it. Names only change when
the list does.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .coordinator import JblBarCoordinator
from .entity import JblBarEntity
from .lines import TEXT, texts
from .messages import message_list
from .timers import TIMER, timer_list

RECENT = 4
STORE_VERSION = 1


class RecentTracker:
    """Remembers the timers and messages seen on the bar."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, f"jbl_bar_91.recent.{entry_id}")
        self.timers: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self._seen: set[str] | None = None  # None until the first state: what runs then is not new

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.timers = [t for t in data.get("timers", []) if isinstance(t, dict) and isinstance(t.get("minutes"), int)][:RECENT]
        self.messages = [m for m in data.get("messages", []) if isinstance(m, dict) and isinstance(m.get("text"), str)][:RECENT]

    def _save(self) -> None:
        # Rare (a new timer or message): written at once.
        data = {"timers": list(self.timers), "messages": list(self.messages)}
        self._hass.async_create_background_task(self._store.async_save(data), "jbl_bar_91 recent save")

    @callback
    def update(self, doc: dict[str, Any] | None) -> bool:
        """Remember what is new in this state; True when a list changed.

        What already runs at the first state (Home Assistant started, the
        integration reloaded) is not new: it may be half done, and is most
        likely among the recent ones already.
        """
        if doc is None:
            return False
        first = self._seen is None
        seen = self._seen or set()
        changed = False
        now: set[str] = set()
        for t in timer_list(doc):
            key = f"timer:{t['id']}"
            now.add(key)
            if first or key in seen or not isinstance(t.get("duration_ms"), int):
                continue
            entry = {"text": t.get("text") or "", "minutes": max(1, round(t["duration_ms"] / 60000)),
                     "sound": t.get("sound") or "off", "countdown": bool(t.get("countdown"))}
            for extra in ("sound_volume", "ring_s"):
                if isinstance(t.get(extra), int):
                    entry[extra] = t[extra]
            self.timers = [entry, *[r for r in self.timers if (r["text"], r["minutes"]) != (entry["text"], entry["minutes"])]][:RECENT]
            changed = True
        for m in message_list(doc):
            key = f"message:{m['id']}:{m.get('text')}"
            now.add(key)
            if first or key in seen or not m.get("text"):
                continue
            entry = {"text": m["text"], "id": m["id"] if m.get("named") else "", "stop_on_key": bool(m.get("stop_on_key"))}
            if m.get("mode") == "forever":
                entry["forever"] = True
            elif m.get("mode") == "duration" and isinstance(m.get("remaining_ms"), int):
                entry["duration_s"] = max(60, -(-m["remaining_ms"] // 60000) * 60)  # whole minutes, rounded up
            elif isinstance(m.get("passes_left"), int) and m["passes_left"] > 0:
                entry["repeat"] = m["passes_left"]
            else:
                continue
            self.messages = [entry, *[r for r in self.messages if (r["text"], r["id"]) != (entry["text"], entry["id"])]][:RECENT]
            changed = True
        self._seen = now
        if changed:
            self._save()
        return changed


def tracker(coordinator: JblBarCoordinator) -> RecentTracker:
    return coordinator.recent


def _length(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    return f"{seconds // 60} min"


class JblBarRecent(JblBarEntity, ButtonEntity):
    """Recent timer or message `index` (1-based), to start again."""

    _attr_has_entity_name = False
    kind = ""

    def __init__(self, coordinator: JblBarCoordinator, index: int) -> None:
        super().__init__(coordinator, f"recent_{self.kind}_{index}")
        self._index = index
        self.entity_id = f"button.jbl_recent_{self.kind}_{index}"

    def items(self) -> list[dict[str, Any]]:
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
        return self.label(item, words) if item else f"{words[f'recent_{self.kind}']} {self._index}"

    def label(self, item: dict[str, Any], words: dict[str, str]) -> str:
        raise NotImplementedError


class JblBarRecentTimer(JblBarRecent):
    kind = "timer"
    _attr_icon = "mdi:timer-refresh-outline"

    def items(self) -> list[dict[str, Any]]:
        return tracker(self.coordinator).timers

    def label(self, item: dict[str, Any], words: dict[str, str]) -> str:
        return f"{item['text'] or words['timer']} · {_length(item['minutes'] * 60)}"

    async def async_press(self) -> None:
        if not (item := self._item()):
            return
        parameters: dict[str, Any] = {"duration_s": item["minutes"] * 60, "sound": item.get("sound", "off")}
        if item["text"]:
            parameters["text"] = item["text"]
        if item.get("countdown"):
            parameters["countdown"] = True
        for extra in ("sound_volume", "ring_s"):
            if extra in item:
                parameters[extra] = item[extra]
        await self.extension_action(TIMER, "start", parameters, "timer_unsupported")


class JblBarRecentMessage(JblBarRecent):
    kind = "message"
    _attr_icon = "mdi:message-reply-text-outline"

    def items(self) -> list[dict[str, Any]]:
        return tracker(self.coordinator).messages

    def label(self, item: dict[str, Any], words: dict[str, str]) -> str:
        if item.get("forever"):
            how = words["forever"]
        elif "duration_s" in item:
            how = _length(item["duration_s"])
        else:
            how = words["times"].format(n=item.get("repeat", 1))
        return f"{item['text']}{' (' + item['id'] + ')' if item['id'] else ''} · {how}"

    async def async_press(self) -> None:
        if not (item := self._item()):
            return
        parameters: dict[str, Any] = {"text": item["text"]}
        if item["id"]:
            parameters["id"] = item["id"]
        for key in ("forever", "duration_s", "repeat"):
            if key in item:
                parameters[key] = item[key]
        if item.get("stop_on_key"):
            parameters["stop_on_key"] = True
        await self.display_action("show", parameters)
