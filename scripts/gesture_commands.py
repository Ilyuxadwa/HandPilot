import pyautogui
import screen_brightness_control as sbc

from commands import volume_up, volume_down

pyautogui.FAILSAFE = True

# Cursor tracking only uses the comfortable middle portion of the camera
# frame as "active" — hands rarely reach the literal 0/1 edges in practice —
# then maps that rectangle onto the FULL screen, so it's an absolute mapping:
# the active region's top-right corner = the screen's top-right corner, etc.
# Untuned guess; narrow/widen these while testing if reaching screen edges
# feels too easy/hard for your setup and camera distance.
ACTIVE_REGION_X_MIN = 0.15
ACTIVE_REGION_X_MAX = 0.85
ACTIVE_REGION_Y_MIN = 0.15
ACTIVE_REGION_Y_MAX = 0.85

# Keeps our own commanded position a couple pixels off the literal screen
# corner. pyautogui.FAILSAFE aborts (raises) if the cursor is ever found
# exactly on a corner pixel when an action fires — without this margin,
# gesture-driven movement reaching a "corner" could trip the failsafe on the
# very next call.
SCREEN_EDGE_MARGIN_PX = 2

# Exponential-moving-average smoothing state for cursor movement, so raw
# landmark jitter doesn't translate directly into a shaky cursor. Untuned —
# 0 = no smoothing (raw position every frame), closer to 1 = more lag but
# steadier. Reset when gesture tracking (re)starts via reset_mouse_smoothing().
smoothed_x = None
smoothed_y = None
SMOOTHING_FACTOR = 0.5


def remap_to_range(value, in_min, in_max, out_min, out_max):
    """Linearly maps value from [in_min, in_max] to [out_min, out_max],
    clamping value to the input range first so anything beyond the active
    region just pins to the corresponding screen edge instead of overshooting."""
    clamped = max(in_min, min(in_max, value))
    ratio = (clamped - in_min) / (in_max - in_min)
    return out_min + ratio * (out_max - out_min)


def move_mouse(x, y):
    """x, y: normalized (0-1) coordinates of the tracked cursor point (the
    midpoint between the index and middle fingertips — see GestureController),
    already mirrored to match what the user sees of their own hand."""
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
        # The real cursor was already sitting on a screen corner (e.g. moved
        # there manually) the instant this call fired. Skip this frame rather
        # than crashing the whole gesture-detection thread over it.
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


# How much one brightness "notch" changes the screen, in percent. Untuned —
# adjust if steps feel too big/small.
BRIGHTNESS_STEP_PERCENT = 5


def volume_up_step():
    volume_up([])  # reuses commands.py's keyboard-based volume control as-is


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


# Discrete gesture_name -> action function, one dict per mode. Continuous
# cursor movement is handled separately (see GestureCommandController) since
# it isn't a discrete named event. click_left/click_right come from the
# pointer-state logic (dropping the index or middle finger while in the
# Victory-shaped "point" pose). open_palm_increase/decrease and
# closed_fist_increase/decrease come from holding Open_Palm/Closed_Fist and
# moving up-or-right / down-or-left (see AdjustmentTracker).
STANDARD_GESTURE_COMMANDS = {
    "click_left": click_left,
    "click_right": click_right,
    "open_palm_increase": volume_up_step,
    "open_palm_decrease": volume_down_step,
    "closed_fist_increase": brightness_up_step,
    "closed_fist_decrease": brightness_down_step,
}

GAMING_GESTURE_COMMANDS = {
    # populated later
}