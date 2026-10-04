from __future__ import annotations

import atexit
import re
import threading
import time

from game_parser import GAMEPAD_BUTTONS, TRIGGERS, Binding, GameProfile

DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|s|m)?", re.IGNORECASE)
UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0}


def parse_duration(value):
    if isinstance(value, (int, float)):
        return float(value)
    number, unit = DURATION.fullmatch(str(value).strip()).groups()
    return float(number) * UNITS[(unit or "s").lower()]


def axis_key(binding: Binding) -> str:
    return f"{binding.kind}:{binding.target}"


class KeyboardMouseBackend:
    def __init__(self):
        self.api = None
        self.down: set[Binding] = set()

    def start(self, profile: GameProfile):
        import pydirectinput
        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = False
        self.api = pydirectinput

    def press(self, binding: Binding):
        if binding.kind == "key":
            self.api.keyDown(binding.target)
        else:
            self.api.mouseDown(button=binding.target)
        self.down.add(binding)

    def release(self, binding: Binding):
        if binding.kind == "key":
            self.api.keyUp(binding.target)
        else:
            self.api.mouseUp(button=binding.target)
        self.down.discard(binding)

    def move_mouse(self, dx: int, dy: int):
        self.api.moveRel(dx, dy, relative=True)

    def stop(self):
        for binding in list(self.down):
            self.release(binding)


class GamepadBackend:
    def __init__(self):
        self.pad = None
        self.buttons = {}
        self.axes = {name: 0.0 for name in
                     ("left_x", "left_y", "right_x", "right_y", "left_trigger", "right_trigger")}

    def start(self, profile: GameProfile):
        import vgamepad
        self.pad = vgamepad.VX360Gamepad()
        self.buttons = {
            name: getattr(vgamepad.XUSB_BUTTON, "XUSB_GAMEPAD_" + suffix)
            for name, suffix in GAMEPAD_BUTTONS.items()
        }

    def press(self, binding: Binding):
        self.pad.press_button(button=self.buttons[binding.target])
        self.pad.update()

    def release(self, binding: Binding):
        self.pad.release_button(button=self.buttons[binding.target])
        self.pad.update()

    def write_axis(self, target: str, value: float):
        self.axes[target] = value
        if target in ("left_x", "left_y"):
            self.pad.left_joystick_float(self.axes["left_x"], self.axes["left_y"])
        elif target in ("right_x", "right_y"):
            self.pad.right_joystick_float(self.axes["right_x"], self.axes["right_y"])
        elif target == "left_trigger":
            self.pad.left_trigger_float(value)
        else:
            self.pad.right_trigger_float(value)
        self.pad.update()

    def stop(self):
        if self.pad is not None:
            self.pad.reset()
            self.pad.update()
            self.pad = None


