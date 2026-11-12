"""Level selects (bass, center, Atmos, rear) and Front EQ preset."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EQ_PRESETS
from .coordinator import JblBarConfigEntry, JblBarCoordinator
from .entity import JblBarEntity, eq_chosen_curve, eq_installed
from .switch import DISPLAY_CLOCK, clock_state


@dataclass(frozen=True, kw_only=True)
class Level:
    key: str
    field: str
    action: str
    options: list[str]
    icon: str


LEVELS = [
    Level(key="bass", field="bass", action="bass_next", options=["1", "2", "3", "4", "5"], icon="mdi:speaker"),
    Level(key="center", field="center", action="center_next", options=["0", "1", "2", "3", "4", "5"], icon="mdi:account-voice"),
    Level(key="atmos", field="atmos", action="atmos_next", options=["low", "mid", "high"], icon="mdi:surround-sound"),
    Level(key="rear", field="rear", action="rear_next", options=["low", "mid", "high", "muted"], icon="mdi:speaker-wireless"),
]


async def async_setup_entry(hass: HomeAssistant, entry: JblBarConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    sound = (coordinator.data or {}).get("sound") or {}
    # Center only exists on remotes that include the center-level control.
    entities: list[SelectEntity] = [JblBarLevel(coordinator, level) for level in LEVELS if level.field != "center" or "center" in sound]
    if eq_installed(coordinator.data):
        entities.append(JblBarEqPreset(coordinator, "eq_preset"))
    if clock_state(coordinator.data) is not None:
        entities.append(JblBarClockWhen(coordinator, "display_clock_when"))
    add(entities)


class JblBarClockWhen(JblBarEntity, SelectEntity):
    """Where the clock shows when on: in standby only, or also with the bar on."""

    _attr_icon = "mdi:clock-digital"
    _attr_options = ["standby", "always"]

    def __init__(self, coordinator: JblBarCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self.entity_id = "select.jbl_display_clock_when"  # suggested, for dashboard templates

    @property
    def available(self) -> bool:
        state = clock_state(self.state_doc)
        return super().available and state is not None and "when" in state

    @property
    def current_option(self) -> str | None:
        state = clock_state(self.state_doc) or {}
        return state.get("when") if state.get("when") in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        await self.extension_action(DISPLAY_CLOCK, "set", {"when": option}, "display_unsupported")


class JblBarLevel(JblBarEntity, SelectEntity):
    """A native level that only cycles: step with read-back until reached."""

    def __init__(self, coordinator: JblBarCoordinator, level: Level) -> None:
        super().__init__(coordinator, level.key)
        self._level = level
        self._attr_options = level.options
        self._attr_icon = level.icon

    def _index(self, doc: dict[str, Any]) -> int | None:
        value = (doc.get("sound") or {}).get(self._level.field)
        return value if isinstance(value, int) and 0 <= value < len(self._level.options) else None

    @property
    def current_option(self) -> str | None:
        index = self._index(self.state_doc)
        return None if index is None else self._level.options[index]

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_step_to(
            self._level.action, self._index, self._level.options.index(option), len(self._level.options)
        )


class JblBarEqPreset(JblBarEntity, SelectEntity):
    """Apply one of the browser remote's Front EQ presets."""

    _attr_icon = "mdi:tune-vertical"
    _attr_options = list(EQ_PRESETS)

    @property
    def eq(self) -> dict[str, Any]:
        return self.state_doc.get("eq") or {}

    @property
    def available(self) -> bool:
        # A remote that keeps the EQ saves a preset it cannot apply yet, and a
        # kept EQ can always be reset (Original), like the web page.
        return super().available and (self.eq_ready or self.eq_keeps)

    @property
    def current_option(self) -> str | None:
        gains = eq_chosen_curve(self.state_doc)
        if gains is None:
            return "original"
        return next((name for name, curve in EQ_PRESETS.items() if curve == gains), None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """status: original, active, waiting (kept EQ applied again when Standard audio plays), reset_required…"""
        eq = self.eq
        attrs: dict[str, Any] = {key: eq[key] for key in ("status", "error") if eq.get(key)}
        if "kept" in eq:
            attrs["kept"] = bool(eq["kept"])
        return attrs

    async def async_select_option(self, option: str) -> None:
        curve = EQ_PRESETS[option]
        if any(curve):
            await self.coordinator.async_action("eq_apply", [float(g) for g in curve])
        else:
            await self.coordinator.async_action("eq_reset")
