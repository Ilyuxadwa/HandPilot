import math
import os
import time
import urllib.request

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

GESTURE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
GESTURE_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "gesture_recognizer.task")

# Canned poses from MediaPipe's classifier that we act on. "Victory" and
# "Pointing_Up" are deliberately left out: their physical hand shapes are now
# claimed by the custom pointer-state logic below (point / click_left /
# click_right), so the canned classifier would never get a chance to report
# them anyway — pointer-state is checked first every frame.
STATIC_GESTURES = {"Open_Palm", "Closed_Fist", "Thumb_Up", "Thumb_Down", "ILoveYou"}

SWIPE_HISTORY_SECONDS = 0.6
SWIPE_MIN_DISTANCE = 0.25
SWIPE_DOMINANCE_RATIO = 0.5  # perpendicular-axis movement must stay under this fraction of the dominant axis
SWIPE_COOLDOWN_SECONDS = 1.0

STATIC_CONFIRM_FRAMES = 3
STATIC_COOLDOWN_SECONDS = 1.0

# Pinch isn't one of MediaPipe's canned categories, so it's detected from raw
# landmark distance instead: thumb tip (4) and index tip (8) closer together
# than this (normalized 0-1 image units) counts as a pinch. Untuned guess —
# watch the "pinch dist" readout in the preview window and adjust. Not bound
# to any action right now (left/right click moved to the pointer-state
# scheme below) but still detected in case it's useful later.
PINCH_DISTANCE_THRESHOLD = 0.06

# How far (in normalized y) a fingertip must sit above its own PIP joint to
# count as "extended". Untuned guess, assumes a roughly upright hand facing
# the camera — watch the "pointer state" readout in the preview and adjust.
FINGER_EXTENDED_MARGIN = 0.02


def download_gesture_model(logger=None):
    """Downloads the gesture_recognizer.task model bundle on first run, same
    pattern as openwakeword.utils.download_models() elsewhere in the app."""
    if os.path.exists(GESTURE_MODEL_PATH):
        return

    os.makedirs(os.path.dirname(GESTURE_MODEL_PATH), exist_ok=True)

    if logger:
        logger.info("Downloading MediaPipe gesture recognizer model...")

    urllib.request.urlretrieve(GESTURE_MODEL_URL, GESTURE_MODEL_PATH)


class SwipeTracker:
    """Tracks a hand's wrist position (normalized 0-1 image coordinates) over
    a short rolling time window and detects a swipe (left/right/up/down) from
    the net displacement, using whichever axis dominates."""

    def __init__(self):
        self.history = []

    def update(self, x, y, timestamp):
        self.history.append((timestamp, x, y))
        cutoff = timestamp - SWIPE_HISTORY_SECONDS
        self.history = [entry for entry in self.history if entry[0] >= cutoff]

    def detect_swipe(self):
        if len(self.history) < 2:
            return None

        start_time, start_x, start_y = self.history[0]
        end_time, end_x, end_y = self.history[-1]

        delta_x = end_x - start_x
        delta_y = end_y - start_y

        if abs(delta_x) >= SWIPE_MIN_DISTANCE and abs(delta_y) <= abs(delta_x) * SWIPE_DOMINANCE_RATIO:
            direction = "swipe_right" if delta_x > 0 else "swipe_left"
            self.history.clear()
            return direction

        if abs(delta_y) >= SWIPE_MIN_DISTANCE and abs(delta_x) <= abs(delta_y) * SWIPE_DOMINANCE_RATIO:
            # image y grows downward, so a positive delta_y means the hand moved down
            direction = "swipe_down" if delta_y > 0 else "swipe_up"
            self.history.clear()
            return direction

        return None

    def reset(self):
        self.history.clear()


