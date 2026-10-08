from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

GAMEPAD_BUTTONS = {
    "a": "A", "b": "B", "x": "X", "y": "Y",
    "lb": "LEFT_SHOULDER", "rb": "RIGHT_SHOULDER",
    "start": "START", "back": "BACK", "guide": "GUIDE",
    "ls": "LEFT_THUMB", "rs": "RIGHT_THUMB",
    "dpad_up": "DPAD_UP", "dpad_down": "DPAD_DOWN",
    "dpad_left": "DPAD_LEFT", "dpad_right": "DPAD_RIGHT",
}

TRIGGERS = ("left_trigger", "right_trigger")
MOUSE_BUTTONS = ("left", "right", "middle")

DEFAULT_SETTINGS = {
    "mouse_speed": 600.0,
    "tick_rate": 60.0,
    "tap_time": 0.08,
}


@dataclass(frozen=True)
class Binding:
    kind: str
    target: str
    sign: int = 0
    mode: str = "click"
    force: float = 1.0

    @property
    def analog(self) -> bool:
        return self.kind in ("mouse_axis", "axis")


@dataclass
class GameProfile:
    name: str
    controls: str
    path: Path
    settings: dict[str, float] = field(default_factory=dict)
    bindings: dict[str, Binding] = field(default_factory=dict)
    defaults: dict[str, str] = field(default_factory=dict)

    @property
    def needs_mouse_ticker(self) -> bool:
        return any(binding.kind == "mouse_axis" for binding in self.bindings.values())


def parse_binding(text: str) -> Binding:
    tokens = text.split()
    kind, target = tokens[0].lower().split(":", 1)

    sign = 0
    if kind in ("axis", "mouse") and target[-1] in "+-":
        sign = 1 if target[-1] == "+" else -1
        target = target[:-1]
    if kind == "mouse":
        kind = "mouse_button" if target in MOUSE_BUTTONS else "mouse_axis"

    mode = "hold" if kind in ("axis", "mouse_axis") else "click"
    force = 1.0
    for token in tokens[1:]:
        if token.lower().startswith("force="):
            force = float(token[6:])
        else:
            mode = token.lower()
    return Binding(kind, target, sign, mode, force)


def parse_hpgame(path: str | Path) -> GameProfile:
    path = Path(path)
    parser = configparser.ConfigParser(
        delimiters=("=",),
        comment_prefixes=("#", ";"),
        inline_comment_prefixes=("#",),
        interpolation=None,
    )
    parser.read(path, encoding="utf-8")

    settings = dict(DEFAULT_SETTINGS)
    if parser.has_section("settings"):
        settings.update({key: float(value) for key, value in parser["settings"].items()})

    return GameProfile(
        name=parser["game"].get("name", path.stem).strip(),
        controls=parser["game"]["controls"].strip().lower(),
        path=path,
        settings=settings,
        bindings={action: parse_binding(raw) for action, raw in parser["bindings"].items()},
        defaults=dict(parser["defaults"]) if parser.has_section("defaults") else {},
    )