"""Night mode: toggled only when the read-back state differs."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import JblBarConfigEntry
from .entity import JblBarEntity, advanced_controls

DISPLAY_CLOCK = "bar91.display-clock"


def clock_state(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """The standby clock's setting (enabled, tz), when the remote has the clock."""
    value = ((doc or {}).get("extensions") or {}).get(DISPLAY_CLOCK)
    return value if isinstance(value, dict) else None


async def async_setup_entry(hass: HomeAssistant, entry: JblBarConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [JblBarNight(coordinator, "night")]
    if advanced_controls(coordinator.data):
        entities.append(JblBarSmartMode(coordinator, "smart_mode"))
    if clock_state(coordinator.data) is not None:
        entities.append(JblBarClock(coordinator, "display_clock"))
    add(entities)


class JblBarClock(JblBarEntity, SwitchEntity):
    """The time on the front display while the bar is in standby, below every message and timer.

    Turning it on sends Home Assistant's time zone: the bar's clock is UTC.
    """

    _attr_icon = "mdi:clock-digital"

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self.entity_id = "switch.jbl_display_clock"  # suggested, so dashboard templates can name it in any language

    @property
    def is_on(self) -> bool | None:
        state = clock_state(self.state_doc)
        return bool(state.get("enabled")) if state is not None else None

    async def _set(self, on: bool) -> None:
        parameters: dict[str, Any] = {"enabled": on}
        if on and self.hass.config.time_zone:
            parameters["tz"] = self.hass.config.time_zone
        await self.extension_action(DISPLAY_CLOCK, "set", parameters, "display_unsupported")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class JblBarNight(JblBarEntity, SwitchEntity):
    _attr_icon = "mdi:weather-night"

    @property
    def is_on(self) -> bool | None:
        return self.sound.get("night")

    async def _set(self, on: bool) -> None:
        if self.is_on is not None and self.is_on != on:
            await self.coordinator.async_action("night_toggle")

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class JblBarSmartMode(JblBarEntity, SwitchEntity):
    """On = Smart Mode, off = Standard (the bar returns to Smart at power-on)."""

    _attr_icon = "mdi:auto-fix"
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool | None:
        mode = self.state_doc.get("mode")
        return None if mode not in ("Smart", "Standard") else mode == "Smart"

    @property
    def available(self) -> bool:
        return super().available and self.awake

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self.is_on is False:
            await self.coordinator.async_action("smart")

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.is_on:
            await self.coordinator.async_action("standard")
