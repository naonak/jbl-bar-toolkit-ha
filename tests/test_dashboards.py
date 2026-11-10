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

    await hass.services.async_call("script", "jbl_timer_stop_all", {}, blocking=True)
    assert remote.timers == []
