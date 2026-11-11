"""The dashboard template: the card's text and the package's scripts, against the fake remote."""
from __future__ import annotations

from pathlib import Path

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component

from .test_integration import setup

DASHBOARDS = Path(__file__).parent.parent / "dashboards"


def load(name: str):
    return yaml.safe_load((DASHBOARDS / name).read_text())


def sent(remote, **expected) -> bool:
    action, parameters = remote.timer_log[-1]
    return action == "start" and expected.items() <= parameters.items()


def card_text(hass: HomeAssistant) -> str:
    content = load("timers-card.yaml")["cards"][0]["content"]
    return Template(content, hass).async_render()


async def setup_package(hass: HomeAssistant) -> None:
    package = load("timers-package.yaml")
    for domain, config in package.items():
        assert await async_setup_component(hass, domain, {domain: config})
    await hass.async_block_till_done()


async def test_card_without_timer_entities(hass: HomeAssistant, remote) -> None:
    remote.timers = None
    await setup(hass, remote)
    assert "No *Timers* entity" in card_text(hass)


async def test_card_and_scripts(hass: HomeAssistant, remote) -> None:
    """Nothing in the card or package names an entity of the bar: they find it."""
    remote.timers = []
    await setup(hass, remote)
    await setup_package(hass)
    assert card_text(hass).strip() == "No timer running."

    await hass.services.async_call("script", "jbl_timer_quick", {"minutes": 5}, blocking=True)
    assert sent(remote, duration_s=300, sound="unless_tv")
    await hass.services.async_call("input_text", "set_value", {"entity_id": "input_text.jbl_timer_name", "value": "Pizza"}, blocking=True)
    await hass.services.async_call("input_boolean", "turn_on", {"entity_id": "input_boolean.jbl_timer_show_time"}, blocking=True)
    await hass.services.async_call("script", "jbl_timer_start", {}, blocking=True)
    assert sent(remote, text="Pizza", duration_s=600, countdown=True, sound="unless_tv")

    coordinator = hass.config_entries.async_entries("jbl_bar_91")[0].runtime_data
    remote.timers[0]["ringing"], remote.timers[0]["remaining_ms"] = True, 0
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    text = card_text(hass)
    assert "**Timer**: 🔔 ringing" in text and "ends at" in text, text
    assert "in 10 min" in text, text

    await hass.services.async_call("script", "jbl_timer_add_minute", {}, blocking=True)
    assert remote.timer_log[-1] == ("extend", {"id": "t2", "add_s": 60})  # the next one running (Pizza; the other rings)
    await hass.services.async_call("script", "jbl_timer_stop_all", {}, blocking=True)
    assert remote.timers == []


async def test_messages_card_and_scripts(hass: HomeAssistant, remote) -> None:
    """The messages card lists what the remote reports; the scripts send and clear, finding the bar themselves."""
    remote.messages = []
    await setup(hass, remote)
    for domain, config in load("messages-package.yaml").items():
        assert await async_setup_component(hass, domain, {domain: config})
    await hass.async_block_till_done()
    content = load("messages-card.yaml")["cards"][0]["content"]
    assert Template(content, hass).async_render().strip() == "No message on the bar."
    for length, expect in [("Until cleared", {"forever": True}), ("3 times", {"repeat": 3}), ("1 hour", {"duration_s": 3600})]:
        await hass.services.async_call("input_text", "set_value", {"entity_id": "input_text.jbl_message_text", "value": "Call grandma"}, blocking=True)
        await hass.services.async_call("input_select", "select_option", {"entity_id": "input_select.jbl_message_length", "option": length}, blocking=True)
        await hass.services.async_call("script", "jbl_message_send", {}, blocking=True)
        assert remote.display_log[-1] == ("show", {"text": "Call grandma", **expect, "stop_on_key": True})
        assert hass.states.get("input_text.jbl_message_text").state == ""
    await hass.services.async_call("script", "jbl_message_clear_unnamed", {}, blocking=True)
    await hass.services.async_call("script", "jbl_message_clear_all", {}, blocking=True)
    assert remote.display_log[-2:] == [("cancel", {"id": "default"}), ("cancel", None)]
    remote.messages = [
        {"id": "default", "named": False, "text": "CALL GRANDMA", "mode": "forever", "showing": True},
        {"id": "plants", "named": True, "text": "WATER THE PLANTS", "mode": "passes", "passes_left": 3, "showing": False},
    ]
    coordinator = hass.config_entries.async_entries("jbl_bar_91")[0].runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    text = Template(content, hass).async_render()
    assert "- **CALL GRANDMA**: showing, until cleared" in text and "- **WATER THE PLANTS** (plants): waiting, 3 times left" in text, text
