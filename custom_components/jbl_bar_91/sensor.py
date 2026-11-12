"""Sound mode, Bluetooth details and soundbar diagnostics."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import JblBarConfigEntry, JblBarCoordinator
from .entity import JblBarEntity, eq_installed, setup_controls, smart_mode_memory
from .lines import message_clock, timer_clock
from .messages import messages_installed
from .timers import timers_installed


def _memory(doc: dict[str, Any]) -> float | None:
    memory = (doc.get("system") or {}).get("memory") or {}
    total = memory.get("total_bytes") or 0
    return round(100 * memory.get("used_bytes", 0) / total, 1) if total else None


@dataclass(frozen=True, kw_only=True)
class Description(SensorEntityDescription):
    value: Callable[[dict[str, Any]], Any]
    attributes: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _eq_status(doc: dict[str, Any]) -> str | None:
    """Whether the Front EQ is heard now, waits to apply, or is off (like the web page's badge)."""
    eq = doc.get("eq") or {}
    if len(eq.get("gains_db") or []) != 5:
        return None
    if eq.get("status") == "reset_required":
        return "reset_needed"
    if eq.get("enabled"):
        # Heard only once the remote confirms it (status "active"); in Smart Mode
        # or on another route the applied EQ stays enabled but is not playing.
        return "active" if eq.get("status") in ("active", None) else "waiting"
    if eq.get("status") == "waiting":
        return "waiting"
    return "off"


def _eq_attributes(doc: dict[str, Any]) -> dict[str, Any]:
    eq = doc.get("eq") or {}
    attrs: dict[str, Any] = {"gains_db": eq.get("gains_db")}
    if eq.get("error"):
        attrs["reason"] = eq["error"]
    return attrs


DIAG = EntityCategory.DIAGNOSTIC
SENSORS = [
    Description(key="sound_mode", device_class=SensorDeviceClass.ENUM, options=["standard", "smart", "unknown"],
                icon="mdi:auto-fix", value=lambda d: (d.get("mode") or "Unknown").lower()),
    Description(key="bluetooth_device", icon="mdi:cellphone", value=lambda d: (d.get("bluetooth") or {}).get("peer_name")),
    Description(key="bluetooth_audio", icon="mdi:bluetooth-audio", value=lambda d: (d.get("bluetooth") or {}).get("audio")),
    Description(key="cpu", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
                entity_category=DIAG, icon="mdi:cpu-32-bit", value=lambda d: (d.get("system") or {}).get("cpu_percent")),
    Description(key="memory", native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
                entity_category=DIAG, icon="mdi:memory", value=_memory),
    Description(key="temperature", device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                state_class=SensorStateClass.MEASUREMENT, entity_category=DIAG, value=lambda d: (d.get("system") or {}).get("temperature_c")),
    Description(key="wifi_signal", device_class=SensorDeviceClass.SIGNAL_STRENGTH, native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
                state_class=SensorStateClass.MEASUREMENT, entity_category=DIAG, entity_registry_enabled_default=False,
                value=lambda d: (d.get("wifi") or {}).get("signal_dbm")),
    # Rear speakers' batteries, as last reported (they may lag while the speakers are off).
    Description(key="rear_battery_left", device_class=SensorDeviceClass.BATTERY, native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT, value=lambda d: (d.get("sound") or {}).get("rear_battery_left")),
    Description(key="rear_battery_right", device_class=SensorDeviceClass.BATTERY, native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT, value=lambda d: (d.get("sound") or {}).get("rear_battery_right")),
    Description(key="uptime", device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.SECONDS,
                entity_category=DIAG, entity_registry_enabled_default=False, value=lambda d: d.get("uptime")),
]


SETUP_SENSORS = [
    # Text the bar last showed for the incoming stream, e.g. "DOLBY SURROUND DD+".
    Description(key="audio_format", icon="mdi:surround-sound",
                value=lambda d: (d.get("sound") or {}).get("audio_format") if d.get("power") == "On" else None),
    Description(key="calibration", icon="mdi:tune-vertical", entity_category=DIAG,
                value=lambda d: (d.get("setup") or {}).get("calibration") or "Idle"),
    Description(key="subwoofer", icon="mdi:speaker-wireless", entity_category=DIAG,
                value=lambda d: "Pairing" if (d.get("setup") or {}).get("sub_pairing")
                else (d.get("setup") or {}).get("subwoofer")),
]


# smart_mode_memory: the mode the bar returns to after the next wake.
MEMORY_SENSORS = [
    Description(key="mode_after_standby", icon="mdi:auto-mode", entity_category=DIAG,
                value=lambda d: ((d.get("automation") or {}).get("remembered_mode") or "").lower() or None),
]


# Front EQ helper installed: is the EQ active, waiting to apply, or off?
EQ_SENSORS = [
    Description(key="front_eq_status", device_class=SensorDeviceClass.ENUM, options=["active", "waiting", "off", "reset_needed"],
                icon="mdi:equalizer", value=_eq_status, attributes=_eq_attributes),
]


async def async_setup_entry(hass: HomeAssistant, entry: JblBarConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    descriptions = (SENSORS + (SETUP_SENSORS if setup_controls(entry.runtime_data.data) else [])
                    + (MEMORY_SENSORS if smart_mode_memory(entry.runtime_data.data) else [])
                    + (EQ_SENSORS if eq_installed(entry.runtime_data.data) else []))
    add(JblBarSensor(entry.runtime_data, description) for description in descriptions)
    if timers_installed(entry.runtime_data.data):
        add([JblBarTimers(entry.runtime_data, "timers"), JblBarNextTimer(entry.runtime_data, "next_timer")])
    if messages_installed(entry.runtime_data.data):
        add([JblBarMessages(entry.runtime_data, "messages")])


class JblBarMessages(JblBarEntity, SensorEntity):
    """How many messages are on the bar's display or waiting; each one in the messages attribute."""

    _attr_icon = "mdi:message-text-outline"

    def __init__(self, coordinator: JblBarCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._clock = message_clock(coordinator)
        self._described: list[dict[str, Any]] = []

    def _handle_coordinator_update(self) -> None:
        self._described = self._clock.describe(self.state_doc)
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        self._described = self._clock.describe(self.state_doc)
        await super().async_added_to_hass()

    @property
    def native_value(self) -> int:
        return len(self._described)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"messages": self._described}


class JblBarTimers(JblBarEntity, SensorEntity):
    """How many timers run or ring; each one in the timers attribute (name, ends_at, ringing…)."""

    _attr_icon = "mdi:timer-outline"

    @property
    def native_value(self) -> int:
        return len(timer_clock(self.coordinator).describe(self.state_doc))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"timers": timer_clock(self.coordinator).describe(self.state_doc)}


class JblBarNextTimer(JblBarEntity, SensorEntity):
    """When the next running timer ends (dashboards show it as a countdown)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:timer-sand"

    def _next(self) -> dict[str, Any] | None:
        running = [t for t in timer_clock(self.coordinator).describe(self.state_doc) if t["ends_at"]]
        return running[0] if running else None

    @property
    def native_value(self) -> Any:
        t = self._next()
        return dt_util.parse_datetime(t["ends_at"]) if t else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        t = self._next()
        return {"name": t["name"], "id": t["id"]} if t else {}


class JblBarSensor(JblBarEntity, SensorEntity):
    entity_description: Description

    def __init__(self, coordinator: JblBarCoordinator, description: Description) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.state_doc)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attributes = self.entity_description.attributes
        return attributes(self.state_doc) if attributes else None
