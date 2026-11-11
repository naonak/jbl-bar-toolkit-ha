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
    """The markdown under the timers list: warnings and the timers beyond the four lines."""
    content = next(c for c in load("timers-card.yaml")["cards"] if c["type"] == "markdown")["content"]
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


async def test_card_without_package(hass: HomeAssistant, remote) -> None:
    remote.timers = []
    await setup(hass, remote)
    assert "timers package is missing" in card_text(hass)


def slot(hass: HomeAssistant, n: int):
    return hass.states.get(f"sensor.jbl_timer_{n}")


async def test_card_and_scripts(hass: HomeAssistant, remote) -> None:
    """Nothing in the card or package names an entity of the bar: they find it."""
    remote.timers = []
    await setup(hass, remote)
    await setup_package(hass)
    assert card_text(hass).strip() == ""
    assert [slot(hass, n).state for n in range(1, 5)] == ["unavailable"] * 4

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
    first, second = slot(hass, 1), slot(hass, 2)
    assert first.name == "🔔 Timer – ringing" and first.attributes["icon"] == "mdi:bell-ring", first
    assert second.name.startswith("PIZZA – ends at ") and second.name.endswith("(in 10 min)"), second.name
    assert second.attributes["timer_id"] == "t2" and second.attributes["device_class"] == "timestamp"
    assert slot(hass, 3).state == "unavailable"

    await hass.services.async_call("script", "jbl_timer_add_minute", {}, blocking=True)
    assert remote.timer_log[-1] == ("extend", {"id": "t2", "add_s": 60})  # the next one running (Pizza; the other rings)

    # The Cancel button of a line stops that timer only.
    await hass.services.async_call("script", "jbl_timer_cancel_slot", {"slot": 2}, blocking=True)
    assert remote.timer_log[-1] == ("cancel", {"id": "t2"})
    assert [t["id"] for t in remote.timers] == ["t1"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert slot(hass, 2).state == "unavailable"
    await hass.services.async_call("script", "jbl_timer_cancel_slot", {"slot": 3}, blocking=True)  # an empty line: nothing
    assert remote.timer_log[-1] == ("cancel", {"id": "t2"})

    for name in ("Tea", "Eggs", "Rice", "Bread"):
        await hass.services.async_call("input_text", "set_value", {"entity_id": "input_text.jbl_timer_name", "value": name}, blocking=True)
        await hass.services.async_call("script", "jbl_timer_start", {}, blocking=True)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert "And 1 more" in card_text(hass)
    assert all(slot(hass, n).state != "unavailable" for n in range(1, 5))

    await hass.services.async_call("script", "jbl_timer_stop_all", {}, blocking=True)
    assert remote.timers == []


async def test_messages_card_and_scripts(hass: HomeAssistant, remote) -> None:
    """The messages card lists what the remote reports, one line each with Clear; the scripts find the bar."""
    remote.messages = []
    await setup(hass, remote)
    content = next(c for c in load("messages-card.yaml")["cards"] if c["type"] == "markdown")["content"]
    assert "messages package is missing" in Template(content, hass).async_render()
    for domain, config in load("messages-package.yaml").items():
        assert await async_setup_component(hass, domain, {domain: config})
    await hass.async_block_till_done()
    assert Template(content, hass).async_render().strip() == ""
    assert hass.states.get("sensor.jbl_message_1").state == "unavailable"
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
    first, second = hass.states.get("sensor.jbl_message_1"), hass.states.get("sensor.jbl_message_2")
    assert first.name == "CALL GRANDMA – showing, until cleared" and first.state == "showing", first
    assert second.name == "WATER THE PLANTS (plants) – waiting, 3 times left" and second.attributes["message_id"] == "plants", second
    assert hass.states.get("sensor.jbl_message_3").state == "unavailable"
    await hass.services.async_call("script", "jbl_message_cancel_slot", {"slot": 2}, blocking=True)
    assert remote.display_log[-1] == ("cancel", {"id": "plants"})
    await hass.services.async_call("script", "jbl_message_cancel_slot", {"slot": 3}, blocking=True)  # an empty line: nothing
    assert remote.display_log[-1] == ("cancel", {"id": "plants"})


def test_card_rows_pass_the_frontend_checks() -> None:
    """The dashboard refuses a whole card for one bad row: a text row needs a name and a text, both non-empty."""
    def rows(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                yield node
            for value in node.values():
                yield from rows(value)
        elif isinstance(node, list):
            for value in node:
                yield from rows(value)

    found = list(rows(load("timers-card.yaml"))) + list(rows(load("messages-card.yaml")))
    assert found
    for row in found:
        assert row.get("name") and row.get("text"), row