class GestureDetector:
    """Wraps MediaPipe's GestureRecognizer task (canned static poses), a
    landmark-distance pinch check, a custom "pointer state" check (see
    get_pointer_state), and a SwipeTracker (motion gestures) into a single
    per-frame call.

    Not thread-safe on its own; GestureController owns one instance and
    drives it from a single background thread, same as the voice pipeline's
    controllers own their underlying detectors."""

    def __init__(self, logger=None):
        self.logger = logger
        download_gesture_model(logger)

        base_options = mp_python.BaseOptions(model_asset_path=GESTURE_MODEL_PATH)
        options = mp_vision.GestureRecognizerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=1,
        )
        self.recognizer = mp_vision.GestureRecognizer.create_from_options(options)

        self.swipe_tracker = SwipeTracker()
        self.pending_static_gesture = None
        self.pending_static_count = 0
        self.last_static_fire_time = 0.0
        self.last_swipe_fire_time = 0.0
        self.start_time = time.time()

        # Live, undebounced state for preview/debugging purposes and for
        # GestureController to read every frame. Unlike the return value of
        # process_frame, these update every frame regardless of confirmation
        # counts or cooldowns.
        self.last_hand_landmarks = None
        self.last_raw_gesture_name = None
        self.last_pinch_distance = None
        self.last_pointer_state = None

    def process_frame(self, frame):
        """frame: BGR numpy array from OpenCV (e.g. cv2.VideoCapture.read()).
        Returns a lowercase gesture name string ('open_palm', 'click_left',
        'swipe_left', etc.) when one is confidently recognized this call,
        otherwise None. 'point' is NOT returned here even while active — it's
        a continuous state, read from last_pointer_state instead, since it
        represents "cursor is following the hand" rather than a one-shot
        event."""
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        timestamp_ms = int((time.time() - self.start_time) * 1000)

        result = self.recognizer.recognize_for_video(mp_image, timestamp_ms)
        now = time.time()

        landmarks = result.hand_landmarks[0] if result.hand_landmarks else None
        self.last_hand_landmarks = landmarks

        canned_name = None
        if result.gestures and result.gestures[0]:
            canned_name = result.gestures[0][0].category_name
        self.last_raw_gesture_name = canned_name

        is_pinching = False
        self.last_pinch_distance = None
        pointer_state = None

        if landmarks:
            thumb_tip = landmarks[4]
            index_tip = landmarks[8]
            self.last_pinch_distance = math.hypot(thumb_tip.x - index_tip.x, thumb_tip.y - index_tip.y)
            is_pinching = self.last_pinch_distance < PINCH_DISTANCE_THRESHOLD

            pointer_state = self.get_pointer_state(landmarks)

            wrist = landmarks[0]
            if pointer_state is None:
                self.swipe_tracker.update(wrist.x, wrist.y, now)
            else:
                # Actively pointing/clicking moves the whole hand around the
                # frame, which would otherwise look like a swipe — don't let
                # that stale motion leak into a swipe check once we're done.
                self.swipe_tracker.reset()
        else:
            self.swipe_tracker.reset()

        self.last_pointer_state = pointer_state

        if pointer_state is None:
            swipe = self.swipe_tracker.detect_swipe()
            if swipe and now - self.last_swipe_fire_time > SWIPE_COOLDOWN_SECONDS:
                self.last_swipe_fire_time = now
                self.reset_static_debounce()
                return swipe

        candidate_name = None
        if pointer_state in ("click_left", "click_right"):
            candidate_name = pointer_state
        elif pointer_state == "point":
            candidate_name = None  # continuous state, never a discrete/debounced event
        elif is_pinching:
            candidate_name = "Pinch"
        elif canned_name in STATIC_GESTURES:
            candidate_name = canned_name

        fired = self.debounce_static_gesture(candidate_name, now)
        if fired:
            return fired.lower()

        return None

    def get_pointer_state(self, landmarks):
        """Reads index/middle/ring/pinky finger extension from raw landmarks
        to distinguish a family of "virtual mouse" hand shapes that the
        canned classifier can't tell apart:
        - both index and middle extended, ring+pinky curled -> "point"
          (classic Victory/peace-sign shape) -> cursor follows the hand
        - only middle extended (index curled down) -> "click_left"
        - only index extended (middle curled down) -> "click_right"
        Ring/pinky must stay curled for any of these, so an open palm
        (which also has index+middle extended) doesn't get mistaken for
        "point"."""
        index_extended = landmarks[8].y < landmarks[6].y - FINGER_EXTENDED_MARGIN
        middle_extended = landmarks[12].y < landmarks[10].y - FINGER_EXTENDED_MARGIN
        ring_extended = landmarks[16].y < landmarks[14].y - FINGER_EXTENDED_MARGIN
        pinky_extended = landmarks[20].y < landmarks[18].y - FINGER_EXTENDED_MARGIN

        if ring_extended or pinky_extended:
            return None

        if index_extended and middle_extended:
            return "point"
        if middle_extended and not index_extended:
            return "click_left"
        if index_extended and not middle_extended:
            return "click_right"

        return None

    def debounce_static_gesture(self, candidate_name, now):
        """Generic confirm-N-frames + cooldown state machine, shared by
        canned classifier poses, the custom pinch check, and click_left /
        click_right so they all behave the same way from the caller's
        perspective."""
        if candidate_name is None:
            self.reset_static_debounce()
            return None

        if candidate_name == self.pending_static_gesture:
            self.pending_static_count += 1
        else:
            self.pending_static_gesture = candidate_name
            self.pending_static_count = 1

        confirmed = self.pending_static_count >= STATIC_CONFIRM_FRAMES
        cooled_down = now - self.last_static_fire_time > STATIC_COOLDOWN_SECONDS

        if confirmed and cooled_down:
            self.last_static_fire_time = now
            self.pending_static_count = 0
            return candidate_name

        return None

    def reset_static_debounce(self):
        self.pending_static_gesture = None
        self.pending_static_count = 0

    def close(self):
        self.recognizer.close()