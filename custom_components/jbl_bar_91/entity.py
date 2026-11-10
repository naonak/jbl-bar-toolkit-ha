"""Base entity."""
from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DISPLAY_MESSAGE, DOMAIN
from .coordinator import JblBarCoordinator


EQ_NOT_INSTALLED = "EQ support is not installed"


def eq_installed(doc: dict[str, Any] | None) -> bool:
    """True when the remote was built with the Front EQ helper.

    The remote only reports EQ as available while the bar is on, in Standard
    mode, with a supported audio route, so entities are created whenever the
    helper exists and are unavailable the rest of the time.
    """
    eq = (doc or {}).get("eq")
    return isinstance(eq, dict) and eq.get("error") != EQ_NOT_INSTALLED


def eq_chosen_curve(doc: dict[str, Any] | None) -> list[float] | None:
    """The Front EQ curve the owner chose, or None for the original tuning.

    An applied EQ reports enabled. A remote that keeps the EQ until Reset
    also reports it while it waits to be applied again (kept, status
    "waiting", e.g. after a source change), with enabled false.
    """
    eq = (doc or {}).get("eq") or {}
    gains = eq.get("gains_db") or []
    if len(gains) != 5:
        return None
    if eq.get("enabled") or (eq.get("kept") and eq.get("status") == "waiting"):
        return [float(g) for g in gains]
    return None


def advanced_controls(doc: dict[str, Any] | None) -> bool:
    """True when the remote has the advanced controls (Smart Mode, audio sync).

    Both shipped together; the audio sync value is the only visible marker.
    """
    return "av_sync_ms" in ((doc or {}).get("sound") or {})


BASS_OFFSET = "bar91.bass-offset"


def bass_offset_state(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """The bass offset extension's state (offset_db, status, error), if included."""
    value = ((doc or {}).get("extensions") or {}).get(BASS_OFFSET)
    return value if isinstance(value, dict) else None


def smart_mode_memory(doc: dict[str, Any] | None) -> bool:
    """True when the remote restores the mode chosen before standby (smart_mode_memory)."""
    return ((doc or {}).get("automation") or {}).get("remembered_mode") in ("Standard", "Smart")


def setup_controls(doc: dict[str, Any] | None) -> bool:
    """True when the remote reads the bar's display (calibration, subwoofer pairing, audio format)."""
    return isinstance((doc or {}).get("setup"), dict)


class JblBarEntity(CoordinatorEntity[JblBarCoordinator]):
    """Entity backed by the remote's state document."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: JblBarCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        assert entry is not None and entry.unique_id is not None
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_translation_key = None if key == "media_player" else key.rsplit("_", 1)[0] if key.startswith("eq_band_") else key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name="JBL Bar 9.1",
            manufacturer="JBL",
            model="Bar 9.1 True Wireless Surround",
            configuration_url=f"http://{coordinator.client.host}",
        )

    @property
    def state_doc(self) -> dict[str, Any]:
        return self.coordinator.data or {}

    async def display_action(self, action: str, parameters: dict[str, Any] | None) -> None:
        """Send a front-display message action (remote extension bar91.display-message)."""
        await self.extension_action(DISPLAY_MESSAGE, action, parameters, "display_unsupported")

    async def extension_action(self, extension: str, action: str, parameters: dict[str, Any] | None, unsupported: str) -> None:
        """Send an extension action; a remote without the extension is reported with the unsupported message."""
        try:
            await self.coordinator.async_action(f"{extension}.{action}", parameters=parameters)
        except HomeAssistantError as err:
            if (err.translation_placeholders or {}).get("error") == "unknown control":
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key=unsupported) from err
            raise

    @property
    def setup(self) -> dict[str, Any]:
        return self.state_doc.get("setup") or {}

    @property
    def sound(self) -> dict[str, Any]:
        return self.state_doc.get("sound") or {}

    @property
    def available(self) -> bool:
        return super().available and bool(self.state_doc.get("available"))

    @property
    def eq_ready(self) -> bool:
        return bool((self.state_doc.get("eq") or {}).get("available"))

    @property
    def eq_keeps(self) -> bool:
        """The remote keeps the EQ until Reset (it reports eq.kept), and also saves
        one it cannot apply yet (standby, Smart Mode, another audio route)."""
        eq = self.state_doc.get("eq") or {}
        return isinstance(eq.get("kept"), bool) and eq.get("error") != EQ_NOT_INSTALLED

    @property
    def awake(self) -> bool:
        return self.coordinator.awake
