"""Rear speaker docking and Bluetooth connection."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import JblBarConfigEntry
from .entity import JblBarEntity
from .timers import timer_list, timers_installed


async def async_setup_entry(hass: HomeAssistant, entry: JblBarConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    add([JblBarRearDocked(coordinator, "rear_docked"), JblBarBluetooth(coordinator, "bluetooth_connected"),
         JblBarCommandRunning(coordinator, "command_running")])
    if timers_installed(coordinator.data):
        add([JblBarTimerRinging(coordinator, "timer_ringing")])


class JblBarRearDocked(JblBarEntity, BinarySensorEntity):
    _attr_icon = "mdi:speaker-wireless"

    @property
    def is_on(self) -> bool | None:
        return self.sound.get("rear_docked")


class JblBarBluetooth(JblBarEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool | None:
        return (self.state_doc.get("bluetooth") or {}).get("connected", False)


class JblBarCommandRunning(JblBarEntity, BinarySensorEntity):
    """On while a command runs: from Home Assistant, from another client, or a calibration.

    Scripts can wait on it, e.g. wait_template: "{{ is_state('binary_sensor.jbl_bar_9_1_command_running', 'off') }}".
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:progress-clock"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return self.coordinator.busy

    @property
    def extra_state_attributes(self) -> dict:
        control = self.state_doc.get("control") or {}
        action = self.coordinator.local_action or control.get("action")
        source = "home_assistant" if self.coordinator.local_action else "remote" if self.coordinator.remote_busy else None
        return {"action": action, "source": source}


class JblBarTimerRinging(JblBarEntity, BinarySensorEntity):
    """On while a timer rings on the bar (until a key on the JBL remote, a cancel, or 10 minutes).

    Automations can use it to tell a phone as well.
    """

    _attr_icon = "mdi:alarm-bell"

    def _ringing(self) -> list[dict]:
        return [t for t in timer_list(self.state_doc) if t.get("ringing")]

    @property
    def is_on(self) -> bool:
        return bool(self._ringing())

    @property
    def extra_state_attributes(self) -> dict:
        return {"names": [t.get("text") or "" for t in self._ringing()]}
