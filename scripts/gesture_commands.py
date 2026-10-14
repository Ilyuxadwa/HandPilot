import pyautogui
import screen_brightness_control as sbc

from commands import volume_up, volume_down

pyautogui.FAILSAFE = True

ACTIVE_REGION_X_MIN = 0.15
ACTIVE_REGION_X_MAX = 0.85
ACTIVE_REGION_Y_MIN = 0.15
ACTIVE_REGION_Y_MAX = 0.85

SCREEN_EDGE_MARGIN_PX = 2

CURSOR_HAND_PRIORITY = ("right", "left")

smoothed_x = None
smoothed_y = None
SMOOTHING_FACTOR = 0.5

BRIGHTNESS_STEP_PERCENT = 5


def remap_to_range(value, in_min, in_max, out_min, out_max):
    clamped = max(in_min, min(in_max, value))
    ratio = (clamped - in_min) / (in_max - in_min)
    return out_min + ratio * (out_max - out_min)


def move_mouse(x, y):
    global smoothed_x, smoothed_y

    screen_width, screen_height = pyautogui.size()

    target_x = remap_to_range(x, ACTIVE_REGION_X_MIN, ACTIVE_REGION_X_MAX,
                               SCREEN_EDGE_MARGIN_PX, screen_width - 1 - SCREEN_EDGE_MARGIN_PX)
    target_y = remap_to_range(y, ACTIVE_REGION_Y_MIN, ACTIVE_REGION_Y_MAX,
                               SCREEN_EDGE_MARGIN_PX, screen_height - 1 - SCREEN_EDGE_MARGIN_PX)

    if smoothed_x is None:
        smoothed_x, smoothed_y = target_x, target_y
    else:
        smoothed_x += (target_x - smoothed_x) * (1 - SMOOTHING_FACTOR)
        smoothed_y += (target_y - smoothed_y) * (1 - SMOOTHING_FACTOR)

    try:
        pyautogui.moveTo(smoothed_x, smoothed_y, _pause=False)
    except pyautogui.FailSafeException:
        pass


def reset_mouse_smoothing():
    global smoothed_x, smoothed_y
    smoothed_x = None
    smoothed_y = None


def click_left():
    pyautogui.click(button="left")
    print("[gesture_commands] Left click")


def click_right():
    pyautogui.click(button="right")
    print("[gesture_commands] Right click")


def volume_up_step():
    volume_up([])


def volume_down_step():
    volume_down([])


def brightness_up_step():
    try:
        sbc.set_brightness(f"+{BRIGHTNESS_STEP_PERCENT}")
        print(f"[gesture_commands] Brightness +{BRIGHTNESS_STEP_PERCENT}%")
    except sbc.ScreenBrightnessError as e:
        print(f"[gesture_commands] Could not adjust brightness: {e}")


def brightness_down_step():
    try:
        sbc.set_brightness(f"-{BRIGHTNESS_STEP_PERCENT}")
        print(f"[gesture_commands] Brightness -{BRIGHTNESS_STEP_PERCENT}%")
    except sbc.ScreenBrightnessError as e:
        print(f"[gesture_commands] Could not adjust brightness: {e}")


STANDARD_GESTURE_COMMANDS = {
    "click_left": click_left,
    "click_right": click_right,
    "open_palm_increase": volume_up_step,
    "open_palm_decrease": volume_down_step,
    "closed_fist_increase": brightness_up_step,
    "closed_fist_decrease": brightness_down_step,
}

GAMING_GESTURE_COMMANDS = {}