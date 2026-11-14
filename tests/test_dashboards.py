"""The dashboard template: the card's text and the package's scripts, against the fake remote."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import yaml
from homeassistant.const import EVENT_HOMEASSISTANT_START
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from .test_integration import setup

DASHBOARDS = Path(__file__).parent.parent / "dashboards"


def load(name: str):
    return yaml.safe_load((DASHBOARDS / name).read_text())


def sent(remote, **expected) -> bool:
    action, parameters = remote.timer_log[-1]
    return action == "start" and expected.items() <= parameters.items()


def card_text(hass: HomeAssistant) -> str:
    """The markdown under the timers list: warnings and the timers beyond the eight lines."""
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


def line(hass: HomeAssistant, kind: str, n: int):
    """The integration's line button N (button.jbl_timer_line_N / button.jbl_message_line_N)."""
    return hass.states.get(f"button.jbl_{kind}_line_{n}")


async def refresh(hass: HomeAssistant) -> None:
    await hass.config_entries.async_entries("jbl_bar_91")[0].runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_card_and_scripts(hass: HomeAssistant, remote) -> None:
    """Nothing in the card or package names an entity of the bar: they find it."""
    remote.timers = []
    await setup(hass, remote)
    await setup_package(hass)
    assert card_text(hass).strip() == ""
    assert [line(hass, "timer", n).state for n in range(1, 9)] == ["unavailable"] * 8

    await hass.services.async_call("script", "jbl_timer_quick", {"minutes": 5}, blocking=True)
    assert sent(remote, duration_s=300, sound="unless_tv")
    await hass.services.async_call("input_text", "set_value", {"entity_id": "input_text.jbl_timer_name", "value": "Pizza"}, blocking=True)
    await hass.services.async_call("input_boolean", "turn_on", {"entity_id": "input_boolean.jbl_timer_show_time"}, blocking=True)
    await hass.services.async_call("script", "jbl_timer_start", {}, blocking=True)
    assert sent(remote, text="Pizza", duration_s=600, countdown=True, sound="unless_tv")

    remote.timers[0]["ringing"], remote.timers[0]["remaining_ms"] = True, 0
    await refresh(hass)
    first, second = line(hass, "timer", 1), line(hass, "timer", 2)
    assert first.name == "🔔 Timer – ringing" and first.attributes["icon"] == "mdi:bell-ring", first
    assert second.name.startswith("PIZZA – ends at ") and second.attributes["id"] == "t2", second
    assert line(hass, "timer", 3).state == "unavailable"

    await hass.services.async_call("script", "jbl_timer_add_minute", {}, blocking=True)
    assert remote.timer_log[-1] == ("extend", {"id": "t2", "add_s": 60})  # the next one running (Pizza; the other rings)

    # A line's button stops that timer only.
    await hass.services.async_call("button", "press", {"entity_id": "button.jbl_timer_line_2"}, blocking=True)
    assert remote.timer_log[-1] == ("cancel", {"id": "t2"})
    assert [t["id"] for t in remote.timers] == ["t1"]
    await refresh(hass)
    assert line(hass, "timer", 2).state == "unavailable"

    for n in range(8):
        await hass.services.async_call("input_text", "set_value", {"entity_id": "input_text.jbl_timer_name", "value": f"T{n}"}, blocking=True)
        await hass.services.async_call("script", "jbl_timer_start", {}, blocking=True)
    remote.timers.append({"id": "t99", "text": "EXTRA", "remaining_ms": 9_000_000, "ringing": False})  # beyond the remote's 8
    await refresh(hass)
    assert "And 2 more" in card_text(hass)  # t1, eight more and one beyond
    assert all(line(hass, "timer", n).state != "unavailable" for n in range(1, 9))

    await hass.services.async_call("script", "jbl_timer_stop_all", {}, blocking=True)
    assert remote.timers == []


