"""Notify entity: notifications on the bar's front display."""
from __future__ import annotations

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DISPLAY_NOTIFY_PASSES, DISPLAY_TEXT_MAX
from .coordinator import JblBarConfigEntry
from .entity import JblBarEntity


async def async_setup_entry(hass: HomeAssistant, entry: JblBarConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([JblBarDisplayNotify(entry.runtime_data, "display")])


def display_text(message: str, title: str | None) -> str:
    """The title goes in front of the message when both fit on the display."""
    message = " ".join(message.split())
    title = " ".join((title or "").split())
    if title and len(title) + 1 + len(message) <= DISPLAY_TEXT_MAX:
        return f"{title} {message}"
    return message


class JblBarDisplayNotify(JblBarEntity, NotifyEntity):
    """notify.send_message shows the message on the display, two passes.

    The bar shows it on or in standby without waking up. For repeats, a
    duration or replacement by id, use jbl_bar_91.display_message.
    """

    _attr_supported_features = NotifyEntityFeature.TITLE

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        await self.display_action("show", {"text": display_text(message, title), "repeat": DISPLAY_NOTIFY_PASSES})