class GameProfiler:
    def __init__(self, profile: GameProfile):
        self.profile = profile
        self.lock = threading.RLock()
        self.backend = None
        self.running = False
        self.held: set[str] = set()
        self.levels: dict[str, dict[str, float]] = {}
        self.timers: dict[str, threading.Timer] = {}
        self.ticker: threading.Thread | None = None
        self.ticker_stop: threading.Event | None = None
        atexit.register(self.stop)

    def start(self):
        with self.lock:
            if self.running:
                return
            self.backend = KeyboardMouseBackend() if self.profile.controls == "keyboard_mouse" else GamepadBackend()
            self.backend.start(self.profile)
            self.running = True
            if self.profile.needs_mouse_ticker:
                self.ticker_stop = threading.Event()
                self.ticker = threading.Thread(
                    target=self.tick_loop, args=(self.ticker_stop,), daemon=True, name="game-mouse"
                )
                self.ticker.start()

    def stop(self):
        with self.lock:
            if not self.running:
                return
            self.release_all()
            self.running = False
            backend, self.backend = self.backend, None
            thread, self.ticker = self.ticker, None
            if self.ticker_stop is not None:
                self.ticker_stop.set()
        if thread is not None:
            thread.join(timeout=1.0)
        backend.stop()

    def action(self, name, argument=None, duration=None):
        key = name.lower()
        if argument is not None:
            grouped = f"{key}.{str(argument).lower()}"
            if grouped in self.profile.bindings:
                key = grouped
            elif duration is None:
                duration = argument
        binding = self.profile.bindings.get(key)
        if binding is None:
            return
        if duration is None and binding.mode == "hold":
            with self.lock:
                self.cancel_timer(key)
                self.press(key)
            return
        seconds = self.profile.settings["tap_time"] if duration is None else parse_duration(duration)
        self.hold(key, seconds)

    def release(self, name, argument=None):
        key = name.lower() if argument is None else f"{name.lower()}.{str(argument).lower()}"
        for bound in list(self.profile.bindings):
            if bound == key or (argument is None and bound.startswith(key + ".")):
                with self.lock:
                    self.cancel_timer(bound)
                    self.release_locked(bound)

    def release_all(self):
        with self.lock:
            for timer in self.timers.values():
                timer.cancel()
            self.timers.clear()
            if not self.running:
                return
            for name in list(self.held):
                self.backend.release(self.profile.bindings[name])
            self.held.clear()
            self.levels.clear()
            for target in {b.target for b in self.profile.bindings.values() if b.kind == "axis"}:
                self.backend.write_axis(target, 0.0)

    def press(self, name):
        with self.lock:
            binding = self.profile.bindings[name]
            if binding.analog:
                level = (binding.sign or 1) * binding.force
                key = axis_key(binding)
                if self.levels.get(key, {}).get(name) == level:
                    return
                self.levels.setdefault(key, {})[name] = level
                self.apply_axis(binding)
            elif name not in self.held:
                self.backend.press(binding)
                self.held.add(name)

    def hold(self, name, seconds):
        with self.lock:
            self.cancel_timer(name)
            self.press(name)
            timer = threading.Timer(seconds, lambda: self.finish_hold(name, timer))
            timer.daemon = True
            self.timers[name] = timer
        timer.start()

    def finish_hold(self, name, timer):
        with self.lock:
            if self.timers.get(name) is timer:
                del self.timers[name]
                self.release_locked(name)

    def cancel_timer(self, name):
        timer = self.timers.pop(name, None)
        if timer is not None:
            timer.cancel()

    def release_locked(self, name):
        if not self.running:
            return
        binding = self.profile.bindings[name]
        if binding.analog:
            if self.levels.get(axis_key(binding), {}).pop(name, None) is not None:
                self.apply_axis(binding)
        elif name in self.held:
            self.held.discard(name)
            self.backend.release(binding)

    def axis_total(self, key):
        return max(-1.0, min(1.0, sum(self.levels.get(key, {}).values())))

    def apply_axis(self, binding):
        if binding.kind != "axis":
            return
        total = self.axis_total(axis_key(binding))
        if binding.target in TRIGGERS:
            total = max(total, 0.0)
        self.backend.write_axis(binding.target, total)

    def tick_loop(self, stop):
        with self.lock:
            speed = self.profile.settings["mouse_speed"]
            interval = 1.0 / self.profile.settings["tick_rate"]
        remainder_x = remainder_y = 0.0
        next_tick = time.perf_counter()
        while not stop.is_set():
            with self.lock:
                if not self.running or self.backend is None:
                    break
                level_x = self.axis_total("mouse_axis:x")
                level_y = self.axis_total("mouse_axis:y")
                backend = self.backend
            remainder_x += level_x * speed * interval
            remainder_y -= level_y * speed * interval
            move_x, move_y = int(remainder_x), int(remainder_y)
            remainder_x -= move_x
            remainder_y -= move_y
            if move_x or move_y:
                backend.move_mouse(move_x, move_y)
            next_tick += interval
            stop.wait(max(0.0, next_tick - time.perf_counter()))