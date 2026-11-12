"""One-shot controls."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import JblBarConfigEntry, JblBarCoordinator
from .entity import JblBarEntity, advanced_controls, setup_controls
from .lines import LINES, JblBarMessageLine, JblBarTimerLine
from .messages import messages_installed
from .timers import timers_installed

BUTTONS = {"standard_mode": ("standard", "mdi:auto-fix"), "bluetooth_pairing": ("bluetooth_pair", "mdi:bluetooth-settings")}


async def async_setup_entry(hass: HomeAssistant, entry: JblBarConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    buttons = dict(BUTTONS)
    if advanced_controls(coordinator.data):
        # The Smart mode switch replaces the one-way Standard button; drop the
        # button left over from older versions instead of keeping it orphaned.
        del buttons["standard_mode"]
        registry = er.async_get(hass)
        if old := registry.async_get_entity_id(Platform.BUTTON, DOMAIN, f"{entry.unique_id}_standard_mode"):
            registry.async_remove(old)
    entities: list[JblBarButton] = [JblBarButton(coordinator, key, action, icon) for key, (action, icon) in buttons.items()]
    if setup_controls(coordinator.data):
        entities += [JblBarCalibrate(coordinator, "calibrate", "calibrate", "mdi:surround-sound"),
                     JblBarSubPair(coordinator, "sub_pair", "sub_pair", "mdi:speaker-wireless")]
    # Clear every display message (timers are not affected). The button for the
    # unnamed message alone went away with the message lines: drop it if left over.
    entities.append(JblBarClearMessages(coordinator, "clear_messages", "mdi:message-off-outline", None))
    registry = er.async_get(hass)
    if old := registry.async_get_entity_id(Platform.BUTTON, DOMAIN, f"{entry.unique_id}_clear_unnamed_message"):
        registry.async_remove(old)
    # One button per timer and per message, for dashboard lists (lines.py).
    if timers_installed(coordinator.data):
        entities += [JblBarTimerLine(coordinator, n) for n in range(1, LINES + 1)]
    if messages_installed(coordinator.data):
        entities += [JblBarMessageLine(coordinator, n) for n in range(1, LINES + 1)]
    # Restart the soundbar: in the device's configuration, for when it stops responding.
    entities.append(JblBarRestart(coordinator, "restart"))
    add(entities)


class JblBarRestart(JblBarEntity, ButtonEntity):
    """Restart the soundbar (remote extension bar91.system). Dashboards should add a confirmation."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.extension_action("bar91.system", "reboot", {"confirm": True}, "restart_unsupported")


class JblBarClearMessages(JblBarEntity, ButtonEntity):
    """Clear every message."""

    def __init__(self, coordinator: JblBarCoordinator, key: str, icon: str, parameters: dict | None) -> None:
        super().__init__(coordinator, key)
        self._attr_icon = icon
        self._parameters = parameters

    async def async_press(self) -> None:
        await self.display_action("cancel", self._parameters)


class JblBarButton(JblBarEntity, ButtonEntity):
    def __init__(self, coordinator: JblBarCoordinator, key: str, action: str, icon: str) -> None:
        super().__init__(coordinator, key)
        self._action = action
        self._attr_icon = icon

    async def async_press(self) -> None:
        await self.coordinator.async_action(self._action)


def _measuring(setup: dict) -> bool:
    phase = setup.get("calibration") or ""
    return "starting" in phase.lower() or phase == "Measuring"


class JblBarCalibrate(JblBarButton):
    """Start the next calibration step; the bar measures for about 35 s."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        return (super().available and self.awake and self.sound.get("rear_docked") is False
                and not _measuring(self.setup) and not self.setup.get("sub_pairing"))


class JblBarSubPair(JblBarButton):
    """Open subwoofer pairing; the subwoofer's own button finishes it."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        return super().available and self.awake and not _measuring(self.setup) and not self.setup.get("sub_pairing")