async def test_messages_card_and_scripts(hass: HomeAssistant, remote) -> None:
    """The messages card lists what the remote reports, one line each; the scripts find the bar."""
    remote.messages = []
    await setup(hass, remote)
    content = next(c for c in load("messages-card.yaml")["cards"] if c["type"] == "markdown")["content"]
    assert "messages package is missing" in Template(content, hass).async_render()
    for domain, config in load("messages-package.yaml").items():
        assert await async_setup_component(hass, domain, {domain: config})
    await hass.async_block_till_done()
    assert Template(content, hass).async_render().strip() == ""
    assert line(hass, "message", 1).state == "unavailable"
    for length, expect in [("Until cleared", {"forever": True}), ("3 times", {"repeat": 3}), ("1 hour", {"duration_s": 3600})]:
        await hass.services.async_call("input_text", "set_value", {"entity_id": "input_text.jbl_message_text", "value": "Call grandma"}, blocking=True)
        await hass.services.async_call("input_select", "select_option", {"entity_id": "input_select.jbl_message_length", "option": length}, blocking=True)
        await hass.services.async_call("script", "jbl_message_send", {}, blocking=True)
        assert remote.display_log[-1] == ("show", {"text": "Call grandma", **expect, "stop_on_key": True})
        assert hass.states.get("input_text.jbl_message_text").state == ""
    await hass.services.async_call("script", "jbl_message_clear_all", {}, blocking=True)
    assert remote.display_log[-1] == ("cancel", None)
    remote.messages = [
        {"id": "default", "named": False, "text": "CALL GRANDMA", "mode": "forever", "showing": True},
        {"id": "plants", "named": True, "text": "WATER THE PLANTS", "mode": "passes", "passes_left": 3, "showing": False},
    ]
    await refresh(hass)
    first, second = line(hass, "message", 1), line(hass, "message", 2)
    assert first.name == "CALL GRANDMA – until cleared", first
    # No passes left in the name: it would change at every pass.
    assert second.name == "WATER THE PLANTS (plants)" and second.attributes["id"] == "plants", second
    assert line(hass, "message", 3).state == "unavailable"
    await hass.services.async_call("button", "press", {"entity_id": "button.jbl_message_line_2"}, blocking=True)
    assert remote.display_log[-1] == ("cancel", {"id": "plants"})
    # The line follows the message (the card's entity rows redraw on a new name).
    remote.messages = [{"id": "default", "named": False, "text": "DDD", "mode": "passes", "passes_left": 3, "showing": True}]
    await refresh(hass)
    assert line(hass, "message", 1).name == "DDD"
    await hass.services.async_call("button", "press", {"entity_id": "button.jbl_message_line_1"}, blocking=True)
    assert remote.display_log[-1] == ("cancel", {"id": "default"})


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
    # A button row draws its name once, at page load: the lines must be entity rows.
    for card in ("timers-card.yaml", "messages-card.yaml"):
        assert "type: button\n          entity:" not in (DASHBOARDS / card).read_text(), card


async def test_clock_schedule(hass: HomeAssistant, remote, freezer) -> None:
    """With the schedule on, the package's automation turns the standby clock on inside the hours, off outside."""
    freezer.move_to(dt_util.now().replace(hour=12, minute=0, second=0))  # far from midnight
    remote.messages, remote.clock = [], {"enabled": False, "tz": ""}
    await setup(hass, remote)
    for domain, config in load("messages-package.yaml").items():
        assert await async_setup_component(hass, domain, {domain: config})
    await hass.async_block_till_done()
    now = dt_util.now()

    async def hours(start, end) -> None:
        for entity, when in (("input_datetime.jbl_clock_from", start), ("input_datetime.jbl_clock_until", end)):
            await hass.services.async_call("input_datetime", "set_datetime", {"entity_id": entity, "time": when.strftime("%H:%M:00")}, blocking=True)
        await hass.async_block_till_done()

    await hours(now - timedelta(hours=1), now + timedelta(hours=1))
    assert remote.clock["enabled"] is False  # schedule off: nothing happens
    await hass.services.async_call("input_boolean", "turn_on", {"entity_id": "input_boolean.jbl_clock_scheduled"}, blocking=True)
    await hass.async_block_till_done()
    assert remote.clock["enabled"] is True, remote.display_log
    await hours(now + timedelta(hours=1), now + timedelta(hours=2))  # now is outside
    assert remote.clock["enabled"] is False, remote.display_log
    await hours(now + timedelta(hours=2), now + timedelta(hours=1))  # over midnight, now inside
    assert remote.clock["enabled"] is True, remote.display_log
    await hours(now, now)  # the same time twice: all day
    assert remote.clock["enabled"] is True

    # Turned off by hand, it stays off: Home Assistant starting again, or the
    # bar coming back after being out of reach, does not apply the schedule.
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.jbl_display_clock"}, blocking=True)
    await hass.async_block_till_done()
    assert remote.clock["enabled"] is False
    hass.bus.async_fire(EVENT_HOMEASSISTANT_START)
    hass.states.async_set("switch.jbl_display_clock", "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set("switch.jbl_display_clock", "off")
    await hass.async_block_till_done()
    assert remote.clock["enabled"] is False, remote.display_log

    # The schedule changed while the bar is out of reach: applied once it is back.
    # (The automation then waits: not async_block_till_done, which would wait for it.)
    async def settle() -> None:
        for _ in range(50):
            await asyncio.sleep(0)

    hass.states.async_set("switch.jbl_display_clock", "unavailable")
    await hass.services.async_call("input_boolean", "turn_off", {"entity_id": "input_boolean.jbl_clock_scheduled"}, blocking=True)
    await hass.services.async_call("input_boolean", "turn_on", {"entity_id": "input_boolean.jbl_clock_scheduled"}, blocking=True)
    await settle()
    assert remote.clock["enabled"] is False
    hass.states.async_set("switch.jbl_display_clock", "off")
    await settle()
    assert remote.clock["enabled"] is True, remote.display_log
