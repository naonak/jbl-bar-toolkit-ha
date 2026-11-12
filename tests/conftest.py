"""Fake JBL Bar 9.1 browser remote with the real server's rules.

POST /api/action requires Content-Type application/json and the current CSRF
token (else 403); refused controls answer 409 {"error", "state"}; every
change is pushed on GET /api/events as "data: <state>" like the Go server.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from aiohttp import web

from custom_components.jbl_bar_91 import coordinator as coordinator_module


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def fast_push(monkeypatch):
    monkeypatch.setattr(coordinator_module, "IDLE_CHECK", 0.05)
    monkeypatch.setattr(coordinator_module, "RECONNECT_MIN", 0.05)
    monkeypatch.setattr(coordinator_module, "RECONNECT_MAX", 0.1)


class FakeRemote:
    def __init__(self) -> None:
        self.s: dict[str, Any] = {
            "csrf": "tok1", "power": "On", "volume": 10, "muted": False, "input": "TV / ARC",
            "bass": 0, "atmos": 1, "rear": 0, "center": 0, "night": False,
            "eq": [0, 0, 0, 0, 0], "eq_on": False, "controls": ["media_play", "media_pause"],
        }
        self.log: list[tuple] = []
        self.forbid_ha = False
        self.eq_helper = True
        self.advanced = True
        self.mode = "Standard"
        self.av_sync = 0
        self.av_sync_limit = 250
        self.busy_other: str | None = None  # a control sent by another client is running
        self.action_delay = 0.0
        self.setup: dict[str, Any] | None = {"sub_pairing": False}
        self.rear_docked = False
        self.model: str | None = "bar91"  # None: remote without /api/features
        self.eq_status_override: str | None = None  # e.g. "reset_required"
        self.keep_eq = False  # remote that keeps the Front EQ until Reset (eq.kept)
        self.eq_kept: list | None = None
        self.bass_offset: float | None = 0.0  # None: remote without the bass offset extension
        self.remembered_mode: str | None = None  # set when smart_mode_memory is on
        self.display = True  # False: remote without the display-message extension
        self.timers: list[dict] | None = []  # None: remote without timers
        self.timer_log: list[tuple[str, dict | None]] = []
        self.timer_extend = True  # False: remote with timers but without +1 min
        self.display_log: list[tuple[str, dict | None]] = []
        self.reboot = True  # False: remote without the restart
        self.reboots: list[dict | None] = []
        self.messages: list[dict] | None = None  # a list: a remote that lists the messages in course
        self.clock: dict | None = None  # a dict: a remote with the standby clock (enabled, tz)
        self.streams = 0
        self.changed = asyncio.Condition()
        self.port = 0
        self._runner: web.AppRunner | None = None

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.port}"

    def actions(self) -> list[str]:
        return [e[1] for e in self.log if e[0] == "ok"]

    def state(self) -> dict[str, Any]:
        s = self.s
        return {
            "available": True, "power": s["power"], "mode": self.mode, "volume": s["volume"], "muted": s["muted"],
            "input": s["input"], "source_state": {"TV / ARC": 0, "Bluetooth": 2, "HDMI": 3}.get(s["input"], 6), "csrf": s["csrf"], "uptime": 1234, "media_controls": s["controls"],
            "sound": {"night": s["night"], "bass": s["bass"], "atmos": s["atmos"], "rear": s["rear"],
                      "rear_docked": self.rear_docked, "center": s["center"], "rear_battery_left": 90, "rear_battery_right": 15,
                      **({"av_sync_ms": self.av_sync} if self.advanced else {}),
                      **({"audio_format": "DOLBY SURROUND DD+"} if self.setup is not None and s["power"] == "On" else {})},
            **({"setup": self.setup} if self.setup is not None else {}),
            "control": {"busy": True, "action": self.busy_other, "since": 1} if self.busy_other else {"busy": False},
            "bluetooth": {"connected": True, "peer_name": "Pixel", "audio": "Streaming", "selected": False},
            "streaming": {"service": "Chromecast", "status": "Playing", "active": True,
                          "cast": {"title": "Song", "artist": "Band", "album": "LP", "player_state": "PLAYING"}},
            "eq": self.eq_state(),
            "system": {"cpu_percent": 12.5, "temperature_c": 51.0,
                       "memory": {"total_bytes": 400, "used_bytes": 100, "available_bytes": 300}},
            "wifi": {"signal_dbm": -50},
            **({"extensions": {
                **({"bar91.bass-offset": {"offset_db": self.bass_offset, "status": "active" if self.bass_offset else "off"}}
                   if self.bass_offset is not None else {}),
                **({"bar91.timer": {"timers": [dict(t) for t in self.timers]}} if self.timers is not None else {}),
                **({"bar91.display-message": {"messages": [dict(m) for m in self.messages]}} if self.messages is not None else {}),
                **({"bar91.display-clock": dict(self.clock)} if self.clock is not None else {}),
            }} if self.bass_offset is not None or self.timers is not None or self.messages is not None or self.clock is not None else {}),
            **({"automation": {"enabled": True, "engine": "go", "status": "IDLE", "remembered_mode": self.remembered_mode}}
               if self.remembered_mode else {}),
        }

    def eq_state(self) -> dict[str, Any]:
        """Like the Go server: usable only with the helper, while the bar is on."""
        s = self.s
        eq = {"enabled": s["eq_on"], "gains_db": s["eq"], "available": False, "status": "unavailable"}
        if not self.eq_helper:
            eq["error"] = "EQ support is not installed"
        elif s["power"] != "On":
            eq["error"] = "Turn on the bar and start audio to adjust EQ"
        else:
            eq["available"], eq["status"] = True, ("active" if s["eq_on"] else "ready")  # like the Go server
        if self.keep_eq:
            eq["kept"] = self.eq_kept is not None
            if self.eq_kept is not None and not s["eq_on"]:
                # Dropped by the bar (source change, Smart, wake): shown while it waits.
                eq.update(gains_db=self.eq_kept, available=False, status="waiting",
                          error="Your EQ is re-applied automatically when Standard audio plays.")
        if self.eq_status_override:
            eq["status"] = self.eq_status_override
        return eq

    async def notify(self) -> None:
        async with self.changed:
            self.changed.notify_all()

    async def get_state(self, request: web.Request) -> web.Response:
        if self.forbid_ha:
            return web.Response(status=403, text="Open jbl.local or the bar's local IP address from its trusted network")
        return web.json_response(self.state())

    async def get_features(self, request: web.Request) -> web.Response:
        if self.forbid_ha:
            return web.Response(status=403, text="Open jbl.local or the bar's local IP address from its trusted network")
        if self.model is None:
            return web.Response(status=404, text="404 page not found")
        return web.json_response({"schema": 1, "model": self.model, "name": "JBL Bar", "actions": [], "extensions": []})

    async def post_action(self, request: web.Request) -> web.Response:
        if request.headers.get("Content-Type") != "application/json":
            self.log.append(("bad-ctype", request.headers.get("Content-Type")))
            return web.Response(status=403, text="Refresh the page before using controls")
        if request.headers.get("X-CSRF-Token") != self.s["csrf"]:
            self.log.append(("403",))
            return web.Response(status=403, text="Refresh the page before using controls")
        req = await request.json()
        a, s = req["action"], self.s
        if self.busy_other:
            self.log.append(("busy", a))
            return web.json_response({"error": "Another control is running", "state": self.state()}, status=409)
        if self.action_delay:
            await asyncio.sleep(self.action_delay)
        self.log.append(("ok", a, req.get("gains_db"), req.get("value"), req.get("parameters")))
        if a == "bar91.bass-offset.set":
            db = (req.get("parameters") or {}).get("offset_db")
            if self.bass_offset is None or not isinstance(db, (int, float)) or isinstance(db, bool) \
                    or not -3 <= db <= 3 or db * 2 != int(db * 2) or set(req) - {"action", "parameters"}:
                return web.json_response({"error": "bass offset must be -3 to 3 dB in 0.5 dB steps", "state": self.state()}, status=409)
            self.bass_offset = float(db)
            await self.notify()
            return web.json_response(self.state())
        if a.startswith("bar91.timer."):
            params = req.get("parameters") or {}
            if self.timers is None:
                return web.json_response({"error": "unknown control", "state": self.state()}, status=409)
            self.timer_log.append((a.rsplit(".", 1)[1], params))
            if a.endswith(".start"):
                name = (params.get("text") or "").upper()
                if any(t["text"] == name for t in self.timers):
                    return web.json_response({"error": f"a timer named {name} is already running", "state": self.state()}, status=409)
                self.timers.append({"id": f"t{len(self.timer_log)}", "text": name, "countdown": bool(params.get("countdown")),
                                    "sound": params.get("sound", "off"), "remaining_ms": params["duration_s"] * 1000, "ringing": False})
            elif a.endswith(".extend"):
                if not self.timer_extend:
                    self.timer_log.pop()
                    return web.json_response({"error": "unknown control", "state": self.state()}, status=409)
                for t in self.timers:
                    if t["id"] == params.get("id"):
                        t["remaining_ms"] += params["add_s"] * 1000
                        t["duration_ms"] = t.get("duration_ms", 0) + params["add_s"] * 1000
            else:
                self.timers = [t for t in self.timers if t["id"] != params.get("id")]
            return web.json_response(self.state())
        if a == "bar91.system.reboot":
            if not self.reboot:
                return web.json_response({"error": "unknown control", "state": self.state()}, status=409)
            self.reboots.append(req.get("parameters"))
            return web.json_response(self.state())
        if a == "bar91.display-clock.set":
            if self.clock is None:
                return web.json_response({"error": "unknown control", "state": self.state()}, status=409)
            params = req.get("parameters") or {}
            self.clock = {**self.clock, **{k: params[k] for k in ("enabled", "when", "tz") if k in params}}
            self.display_log.append(("clock", params))
            return web.json_response(self.state())
        if a.startswith("bar91.display-message."):
            params = req.get("parameters")
            if not self.display or a not in ("bar91.display-message.show", "bar91.display-message.cancel"):
                return web.json_response({"error": "unknown control", "state": self.state()}, status=409)
            if a.endswith(".show") and not (params or {}).get("text"):
                return web.json_response({"error": "provide a text", "state": self.state()}, status=409)
            self.display_log.append((a.rsplit(".", 1)[1], params))
            return web.json_response(self.state())
        if a == "av_sync_set":
            v = req.get("value")
            if s["input"] not in ("TV / ARC", "HDMI"):
                return web.json_response({"error": "select the TV or HDMI input to adjust audio sync", "state": self.state()}, status=409)
            if isinstance(v, int) and abs(v - self.av_sync) > self.av_sync_limit:
                return web.json_response({"error": f"change audio sync by at most {self.av_sync_limit} ms per request", "state": self.state()}, status=409)
            if not isinstance(v, int) or v % 10 or not 0 <= v <= 250:
                return web.json_response({"error": "audio sync value refused", "state": self.state()}, status=409)
            self.av_sync = v
            await self.notify()
            return web.json_response(self.state())
        if a in ("calibrate", "sub_pair"):
            if "value" in req or self.setup is None:
                return web.json_response({"error": "unknown control", "state": self.state()}, status=409)
            if a == "calibrate" and self.rear_docked:
                return web.json_response({"error": "undock both rear speakers first", "state": self.state()}, status=409)
            self.setup = {**self.setup, **({"calibration": "Step 1 starting"} if a == "calibrate" else {"sub_pairing": True})}
            await self.notify()
            return web.json_response(self.state())
        if a == "smart":
            self.mode = "Smart"
        elif a == "standard":
            self.mode = "Standard"
        if a == "media_next":
            return web.json_response({"error": "this source does not report support for that playback control", "state": self.state()}, status=409)
        if a == "volume_up": s["volume"] += 1
        elif a == "volume_down": s["volume"] -= 1
        elif a == "mute": s["muted"] = not s["muted"]
        elif a == "power": s["power"] = "Standby" if s["power"] == "On" else "On"
        elif a == "night_toggle": s["night"] = not s["night"]
        elif a == "bass_next": s["bass"] = (s["bass"] + 1) % 5
        elif a == "atmos_next": s["atmos"] = (s["atmos"] + 1) % 3
        elif a == "rear_next": s["rear"] = (s["rear"] + 1) % 4
        elif a == "center_next": s["center"] = (s["center"] + 1) % 6
        elif a == "input_hdmi": s["input"] = "HDMI"
        elif a == "input_tv": s["input"] = "TV / ARC"
        elif a == "input_bluetooth": s["input"] = "Bluetooth"
        elif a == "eq_apply" and self.keep_eq and not self.eq_state()["available"] and any(req["gains_db"]):
            # Cannot apply now: the remote keeps it and applies it later.
            self.eq_kept = list(req["gains_db"])
        elif a == "eq_apply":
            s["eq"], s["eq_on"] = req["gains_db"], True
            self.eq_kept = list(req["gains_db"])
        elif a == "eq_reset":
            s["eq"], s["eq_on"] = [0] * 5, False
            self.eq_kept = None
        await self.notify()
        return web.json_response(self.state())

    async def events(self, request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        self.streams += 1
        try:
            await resp.write(f"data: {json.dumps(self.state())}\n\n".encode())
            while request.transport is not None and not request.transport.is_closing():
                async with self.changed:
                    try:
                        await asyncio.wait_for(self.changed.wait(), 0.05)
                    except TimeoutError:
                        continue
                await resp.write(f"data: {json.dumps(self.state())}\n\n".encode())
        except (ConnectionResetError, asyncio.CancelledError):
            raise
        finally:
            self.streams -= 1

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/api/state", self.get_state)
        app.router.add_get("/api/features", self.get_features)
        app.router.add_post("/api/action", self.post_action)
        app.router.add_get("/api/events", self.events)
        self._runner = web.AppRunner(app, handle_signals=False, shutdown_timeout=0.2)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()


@pytest.fixture
async def remote(socket_enabled):
    fake = FakeRemote()
    await fake.start()
    yield fake
    await fake.stop()
