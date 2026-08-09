from flet import Icons

import json
import random

with open("config/icons.json", "r", encoding="utf-8") as f:
    icon_map = json.load(f)

with open("config/welcome_messages.json", "r", encoding="utf-8") as f:
    welcome_messages = json.load(f)

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