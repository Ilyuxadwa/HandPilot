from flet import Icons
import random
import json
import os

from game_profiler import GameProfiler
from game_parser import parse_hpgame



with open("config/icons.json", "r", encoding="utf-8") as f:
    icon_map = json.load(f)

with open("config/welcome_messages.json", "r", encoding="utf-8") as f:
    welcome_messages = json.load(f)



def get_games():
    profilers = {}
    for file_name in sorted(os.listdir("assets/games")):
        if file_name.lower().endswith(".hpgame"):
            profiler = GameProfiler(parse_hpgame(os.path.join("assets/games", file_name)))
            profilers[profiler.profile.name] = profiler
    return profilers


def icon(name: str):
    icon_key = icon_map.get(name)
    if icon_key is None:
        raise KeyError(f"No icon mapped for '{name}'")
    icon_value = getattr(Icons, icon_key, None)
    if icon_value is None:
        raise AttributeError(f"ft.Icons has no attribute '{icon_key}'")
    return icon_value

def welcome_message():
    msg = random.choice(list(welcome_messages))
    return icon("welcome-"+welcome_messages.get(msg)), msg

def choose_sound(name: str):
    with open("config/sounds.json", "r", encoding="utf-8") as f:
        sound_map = json.load(f)
    sound_list = sound_map.get(name)
    if not sound_list:
        raise KeyError(f"No sounds mapped for '{name}'")
    return random.choice(sound_list)