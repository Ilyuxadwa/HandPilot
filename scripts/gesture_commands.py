import pyautogui

pyautogui.FAILSAFE = True

# Exponential-moving-average smoothing state for cursor movement, so raw
# landmark jitter doesn't translate directly into a shaky cursor. Untuned —
# 0 = no smoothing (raw position every frame), closer to 1 = more lag but
# steadier. Reset when gesture tracking (re)starts via reset_mouse_smoothing().
smoothed_x = None
smoothed_y = None
SMOOTHING_FACTOR = 0.5


def move_mouse(x, y):
    """x, y: normalized (0-1) index fingertip coordinates from the camera
    frame, already mirrored to match what the user sees of their own hand."""
    global smoothed_x, smoothed_y

    screen_width, screen_height = pyautogui.size()
    target_x = x * screen_width
    target_y = y * screen_height

    if smoothed_x is None:
        smoothed_x, smoothed_y = target_x, target_y
    else:
        smoothed_x += (target_x - smoothed_x) * (1 - SMOOTHING_FACTOR)
        smoothed_y += (target_y - smoothed_y) * (1 - SMOOTHING_FACTOR)

    pyautogui.moveTo(smoothed_x, smoothed_y, _pause=False)


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


# Discrete gesture_name -> action function, one dict per mode. Continuous
# cursor movement is handled separately (see GestureCommandController) since
# it isn't a discrete named event. click_left/click_right come from the
# custom pointer-state logic (dropping the index or middle finger while in
# the Victory-shaped "point" pose), not from the canned classifier.
STANDARD_GESTURE_COMMANDS = {
    "click_left": click_left,
    "click_right": click_right,
}

GAMING_GESTURE_COMMANDS = {
    # populated later
}