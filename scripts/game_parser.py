from __future__ import annotations

import configparser
import re
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


@dataclass(frozen=True)
class Step:
    wait: str | None = None
    actions: tuple[tuple[str, str | None], ...] = ()


@dataclass
class GameProfile:
    name: str
    controls: str
    path: Path
    settings: dict[str, float] = field(default_factory=dict)
    bindings: dict[str, Binding] = field(default_factory=dict)
    defaults: dict[str, str] = field(default_factory=dict)
    combos: dict[str, list[Step]] = field(default_factory=dict)

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


def parse_combo(text: str) -> list[Step]:
    steps = []
    for part in text.split(","):
        part = part.strip()
        if part.lower().startswith("wait "):
            steps.append(Step(wait=part[5:].strip()))
        else:
            actions = []
            for item in part.split("+"):
                tokens = item.split()
                actions.append((tokens[0].lower(), tokens[1] if len(tokens) > 1 else None))
            steps.append(Step(actions=tuple(actions)))
    return steps


def is_sequence(text: str) -> bool:
    return "," in text or " + " in text or text.lower().startswith("wait ")


def parse_sequence(name: str, text: str, bindings: dict[str, Binding]) -> list[Step]:
    steps = []
    count = 0
    for part in text.split(","):
        part = part.strip()
        if part.lower().startswith("wait "):
            steps.append(Step(wait=part[5:].strip()))
            continue
        actions = []
        for item in re.split(r"\s\+\s", part):
            tokens = item.split()
            options = [t for t in tokens[1:] if t.lower() in ("hold", "click") or t.lower().startswith("force=")]
            duration = next((t for t in tokens[1:] if t not in options), None)
            count += 1
            hidden = f"{name}#{count}"
            bindings[hidden] = parse_binding(" ".join([tokens[0], *options]))
            actions.append((hidden, duration))
        steps.append(Step(actions=tuple(actions)))
    return steps


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

    bindings = {}
    combos = {}
    for action, raw in parser["bindings"].items():
        if is_sequence(raw):
            combos[action] = parse_sequence(action, raw, bindings)
        else:
            bindings[action] = parse_binding(raw)
    if parser.has_section("combos"):
        combos.update({name: parse_combo(raw) for name, raw in parser["combos"].items()})

    return GameProfile(
        name=parser["game"].get("name", path.stem).strip(),
        controls=parser["game"]["controls"].strip().lower(),
        path=path,
        settings=settings,
        bindings=bindings,
        defaults=dict(parser["defaults"]) if parser.has_section("defaults") else {},
        combos=combos,
    )