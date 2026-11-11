"""JBL Bar 9.1 integration, through the soundbar's local browser remote."""
from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import JblBarClient, JblBarError
from .const import DOMAIN, SUPPORTED_MODEL
from .coordinator import JblBarConfigEntry, JblBarCoordinator
from .entity import (
    advanced_controls,
    bass_offset_state,
    eq_installed,
    setup_controls,
    smart_mode_memory,
)
from .messages import messages_installed
from .timers import timers_installed

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NOTIFY,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


def features(doc: dict[str, Any] | None) -> frozenset[str]:
    """What the toolkit remote offers that decides which entities exist."""
    checks = {
        "advanced": advanced_controls(doc), "bass_offset": bass_offset_state(doc) is not None,
        "eq": eq_installed(doc), "setup": setup_controls(doc), "memory": smart_mode_memory(doc),
        "timers": timers_installed(doc), "messages": messages_installed(doc),
    }
    return frozenset(name for name, present in checks.items() if present)


async def async_setup_entry(hass: HomeAssistant, entry: JblBarConfigEntry) -> bool:
    client = JblBarClient(async_get_clientsession(hass), entry.data[CONF_HOST])
    coordinator = JblBarCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    try:
        model = await client.get_model()
    except JblBarError as err:
        raise ConfigEntryNotReady(str(err)) from err
    if model not in (None, SUPPORTED_MODEL):
        # Never create Bar 9.1 entities for another bar's toolkit remote.
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="unsupported_model", translation_placeholders={"model": model})
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    known = features(coordinator.data)

    @callback
    def new_features() -> None:
        # The bar's remote was updated while Home Assistant ran (timers, messages…):
        # reload once so their entities appear. A feature that goes away only makes
        # its entities unavailable, so a restarting bar never reloads in a loop.
        if features(coordinator.data) - known:
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(coordinator.async_add_listener(new_features))
    coordinator.start_push()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JblBarConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
