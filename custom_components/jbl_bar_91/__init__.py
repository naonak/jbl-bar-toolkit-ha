"""JBL Bar 9.1 integration, through the soundbar's local browser remote."""
from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import JblBarClient, JblBarError
from .const import DOMAIN, SUPPORTED_MODEL
from .coordinator import JblBarConfigEntry, JblBarCoordinator

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
    coordinator.start_push()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JblBarConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
