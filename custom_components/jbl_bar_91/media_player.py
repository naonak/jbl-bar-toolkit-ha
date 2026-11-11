"""Media player: power, volume, mute, source, playback and now playing."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature as F,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, SOURCES, VOLUME_MAX
from .timers import TIMER, TIMER_RING_DEFAULT, TIMER_SOUNDS, TIMER_VOLUME_DEFAULT, fold_name, timer_list
from .coordinator import JblBarConfigEntry
from .entity import JblBarEntity

PLAYBACK = {
    F.PLAY: "media_play",
    F.PAUSE: "media_pause",
    F.STOP: "media_stop",
    F.NEXT_TRACK: "media_next",
    F.PREVIOUS_TRACK: "media_previous",
}


async def async_setup_entry(hass: HomeAssistant, entry: JblBarConfigEntry, add: AddConfigEntryEntitiesCallback) -> None:
    add([JblBarMediaPlayer(entry.runtime_data, "media_player")])
    platform = entity_platform.async_get_current_platform()
    # Front display messages (remote extension bar91.display-message).
    platform.async_register_entity_service(
        "display_message",
        {
            vol.Required("message"): vol.All(cv.string, vol.Length(min=1, max=64)),
            vol.Optional("id"): vol.All(cv.string, vol.Match(r"^[a-z0-9_-]{1,32}$")),
            vol.Optional("repeat"): vol.All(vol.Coerce(int), vol.Range(min=1, max=99)),
            vol.Optional("duration"): cv.positive_time_period,
            vol.Optional("forever"): cv.boolean,
            vol.Optional("clear_on_key"): cv.boolean,
        },
        "async_display_message",
    )
    platform.async_register_entity_service(
        "display_cancel",
        {vol.Optional("id"): vol.All(cv.string, vol.Match(r"^[a-z0-9_-]{1,32}$"))},
        "async_display_cancel",
    )
    # Timers on the front display (remote extension bar91.timer).
    platform.async_register_entity_service(
        "timer_start",
        {
            vol.Required("duration"): cv.positive_time_period,
            vol.Optional("name"): vol.All(cv.string, vol.Length(max=64)),
            vol.Optional("show_time_left"): cv.boolean,
            vol.Optional("sound"): vol.In(TIMER_SOUNDS),
            vol.Optional("sound_volume"): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
            vol.Optional("ring_for"): cv.positive_time_period,
        },
        "async_timer_start",
    )
    platform.async_register_entity_service(
        "timer_cancel",
        {
            vol.Optional("name"): vol.All(cv.string, vol.Length(max=64)),
            vol.Optional("id"): vol.All(cv.string, vol.Match(r"^t[0-9]{1,9}$")),
            vol.Optional("all"): cv.boolean,
        },
        "async_timer_cancel",
    )
    platform.async_register_entity_service(
        "timer_extend",
        {
            vol.Optional("duration"): cv.positive_time_period,
            vol.Optional("name"): vol.All(cv.string, vol.Length(max=64)),
            vol.Optional("id"): vol.All(cv.string, vol.Match(r"^t[0-9]{1,9}$")),
        },
        "async_timer_extend",
    )


class JblBarMediaPlayer(JblBarEntity, MediaPlayerEntity):
    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_source_list = [name for name, _ in SOURCES.values()]

    @property
    def supported_features(self) -> F:
        features = F.TURN_ON | F.TURN_OFF | F.VOLUME_SET | F.VOLUME_STEP | F.VOLUME_MUTE | F.SELECT_SOURCE
        controls = self.state_doc.get("media_controls") or []
        for feature, action in PLAYBACK.items():
            if action in controls:
                features |= feature
        return features

    @property
    def _cast(self) -> dict[str, Any]:
        return ((self.state_doc.get("streaming") or {}).get("cast")) or {}

    @property
    def state(self) -> MediaPlayerState | None:
        power = self.state_doc.get("power")
        if power == "Standby":
            return MediaPlayerState.OFF
        if power != "On":
            return None
        player = self._cast.get("player_state")
        if player == "PLAYING":
            return MediaPlayerState.PLAYING
        if player == "PAUSED":
            return MediaPlayerState.PAUSED
        if (self.state_doc.get("streaming") or {}).get("active"):
            return MediaPlayerState.PLAYING
        return MediaPlayerState.ON

    @property
    def volume_level(self) -> float | None:
        volume = self.state_doc.get("volume")
        return None if volume is None else volume / VOLUME_MAX

    @property
    def is_volume_muted(self) -> bool | None:
        return self.state_doc.get("muted")

    @property
    def source(self) -> str | None:
        found = SOURCES.get(self.state_doc.get("input", ""))
        return found[0] if found else self.state_doc.get("input")

    @property
    def app_name(self) -> str | None:
        return (self.state_doc.get("streaming") or {}).get("service")

    @property
    def media_title(self) -> str | None:
        return self._cast.get("title")

    @property
    def media_artist(self) -> str | None:
        return self._cast.get("artist")

    @property
    def media_album_name(self) -> str | None:
        return self._cast.get("album")

    async def async_turn_on(self) -> None:
        if self.state_doc.get("power") != "On":
            await self.coordinator.async_action("power")

    async def async_turn_off(self) -> None:
        if self.state_doc.get("power") == "On":
            await self.coordinator.async_action("power")

    async def async_volume_up(self) -> None:
        await self.coordinator.async_action("volume_up")

    async def async_volume_down(self) -> None:
        await self.coordinator.async_action("volume_down")

    async def async_set_volume_level(self, volume: float) -> None:
        target = max(0, min(VOLUME_MAX, round(volume * VOLUME_MAX)))
        await self.coordinator.async_step_to(
            lambda current: "volume_up" if current < target else "volume_down",
            lambda doc: doc.get("volume"),
            target,
            VOLUME_MAX,
        )

    async def async_mute_volume(self, mute: bool) -> None:
        if bool(self.state_doc.get("muted")) != mute:
            await self.coordinator.async_action("mute")

    async def async_select_source(self, source: str) -> None:
        for name, action in SOURCES.values():
            if name == source:
                await self.coordinator.async_action(action)
                return

    async def _playback(self, feature: F) -> None:
        await self.coordinator.async_action(PLAYBACK[feature])

    async def async_media_play(self) -> None:
        await self._playback(F.PLAY)

    async def async_media_pause(self) -> None:
        await self._playback(F.PAUSE)

    async def async_media_stop(self) -> None:
        await self._playback(F.STOP)

    async def async_media_next_track(self) -> None:
        await self._playback(F.NEXT_TRACK)

    async def async_media_previous_track(self) -> None:
        await self._playback(F.PREVIOUS_TRACK)

    async def async_display_message(
        self,
        message: str,
        id: str | None = None,
        repeat: int | None = None,
        duration: timedelta | None = None,
        forever: bool | None = None,
        clear_on_key: bool | None = None,
    ) -> None:
        """Show a message on the bar's front display (on or in standby)."""
        if sum(x is not None and x is not False for x in (repeat, duration, forever)) > 1:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="display_one_length")
        parameters: dict[str, Any] = {"text": message}
        if id:
            parameters["id"] = id
        if repeat is not None:
            parameters["repeat"] = repeat
        if duration is not None:
            seconds = int(duration.total_seconds())
            if not 1 <= seconds <= 86400:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="display_duration")
            parameters["duration_s"] = seconds
        if forever:
            parameters["forever"] = True
        if clear_on_key:
            parameters["stop_on_key"] = True  # any key on the JBL remote clears it
        await self.display_action("show", parameters)

    async def async_display_cancel(self, id: str | None = None) -> None:
        """Stop a message (by id), or every message."""
        await self.display_action("cancel", {"id": id} if id else None)

    async def async_timer_start(
        self,
        duration: timedelta,
        name: str | None = None,
        show_time_left: bool | None = None,
        sound: str | None = None,
        sound_volume: int | None = None,
        ring_for: timedelta | None = None,
    ) -> None:
        """Start a timer on the bar's front display."""
        seconds = int(duration.total_seconds())
        if not 1 <= seconds <= 43200:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="timer_duration")
        parameters: dict[str, Any] = {"duration_s": seconds}
        if name and name.strip():
            parameters["text"] = name
        if show_time_left:
            parameters["countdown"] = True
        sound = sound or "off"
        parameters["sound"] = sound
        if sound != "off":
            parameters["sound_volume"] = sound_volume or TIMER_VOLUME_DEFAULT
            ring = int(ring_for.total_seconds()) if ring_for is not None else TIMER_RING_DEFAULT
            if not 3 <= ring <= 300:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="timer_ring")
            parameters["ring_s"] = ring
        await self.extension_action(TIMER, "start", parameters, "timer_unsupported")

    async def async_timer_cancel(self, name: str | None = None, id: str | None = None, all: bool | None = None) -> None:
        """Stop a timer by name or id, or every timer."""
        timers = timer_list(self.state_doc)
        if all:
            ids = [t["id"] for t in timers]
        elif id:
            ids = [id]
        elif name is not None:
            wanted = fold_name(name)
            ids = [t["id"] for t in timers if (t.get("text") or "") == wanted]
            if not ids:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="timer_not_found", translation_placeholders={"name": name})
        else:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="timer_which")
        for timer_id in ids:
            await self.extension_action(TIMER, "cancel", {"id": timer_id}, "timer_unsupported")

    async def async_timer_extend(self, duration: timedelta | None = None, name: str | None = None, id: str | None = None) -> None:
        """Add time to a running timer (1 minute by default): by name or id, else the next one to end."""
        seconds = int(duration.total_seconds()) if duration is not None else 60
        if not 1 <= seconds <= 3600:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="timer_extend_duration")
        running = [t for t in timer_list(self.state_doc) if not t.get("ringing")]
        if id:
            target = id
        elif name is not None:
            wanted = fold_name(name)
            found = [t["id"] for t in running if (t.get("text") or "") == wanted]
            if not found:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="timer_not_found", translation_placeholders={"name": name})
            target = found[0]
        else:
            if not running:
                raise ServiceValidationError(translation_domain=DOMAIN, translation_key="timer_none_running")
            target = min(running, key=lambda t: int(t.get("remaining_ms") or 0))["id"]
        await self.extension_action(TIMER, "extend", {"id": target, "add_s": seconds}, "timer_extend_unsupported")

