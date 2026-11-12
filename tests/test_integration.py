"""Behaviour tests against the fake remote."""
from __future__ import annotations

import asyncio
from datetime import UTC

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jbl_bar_91.const import DOMAIN

MP = "media_player.jbl_bar_9_1"


async def setup(hass: HomeAssistant, remote) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=remote.host, data={CONF_HOST: remote.host}, title="JBL Bar 9.1")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def until(predicate, timeout: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


async def call(hass, domain, service, entity_id, **data):
    await hass.services.async_call(domain, service, {"entity_id": entity_id, **data}, blocking=True)


async def test_config_flow(hass: HomeAssistant, remote) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: f"http://{remote.host}/"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: remote.host}


async def test_config_flow_errors(hass: HomeAssistant, remote) -> None:
    remote.forbid_ha = True
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: remote.host})
    assert result["errors"] == {"base": "forbidden"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "127.0.0.1:9"})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_entities_from_state(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    mp = hass.states.get(MP)
    assert mp.state == "playing"
    assert mp.attributes["volume_level"] == pytest.approx(10 / 32)
    assert mp.attributes["source"] == "TV"
    assert mp.attributes["media_title"] == "Song" and mp.attributes["media_artist"] == "Band"
    assert hass.states.get("select.jbl_bar_9_1_bass_level").state == "1"
    assert hass.states.get("select.jbl_bar_9_1_center_level").state == "0"
    assert hass.states.get("select.jbl_bar_9_1_atmos_height").state == "mid"
    assert hass.states.get("select.jbl_bar_9_1_front_eq_preset").state == "original"
    assert hass.states.get("switch.jbl_bar_9_1_night_mode").state == "off"
    assert hass.states.get("sensor.jbl_bar_9_1_memory_used").state == "25.0"
    assert hass.states.get("sensor.jbl_bar_9_1_sound_mode").state == "standard"
    assert hass.states.get("binary_sensor.jbl_bar_9_1_bluetooth_connected").state == "on"


async def test_volume_mute_source_power(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    remote.log.clear()
    await call(hass, "media_player", "volume_set", MP, volume_level=13 / 32)
    assert remote.s["volume"] == 13 and remote.actions() == ["volume_up"] * 3
    remote.log.clear()
    await call(hass, "media_player", "volume_mute", MP, is_volume_muted=True)
    await call(hass, "media_player", "volume_mute", MP, is_volume_muted=True)
    assert remote.actions() == ["mute"]
    await call(hass, "media_player", "select_source", MP, source="HDMI")
    assert hass.states.get(MP).attributes["source"] == "HDMI"
    await call(hass, "media_player", "turn_off", MP)
    assert hass.states.get(MP).state == "off"
    remote.log.clear()
    await call(hass, "media_player", "turn_off", MP)
    assert remote.actions() == []


async def test_levels_step_with_readback(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    remote.log.clear()
    await call(hass, "select", "select_option", "select.jbl_bar_9_1_bass_level", option="4")
    assert remote.s["bass"] == 3 and remote.actions() == ["bass_next"] * 3
    remote.log.clear()
    await call(hass, "select", "select_option", "select.jbl_bar_9_1_center_level", option="3")
    assert remote.s["center"] == 3 and remote.actions() == ["center_next"] * 3
    assert hass.states.get("select.jbl_bar_9_1_center_level").state == "3"


async def test_front_eq(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    await call(hass, "select", "select_option", "select.jbl_bar_9_1_front_eq_preset", option="less_bass")
    assert remote.s["eq"] == [-4, -2, 0, 0, 0]
    await call(hass, "number", "set_value", "number.jbl_bar_9_1_front_eq_8_khz", value=-2.5)
    assert remote.s["eq"] == [-4, -2, 0, 0, -2.5]
    assert hass.states.get("select.jbl_bar_9_1_front_eq_preset").state == "unknown"
    remote.log.clear()
    await call(hass, "select", "select_option", "select.jbl_bar_9_1_front_eq_preset", option="original")
    assert remote.actions() == ["eq_reset"] and remote.s["eq_on"] is False


async def test_eq_entities_exist_when_added_in_standby(hass: HomeAssistant, remote) -> None:
    remote.s["power"] = "Standby"
    entry = await setup(hass, remote)
    preset, band = "select.jbl_bar_9_1_front_eq_preset", "number.jbl_bar_9_1_front_eq_125_hz"
    assert hass.states.get(preset).state == "unavailable"
    assert hass.states.get(band).state == "unavailable"
    remote.s["power"] = "On"
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(preset).state == "original"
    assert hass.states.get(band).state == "0.0"


async def test_no_eq_entities_without_helper(hass: HomeAssistant, remote) -> None:
    remote.eq_helper = False
    await setup(hass, remote)
    assert hass.states.get("select.jbl_bar_9_1_front_eq_preset") is None
    assert hass.states.get("number.jbl_bar_9_1_front_eq_125_hz") is None


async def test_night_switch_is_idempotent(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    remote.log.clear()
    await call(hass, "switch", "turn_on", "switch.jbl_bar_9_1_night_mode")
    await call(hass, "switch", "turn_on", "switch.jbl_bar_9_1_night_mode")
    assert remote.actions() == ["night_toggle"] and remote.s["night"] is True


async def test_refused_control_is_reported_not_retried(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    remote.s["controls"] = ["media_play", "media_pause", "media_next"]
    await remote.notify()
    assert await until(lambda: hass.states.get(MP).attributes["supported_features"] & 32)
    remote.log.clear()
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "media_player", "media_next_track", MP)
    assert "playback control" in str(err.value) or err.value.translation_key == "refused"
    assert remote.actions() == ["media_next"]


async def test_stale_token_retried_once(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    remote.s["csrf"] = "tok2"
    remote.log.clear()
    await call(hass, "switch", "turn_on", "switch.jbl_bar_9_1_night_mode")
    assert [e[0] for e in remote.log] == ["403", "ok"]


async def test_push_updates_and_standby_closes_stream(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    assert await until(lambda: remote.streams == 1)
    remote.s["volume"] = 20
    await remote.notify()
    assert await until(lambda: hass.states.get(MP).attributes.get("volume_level") == pytest.approx(20 / 32))
    remote.s["power"] = "Standby"
    await remote.notify()
    assert await until(lambda: hass.states.get(MP).state == "off")
    assert await until(lambda: remote.streams == 0)


async def test_smart_mode_switch(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    sw = "switch.jbl_bar_9_1_smart_mode"
    assert hass.states.get(sw).state == "off"
    remote.log.clear()
    await call(hass, "switch", "turn_on", sw)
    await call(hass, "switch", "turn_on", sw)
    assert remote.actions() == ["smart"] and hass.states.get(sw).state == "on"
    await call(hass, "switch", "turn_off", sw)
    assert remote.actions() == ["smart", "standard"] and remote.mode == "Standard"


async def test_audio_sync_in_chunks(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    num = "number.jbl_bar_9_1_audio_sync"
    assert hass.states.get(num).state == "0"
    remote.log.clear()
    await call(hass, "number", "set_value", num, value=120)
    assert remote.av_sync == 120 and hass.states.get(num).state == "120"
    assert [(e[1], e[3]) for e in remote.log if e[0] == "ok"] == [("av_sync_set", 120)]
    await call(hass, "number", "set_value", num, value=100)
    assert remote.av_sync == 100


async def test_audio_sync_split_for_older_remotes(hass: HomeAssistant, remote) -> None:
    remote.av_sync_limit = 80
    await setup(hass, remote)
    remote.log.clear()
    await call(hass, "number", "set_value", "number.jbl_bar_9_1_audio_sync", value=120)
    assert remote.av_sync == 120
    assert [e[3] for e in remote.log if e[0] == "ok"] == [120, 50, 100, 120]


async def test_audio_sync_unavailable_on_bluetooth(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    await call(hass, "media_player", "select_source", MP, source="Bluetooth")
    assert hass.states.get("number.jbl_bar_9_1_audio_sync").state == "unavailable"


async def test_no_advanced_entities_on_older_remote(hass: HomeAssistant, remote) -> None:
    remote.advanced = False
    await setup(hass, remote)
    assert hass.states.get("switch.jbl_bar_9_1_smart_mode") is None
    assert hass.states.get("number.jbl_bar_9_1_audio_sync") is None
    assert hass.states.get("button.jbl_bar_9_1_standard_mode") is not None


async def test_standard_button_replaced_by_smart_switch(hass: HomeAssistant, remote) -> None:
    remote.advanced = False
    entry = await setup(hass, remote)
    assert hass.states.get("button.jbl_bar_9_1_standard_mode") is not None
    # The bar gets the advanced remote: after a reload the old button is gone.
    remote.advanced = True
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("button.jbl_bar_9_1_standard_mode") is None
    assert er.async_get(hass).async_get_entity_id("button", DOMAIN, f"{remote.host}_standard_mode") is None
    assert hass.states.get("switch.jbl_bar_9_1_smart_mode") is not None


async def test_setup_controls(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    calibrate, sub = "button.jbl_bar_9_1_calibrate_surround", "button.jbl_bar_9_1_pair_subwoofer"
    assert hass.states.get("sensor.jbl_bar_9_1_audio_format").state == "DOLBY SURROUND DD+"
    assert hass.states.get("sensor.jbl_bar_9_1_calibration").state == "Idle"
    assert hass.states.get(calibrate).state != "unavailable"
    remote.log.clear()
    await call(hass, "button", "press", calibrate)
    assert await until(lambda: hass.states.get("sensor.jbl_bar_9_1_calibration").state == "Step 1 starting")
    assert remote.actions() == ["calibrate"]
    # The bar is measuring: both setup buttons wait.
    assert hass.states.get(calibrate).state == "unavailable" and hass.states.get(sub).state == "unavailable"
    remote.setup = {"sub_pairing": False, "calibration": "Step 1 done"}
    await remote.notify()
    assert await until(lambda: hass.states.get(calibrate).state != "unavailable")
    await call(hass, "button", "press", sub)
    assert await until(lambda: hass.states.get("sensor.jbl_bar_9_1_subwoofer").state == "Pairing")
    assert remote.actions() == ["calibrate", "sub_pair"] and hass.states.get(sub).state == "unavailable"


async def test_calibrate_needs_undocked_rears(hass: HomeAssistant, remote) -> None:
    remote.rear_docked = True
    await setup(hass, remote)
    assert hass.states.get("button.jbl_bar_9_1_calibrate_surround").state == "unavailable"
    assert hass.states.get("button.jbl_bar_9_1_pair_subwoofer").state != "unavailable"


async def test_no_setup_entities_on_older_remote(hass: HomeAssistant, remote) -> None:
    remote.setup = None
    await setup(hass, remote)
    for entity_id in ("button.jbl_bar_9_1_calibrate_surround", "button.jbl_bar_9_1_pair_subwoofer",
                      "sensor.jbl_bar_9_1_audio_format", "sensor.jbl_bar_9_1_calibration"):
        assert hass.states.get(entity_id) is None


async def test_waits_for_a_control_running_elsewhere(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    remote.busy_other = "av_sync_set"
    await remote.notify()
    assert await until(lambda: hass.states.get("binary_sensor.jbl_bar_9_1_command_running").state == "on")
    assert hass.states.get("binary_sensor.jbl_bar_9_1_command_running").attributes["source"] == "remote"
    remote.log.clear()

    async def finish() -> None:
        await asyncio.sleep(0.6)
        remote.busy_other = None
        await remote.notify()

    task = hass.async_create_task(finish())
    await call(hass, "media_player", "volume_up", MP)
    await task
    assert remote.s["volume"] == 11 and remote.actions() == ["volume_up"]
    assert await until(lambda: hass.states.get("binary_sensor.jbl_bar_9_1_command_running").state == "off")


async def test_resends_after_another_control_is_running(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    remote.log.clear()
    # The remote refuses before acting; the state does not report busy (older remote).
    real_state = remote.state

    def refuse_once() -> dict:
        return real_state()

    remote.busy_other = "smart"
    remote.state = lambda: {**refuse_once(), "control": {"busy": False}}

    async def finish() -> None:
        await asyncio.sleep(0.3)
        remote.busy_other = None

    task = hass.async_create_task(finish())
    await call(hass, "media_player", "volume_up", MP)
    await task
    remote.state = real_state
    assert [e[0] for e in remote.log][-1] == "ok" and ("busy", "volume_up") in remote.log and remote.actions() == ["volume_up"]


async def test_command_running_while_home_assistant_waits(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    sensor = "binary_sensor.jbl_bar_9_1_command_running"
    assert hass.states.get(sensor).state == "off"
    remote.action_delay = 0.5
    task = hass.async_create_task(call(hass, "switch", "turn_on", "switch.jbl_bar_9_1_night_mode"))
    assert await until(lambda: hass.states.get(sensor).state == "on")
    attrs = hass.states.get(sensor).attributes
    assert attrs["source"] == "home_assistant" and attrs["action"] == "night_toggle"
    await task
    assert await until(lambda: hass.states.get(sensor).state == "off")


async def test_unload(hass: HomeAssistant, remote) -> None:
    entry = await setup(hass, remote)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_bass_offset(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    num = "number.jbl_bar_9_1_bass_offset"
    assert hass.states.get(num).state == "0.0"
    assert hass.states.get(num).attributes["status"] == "off"
    remote.log.clear()
    await call(hass, "number", "set_value", num, value=-1.5)
    assert remote.bass_offset == -1.5 and hass.states.get(num).state == "-1.5"
    assert [(e[1], e[4]) for e in remote.log if e[0] == "ok"] == [("bar91.bass-offset.set", {"offset_db": -1.5})]
    assert hass.states.get(num).attributes["status"] == "active"


async def test_bass_offset_needs_the_extension(hass: HomeAssistant, remote) -> None:
    remote.bass_offset = None
    await setup(hass, remote)
    assert hass.states.get("number.jbl_bar_9_1_bass_offset") is None


async def test_mode_after_standby(hass: HomeAssistant, remote) -> None:
    remote.remembered_mode = "Smart"
    await setup(hass, remote)
    assert hass.states.get("sensor.jbl_bar_9_1_mode_after_standby").state == "smart"


async def test_no_mode_after_standby_without_memory(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    assert hass.states.get("sensor.jbl_bar_9_1_mode_after_standby") is None


async def test_center_options_unchanged(hass: HomeAssistant, remote) -> None:
    """Center is shown 1-6 through translations; option values stay 0-5 for automations."""
    await setup(hass, remote)
    assert hass.states.get("select.jbl_bar_9_1_center_level").attributes["options"] == ["0", "1", "2", "3", "4", "5"]


async def test_config_flow_refuses_another_model(hass: HomeAssistant, remote) -> None:
    remote.model = "bar1300"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: remote.host})
    assert result["errors"] == {"base": "unsupported_model"}
    assert result["description_placeholders"] == {"model": "bar1300"}
    remote.model = "bar91"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: remote.host})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_config_flow_accepts_remote_without_features(hass: HomeAssistant, remote) -> None:
    remote.model = None  # older remote: /api/features answers 404
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: remote.host})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_setup_refuses_another_model(hass: HomeAssistant, remote) -> None:
    remote.model = "bar1300"
    entry = MockConfigEntry(domain=DOMAIN, unique_id=remote.host, data={CONF_HOST: remote.host}, title="JBL Bar 9.1")
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is config_entries.ConfigEntryState.SETUP_ERROR
    assert hass.states.get(MP) is None


async def test_kept_eq_waiting_is_shown_and_can_be_reset(hass: HomeAssistant, remote) -> None:
    """A remote that keeps the EQ reports it while the bar has dropped it."""
    remote.keep_eq = True
    await setup(hass, remote)
    preset = "select.jbl_bar_9_1_front_eq_preset"
    band = "number.jbl_bar_9_1_front_eq_125_hz"
    await call(hass, "select", "select_option", preset, option="clear_dialogue")
    assert hass.states.get(preset).attributes["kept"] is True
    # The bar drops the EQ (e.g. input change); the remote waits to apply it again.
    remote.s["eq"], remote.s["eq_on"] = [0] * 5, False
    await remote.notify()
    assert await until(lambda: hass.states.get(preset).attributes.get("status") == "waiting")
    state = hass.states.get(preset)
    assert state.state == "clear_dialogue", "the chosen EQ, not Original, while it waits"
    assert state.attributes["kept"] is True and "re-applied" in state.attributes["error"]
    # A remote that keeps the EQ saves a band changed while it cannot apply.
    assert hass.states.get(band).state == "-3.0"
    remote.log.clear()
    await call(hass, "number", "set_value", band, value=-4)
    assert remote.actions() == ["eq_apply"] and remote.eq_kept == [-4.0, -1.0, 0.0, 0.0, -1.0]
    assert hass.states.get(preset).attributes["status"] == "waiting"
    assert hass.states.get(band).state == "-4.0"
    remote.log.clear()
    await call(hass, "select", "select_option", preset, option="original")
    assert remote.actions() == ["eq_reset"]
    assert hass.states.get(preset).state == "original"
    assert hass.states.get(preset).attributes["kept"] is False


async def test_kept_eq_waiting_at_startup(hass: HomeAssistant, remote) -> None:
    remote.keep_eq = True
    remote.eq_kept = [-3.0, -1.0, 0.0, 0.0, -1.0]
    await setup(hass, remote)
    remote.s["power"] = "On"
    preset = "select.jbl_bar_9_1_front_eq_preset"
    assert hass.states.get(preset).state == "clear_dialogue"
    assert hass.states.get(preset).attributes["status"] == "waiting"


async def test_eq_saved_in_standby(hass: HomeAssistant, remote) -> None:
    """With a remote that keeps the EQ, a preset chosen in standby is saved for later."""
    remote.keep_eq = True
    remote.s["power"] = "Standby"
    await setup(hass, remote)
    preset = "select.jbl_bar_9_1_front_eq_preset"
    assert hass.states.get(preset).state == "original"
    await call(hass, "select", "select_option", preset, option="warm")
    assert remote.eq_kept == [0, 0, -1, -2, -3]
    assert hass.states.get(preset).state == "warm"
    assert hass.states.get(preset).attributes["status"] == "waiting"


async def test_eq_unavailable_in_standby_on_older_remote(hass: HomeAssistant, remote) -> None:
    """An older remote (no eq.kept) refuses an EQ it cannot apply: the entities stay unavailable."""
    remote.s["power"] = "Standby"
    await setup(hass, remote)
    assert hass.states.get("select.jbl_bar_9_1_front_eq_preset").state == "unavailable"
    assert hass.states.get("number.jbl_bar_9_1_front_eq_125_hz").state == "unavailable"


async def test_front_eq_status_sensor(hass: HomeAssistant, remote) -> None:
    """Like the web page's badge: active, waiting (with the reason), off or reset_needed."""
    remote.keep_eq = True
    await setup(hass, remote)
    status = "sensor.jbl_bar_9_1_front_eq_status"
    assert hass.states.get(status).state == "off"
    await call(hass, "select", "select_option", "select.jbl_bar_9_1_front_eq_preset", option="warm")
    assert hass.states.get(status).state == "active"
    assert hass.states.get(status).attributes["gains_db"] == [0, 0, -1, -2, -3]
    remote.s["eq"], remote.s["eq_on"] = [0] * 5, False  # dropped by the bar: kept EQ waits
    await remote.notify()
    assert await until(lambda: hass.states.get(status).state == "waiting")
    assert "Standard audio" in hass.states.get(status).attributes["reason"]
    remote.eq_status_override = "reset_required"
    await remote.notify()
    assert await until(lambda: hass.states.get(status).state == "reset_needed")


async def test_front_eq_status_waits_in_smart_mode(hass: HomeAssistant, remote) -> None:
    """An applied EQ the remote cannot confirm (Smart Mode, another route) is not reported active."""
    remote.keep_eq = True
    await setup(hass, remote)
    status = "sensor.jbl_bar_9_1_front_eq_status"
    await call(hass, "select", "select_option", "select.jbl_bar_9_1_front_eq_preset", option="warm")
    remote.s["eq_on"] = True
    remote.eq_status_override = "active"
    await remote.notify()
    assert await until(lambda: hass.states.get(status).state == "active")
    remote.eq_status_override = "unavailable"  # Smart Mode: still enabled, not confirmed
    await remote.notify()
    assert await until(lambda: hass.states.get(status).state == "waiting")


async def test_no_front_eq_status_without_helper(hass: HomeAssistant, remote) -> None:
    remote.eq_helper = False
    await setup(hass, remote)
    assert hass.states.get("sensor.jbl_bar_9_1_front_eq_status") is None


async def test_display_message_and_cancel(hass: HomeAssistant, remote) -> None:
    """The services send the remote's display-message actions with typed parameters."""
    await setup(hass, remote)
    await call(hass, DOMAIN, "display_message", MP, message="Frigo ouvert", id="fridge", forever=True)
    await call(hass, DOMAIN, "display_message", MP, message="Frigo fermé", id="fridge")
    await call(hass, DOMAIN, "display_message", MP, message="Colis", repeat=3)
    await call(hass, DOMAIN, "display_message", MP, message="Porte", duration={"minutes": 5})
    await call(hass, DOMAIN, "display_message", MP, message="Pain au four", forever=True, clear_on_key=True)
    await call(hass, DOMAIN, "display_cancel", MP, id="fridge")
    await call(hass, DOMAIN, "display_cancel", MP)
    assert remote.display_log == [
        ("show", {"text": "Frigo ouvert", "id": "fridge", "forever": True}),
        ("show", {"text": "Frigo fermé", "id": "fridge"}),
        ("show", {"text": "Colis", "repeat": 3}),
        ("show", {"text": "Porte", "duration_s": 300}),
        ("show", {"text": "Pain au four", "forever": True, "stop_on_key": True}),
        ("cancel", {"id": "fridge"}),
        ("cancel", None),
    ]


async def test_display_message_validation(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    with pytest.raises(ServiceValidationError):
        await call(hass, DOMAIN, "display_message", MP, message="A", repeat=2, forever=True)
    with pytest.raises(ServiceValidationError):
        await call(hass, DOMAIN, "display_message", MP, message="A", duration={"hours": 25})
    with pytest.raises(vol.Invalid):  # schema: id format, repeat range
        await call(hass, DOMAIN, "display_message", MP, message="A", id="Fridge Door")
    with pytest.raises(vol.Invalid):
        await call(hass, DOMAIN, "display_message", MP, message="A", repeat=100)
    assert remote.display_log == []
    # forever: false is the same as leaving it out.
    await call(hass, DOMAIN, "display_message", MP, message="A", repeat=2, forever=False)
    assert remote.display_log == [("show", {"text": "A", "repeat": 2})]


async def test_display_message_needs_a_recent_remote(hass: HomeAssistant, remote) -> None:
    remote.display = False
    await setup(hass, remote)
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, DOMAIN, "display_message", MP, message="Frigo")
    assert err.value.translation_key == "display_unsupported"


async def test_display_notify_entity(hass: HomeAssistant, remote) -> None:
    """notify.send_message shows the message on the display, two passes; the title goes first when it fits."""
    await setup(hass, remote)
    target = "notify.jbl_bar_9_1_display"
    assert hass.states.get(target) is not None
    await hass.services.async_call("notify", "send_message", {"entity_id": target, "message": "Colis livré"}, blocking=True)
    await hass.services.async_call("notify", "send_message", {"entity_id": target, "message": "Porte ouverte", "title": "Garage"}, blocking=True)
    await hass.services.async_call(
        "notify", "send_message", {"entity_id": target, "message": "La porte du garage est ouverte", "title": "Alerte"}, blocking=True
    )
    assert remote.display_log == [
        ("show", {"text": "Colis livré", "repeat": 2}),
        ("show", {"text": "Garage Porte ouverte", "repeat": 2}),
        ("show", {"text": "La porte du garage est ouverte", "repeat": 2}),
    ]


async def test_display_notify_needs_a_recent_remote(hass: HomeAssistant, remote) -> None:
    remote.display = False
    await setup(hass, remote)
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("notify", "send_message", {"entity_id": "notify.jbl_bar_9_1_display", "message": "X"}, blocking=True)
    assert err.value.translation_key == "display_unsupported"


async def test_timer_services(hass: HomeAssistant, remote) -> None:
    """timer_start sends the remote's parameters; timer_cancel finds a timer by name, id or all."""
    await setup(hass, remote)
    await call(hass, DOMAIN, "timer_start", MP, duration={"minutes": 10}, name="Pizza", show_time_left=True, sound="unless_tv")
    await call(hass, DOMAIN, "timer_start", MP, duration={"seconds": 90})
    await call(hass, DOMAIN, "timer_start", MP, duration={"minutes": 5}, name="Pâtes", sound="always", sound_volume=20, ring_for={"minutes": 1})
    assert remote.timer_log == [
        ("start", {"duration_s": 600, "text": "Pizza", "countdown": True, "sound": "unless_tv", "sound_volume": 10, "ring_s": 30}),
        ("start", {"duration_s": 90, "sound": "off"}),
        ("start", {"duration_s": 300, "text": "Pâtes", "sound": "always", "sound_volume": 20, "ring_s": 60}),
    ]
    await hass.async_block_till_done()
    await call(hass, DOMAIN, "timer_cancel", MP, name="pizza")
    assert remote.timer_log[-1] == ("cancel", {"id": "t1"})
    await call(hass, DOMAIN, "timer_cancel", MP, id="t2")
    assert remote.timer_log[-1] == ("cancel", {"id": "t2"})
    await call(hass, DOMAIN, "timer_cancel", MP, all=True)
    assert remote.timer_log[-1] == ("cancel", {"id": "t3"}) and remote.timers == []


async def test_timer_service_errors(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    with pytest.raises(ServiceValidationError):
        await call(hass, DOMAIN, "timer_start", MP, duration={"hours": 13})
    with pytest.raises(ServiceValidationError):
        await call(hass, DOMAIN, "timer_start", MP, duration={"minutes": 1}, sound="always", ring_for={"minutes": 6})
    with pytest.raises(ServiceValidationError):
        await call(hass, DOMAIN, "timer_cancel", MP, name="nothing")
    with pytest.raises(ServiceValidationError):
        await call(hass, DOMAIN, "timer_cancel", MP)
    await call(hass, DOMAIN, "timer_start", MP, duration={"minutes": 1}, name="Pizza")
    with pytest.raises(HomeAssistantError):  # the remote refuses a second PIZZA
        await call(hass, DOMAIN, "timer_start", MP, duration={"minutes": 2}, name="pizza")


async def test_timer_entities(hass: HomeAssistant, remote) -> None:
    remote.timers = [
        {"id": "t1", "text": "PIZZA", "countdown": True, "sound": "unless_tv", "remaining_ms": 600000, "ringing": False},
        {"id": "t2", "text": "", "countdown": False, "sound": "off", "remaining_ms": 60000, "ringing": False},
    ]
    await setup(hass, remote)
    timers = hass.states.get("sensor.jbl_bar_9_1_timers")
    assert timers.state == "2"
    names = [t["name"] for t in timers.attributes["timers"]]
    assert names == ["", "PIZZA"]  # first to end first
    nxt = hass.states.get("sensor.jbl_bar_9_1_next_timer")
    assert nxt.attributes["id"] == "t2" and nxt.attributes.get("device_class") == "timestamp"
    assert hass.states.get("binary_sensor.jbl_bar_9_1_timer_ringing").state == "off"
    remote.timers[1]["ringing"], remote.timers[1]["remaining_ms"] = True, 0
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    ringing = hass.states.get("binary_sensor.jbl_bar_9_1_timer_ringing")
    assert ringing.state == "on" and ringing.attributes["names"] == [""]
    assert hass.states.get("sensor.jbl_bar_9_1_next_timer").attributes["id"] == "t1"


async def test_timer_entities_need_a_recent_remote(hass: HomeAssistant, remote) -> None:
    remote.timers = None
    await setup(hass, remote)
    assert hass.states.get("sensor.jbl_bar_9_1_timers") is None
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, DOMAIN, "timer_start", MP, duration={"minutes": 1})
    assert err.value.translation_key == "timer_unsupported"


def test_timer_clock_keeps_end_times_still() -> None:
    from datetime import datetime, timedelta

    from custom_components.jbl_bar_91.timers import TimerClock, fold_name

    clock = TimerClock()
    now = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)
    doc = {"extensions": {"bar91.timer": {"timers": [{"id": "t1", "remaining_ms": 60000}]}}}
    first = clock.ends(doc, now)["t1"]
    doc["extensions"]["bar91.timer"]["timers"][0]["remaining_ms"] = 58800  # 1.2 s later, 1.2 s less
    assert clock.ends(doc, now + timedelta(milliseconds=1500))["t1"] == first
    assert fold_name("  pâtes  à l'œuf ") == "PATES A L'OEUF"


async def test_timer_extend(hass: HomeAssistant, remote) -> None:
    """+1 min by default to the next timer to end; by name or id; refused when none runs or the remote is older."""
    remote.timers = [
        {"id": "t1", "text": "PIZZA", "countdown": True, "sound": "off", "remaining_ms": 600000, "duration_ms": 600000, "ringing": False},
        {"id": "t2", "text": "", "countdown": False, "sound": "off", "remaining_ms": 60000, "duration_ms": 120000, "ringing": False},
        {"id": "t3", "text": "PATES", "countdown": False, "sound": "off", "remaining_ms": 0, "duration_ms": 30000, "ringing": True},
    ]
    await setup(hass, remote)
    await call(hass, DOMAIN, "timer_extend", MP)
    assert remote.timer_log[-1] == ("extend", {"id": "t2", "add_s": 60})
    await call(hass, DOMAIN, "timer_extend", MP, name="pizza", duration={"minutes": 5})
    assert remote.timer_log[-1] == ("extend", {"id": "t1", "add_s": 300})
    await call(hass, DOMAIN, "timer_extend", MP, id="t1", duration={"seconds": 30})
    assert remote.timer_log[-1] == ("extend", {"id": "t1", "add_s": 30})
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    pizza = next(t for t in hass.states.get("sensor.jbl_bar_9_1_timers").attributes["timers"] if t["name"] == "PIZZA")
    assert pizza["duration_s"] == 930
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, DOMAIN, "timer_extend", MP, name="pates")  # ringing: not extended
    assert err.value.translation_key == "timer_not_found"
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, DOMAIN, "timer_extend", MP, duration={"hours": 2})
    assert err.value.translation_key == "timer_extend_duration"
    remote.timer_extend = False
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, DOMAIN, "timer_extend", MP)
    assert err.value.translation_key == "timer_extend_unsupported"
    remote.timers = []
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, DOMAIN, "timer_extend", MP)
    assert err.value.translation_key == "timer_none_running"


async def test_display_messages_sensor_and_clear_buttons(hass: HomeAssistant, remote) -> None:
    """The Messages sensor lists what the remote reports; a line clears one message, a button all of them."""
    remote.messages = [
        {"id": "default", "named": False, "text": "FRIGO OUVERT", "mode": "passes", "passes_left": 2, "showing": True},
        {"id": "colis", "named": True, "text": "COLIS", "mode": "duration", "remaining_ms": 300000, "showing": False},
    ]
    await setup(hass, remote)
    state = hass.states.get("sensor.jbl_bar_9_1_messages")
    assert state.state == "2"
    unnamed, colis = state.attributes["messages"]
    assert unnamed["name"] == "" and unnamed["passes_left"] == 2 and unnamed["showing"] and unnamed["ends_at"] is None
    assert colis["name"] == "colis" and colis["mode"] == "duration" and colis["ends_at"] and not colis["showing"]
    assert hass.states.get("button.jbl_bar_9_1_clear_unnamed_message") is None  # the message lines replace it
    await call(hass, "button", "press", "button.jbl_message_line_1")
    await call(hass, "button", "press", "button.jbl_bar_9_1_clear_all_messages")
    assert remote.display_log[-2:] == [("cancel", {"id": "default"}), ("cancel", None)]


async def test_no_messages_sensor_on_older_remotes(hass: HomeAssistant, remote) -> None:
    await setup(hass, remote)
    assert hass.states.get("sensor.jbl_bar_9_1_messages") is None
    assert hass.states.get("button.jbl_bar_9_1_clear_all_messages") is not None


async def test_new_remote_features_appear_without_a_reload(hass: HomeAssistant, remote) -> None:
    """The bar's remote is updated while Home Assistant runs: the new entities appear by themselves."""
    remote.timers = None
    await setup(hass, remote)
    assert hass.states.get("sensor.jbl_bar_9_1_messages") is None and hass.states.get("sensor.jbl_bar_9_1_timers") is None
    coordinator = hass.config_entries.async_entries("jbl_bar_91")[0].runtime_data
    await coordinator.async_refresh()  # nothing new: no reload
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries("jbl_bar_91")[0].runtime_data is coordinator
    remote.timers, remote.messages = [], []
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries("jbl_bar_91")[0]
    assert entry.runtime_data is not coordinator  # reloaded once
    assert hass.states.get("sensor.jbl_bar_9_1_messages").state == "0"
    assert hass.states.get("sensor.jbl_bar_9_1_timers") is not None
    remote.timers = None  # a feature going away (a bar restarting on an older remote) does not reload
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries("jbl_bar_91")[0].runtime_data is entry.runtime_data


async def test_restart_button(hass: HomeAssistant, remote) -> None:
    """The Restart button sends the remote's reboot with confirm; an older remote is reported."""
    await setup(hass, remote)
    state = hass.states.get("button.jbl_bar_9_1_restart")
    assert state.attributes["device_class"] == "restart"
    await call(hass, "button", "press", "button.jbl_bar_9_1_restart")
    assert remote.reboots == [{"confirm": True}]
    remote.reboot = False
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "button", "press", "button.jbl_bar_9_1_restart")
    assert err.value.translation_key == "restart_unsupported"


async def test_lines_in_french_and_the_old_unnamed_button_removed(hass: HomeAssistant, remote) -> None:
    """Line names follow Home Assistant's language; the button replaced by the lines leaves the registry."""
    hass.config.language = "fr"
    registry = er.async_get(hass)
    old = registry.async_get_or_create("button", DOMAIN, f"{remote.host}_clear_unnamed_message", suggested_object_id="jbl_bar_9_1_clear_unnamed_message")
    remote.timers = [{"id": "t1", "text": "", "remaining_ms": 600000, "ringing": False}]
    remote.messages = [{"id": "colis", "named": True, "text": "COLIS", "mode": "duration", "remaining_ms": 300000, "showing": True}]
    await setup(hass, remote)
    assert registry.async_get(old.entity_id) is None
    timer, message = hass.states.get("button.jbl_timer_line_1"), hass.states.get("button.jbl_message_line_1")
    assert timer.name.startswith("Minuteur – fin à "), timer.name
    assert message.name.startswith("COLIS (colis) – jusqu'à "), message.name
    assert hass.states.get("button.jbl_timer_line_2").name == "Ligne de minuteur 2"


async def test_events_and_rear_batteries(hass: HomeAssistant, remote) -> None:
    """Timer and message events fire once per change, never for what was there at start."""
    remote.timers = [{"id": "t0", "text": "OLD", "remaining_ms": 900000, "ringing": False}]
    remote.messages = []
    await setup(hass, remote)
    assert hass.states.get("sensor.jbl_bar_9_1_rear_left_battery").state == "90"
    assert hass.states.get("sensor.jbl_bar_9_1_rear_right_battery").attributes["device_class"] == "battery"
    timer_events, message_events = "event.jbl_bar_9_1_timer_events", "event.jbl_bar_9_1_message_events"
    assert hass.states.get(timer_events).state == "unknown"  # the timer already running fired nothing
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    seen: list[tuple[str, str, dict]] = []

    @callback
    def record(event) -> None:
        new = event.data["new_state"]
        if new and new.entity_id in (timer_events, message_events) and new.state not in ("unknown", "unavailable"):
            seen.append((new.entity_id.split("_")[-2], new.attributes["event_type"], {k: new.attributes[k] for k in ("id",) if k in new.attributes}))

    hass.bus.async_listen("state_changed", record)

    async def step(timers, messages) -> None:
        remote.timers, remote.messages = timers, messages
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    await step([{"id": "t0", "text": "OLD", "remaining_ms": 800000, "ringing": False},
                {"id": "t1", "text": "PIZZA", "remaining_ms": 60000, "ringing": False}],
               [{"id": "colis", "named": True, "text": "COLIS", "mode": "forever", "showing": True}])
    await step([{"id": "t0", "text": "OLD", "remaining_ms": 700000, "ringing": False},
                {"id": "t1", "text": "PIZZA", "remaining_ms": 0, "ringing": True}], [])
    await step([], [])
    assert seen == [("timer", "started", {"id": "t1"}), ("message", "shown", {"id": "colis"}),
                    ("timer", "ringing", {"id": "t1"}), ("message", "ended", {"id": "colis"}),
                    ("timer", "cancelled", {"id": "t0"}), ("timer", "finished", {"id": "t1"})], seen
    assert hass.states.get(timer_events).attributes["name"] == "PIZZA"


async def test_standby_clock_switch(hass: HomeAssistant, remote) -> None:
    """The clock switch follows the bar and sends Home Assistant's time zone; it appears with a remote that has it."""
    await setup(hass, remote)
    assert hass.states.get("switch.jbl_display_clock") is None  # remote without the clock
    await hass.config.async_update(time_zone="Europe/Paris")
    remote.clock = {"enabled": False, "tz": ""}
    await hass.config_entries.async_entries(DOMAIN)[0].runtime_data.async_refresh()  # gained the clock: reloads by itself
    await hass.async_block_till_done()
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    clock = hass.states.get("switch.jbl_display_clock")
    assert clock.state == "off" and clock.name == "JBL Bar 9.1 Clock in standby", clock
    await call(hass, "switch", "turn_on", "switch.jbl_display_clock")
    assert remote.display_log[-1] == ("clock", {"enabled": True, "tz": "Europe/Paris"})
    assert hass.states.get("switch.jbl_display_clock").state == "on"
    await call(hass, "switch", "turn_off", "switch.jbl_display_clock")
    assert remote.display_log[-1] == ("clock", {"enabled": False}) and remote.clock["tz"] == "Europe/Paris"
    # Where it shows: in standby only, or with the bar on too (a remote that reports "when").
    assert hass.states.get("select.jbl_display_clock_when").state == "unavailable"  # this remote has no "when" yet
    remote.clock["when"] = "standby"
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    when = hass.states.get("select.jbl_display_clock_when")
    assert when.state == "standby" and when.name == "JBL Bar 9.1 Clock shows", when
    await call(hass, "select", "select_option", "select.jbl_display_clock_when", option="always")
    assert remote.display_log[-1] == ("clock", {"when": "always"}) and remote.clock["when"] == "always"
