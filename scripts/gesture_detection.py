import math
import os
import time
import urllib.request

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

GESTURE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
GESTURE_MODEL_PATH = "assets/models/cv/gesture_recognizer.task"

# Canned poses from MediaPipe's classifier that we act on as one-shot events.
# "Victory" and "Pointing_Up" are left out: their shapes are claimed by the
# pointer-state logic (point/click_left/click_right). "Open_Palm" and
# "Closed_Fist" are left out too: their shapes are now claimed by the
# hold-to-adjust logic below (ADJUSTMENT_GESTURES) instead of firing once.
STATIC_GESTURES = {"Thumb_Up", "Thumb_Down", "ILoveYou"}

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

# Poses that, while held, enable continuous value adjustment (volume,
# brightness, ...) instead of firing as a discrete event — see
# AdjustmentTracker. Moving up/right while holding the pose increases the
# bound value, down/left decreases it; gesture_commands.py decides which
# value each pose controls.
ADJUSTMENT_GESTURES = {"Open_Palm", "Closed_Fist"}

# Combined (rightward + upward, since image y grows downward) normalized
# wrist movement needed to register one adjustment "step" — like a notch on
# a scroll wheel. Untuned guess; watch the "adjustment" readout in the
# preview and adjust if steps feel too twitchy or too sluggish.
ADJUSTMENT_STEP_DISTANCE = 0.05

# Standard 21-point MediaPipe hand landmark topology, for drawing the hand
# skeleton in the preview. Stable across API versions even though
# mediapipe.solutions.drawing_utils (which used to draw this for you) was
# removed from the package.
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]

FIRED_LABEL_DURATION_SECONDS = 1.0
PREVIEW_WINDOW_NAME = "HandPilot Gesture Preview"


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


class AdjustmentTracker:
    """While a hold-to-adjust pose is active, tracks a reference point and
    emits 'increase'/'decrease' once cumulative movement since the last step
    crosses ADJUSTMENT_STEP_DISTANCE — like notches on a scroll wheel, so
    holding the pose and moving further yields more steps. Movement right
    and up both count as positive ("increase"); left and down both count as
    negative ("decrease"), combined into one score rather than tracked as
    two separate axes."""

    def __init__(self):
        self.reference_x = None
        self.reference_y = None

    def update(self, x, y):
        if self.reference_x is None:
            self.reference_x, self.reference_y = x, y
            return None

        # image y grows downward, so -delta_y is positive when the hand moves up
        combined_delta = (x - self.reference_x) - (y - self.reference_y)

        if combined_delta >= ADJUSTMENT_STEP_DISTANCE:
            self.reference_x, self.reference_y = x, y
            return "increase"

        if combined_delta <= -ADJUSTMENT_STEP_DISTANCE:
            self.reference_x, self.reference_y = x, y
            return "decrease"

        return None

    def reset(self):
        self.reference_x = None
        self.reference_y = None


class GestureDetector:
    """Wraps MediaPipe's GestureRecognizer task (canned static poses), a
    landmark-distance pinch check, a custom "pointer state" check (see
    get_pointer_state), a SwipeTracker (motion gestures), and an
    AdjustmentTracker (hold-to-adjust gestures) into a single per-frame call.
    Also owns everything OpenCV-related: the webcam capture (open_camera/
    read_frame) and the debug preview window (render_preview).
    GestureController has no cv2 dependency at all — it only does thread
    lifecycle and dispatch.

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
        self.capture = None

        self.swipe_tracker = SwipeTracker()
        self.adjustment_tracker = AdjustmentTracker()
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
        self.last_adjustment_gesture = None
        self.last_cursor_position = None
        self.last_fired_gesture = None
        self.last_fired_time = 0.0

    def process_frame(self, frame):
        """frame: BGR numpy array from OpenCV (e.g. cv2.VideoCapture.read()).
        Returns a lowercase gesture name string ('thumb_up', 'click_left',
        'swipe_left', 'open_palm_increase', etc.) when one is confidently
        recognized this call, otherwise None. 'point' is NOT returned here
        even while active — it's a continuous state: read last_cursor_position
        for where the cursor should go, since it represents "cursor is
        following the hand" rather than a one-shot event. Likewise which
        adjustment pose (if any) is currently held is read from
        last_adjustment_gesture, separate from the 'increase'/'decrease' step
        events this returns."""
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
        adjustment_gesture = None
        self.last_cursor_position = None

        if landmarks:
            thumb_tip = landmarks[4]
            index_tip = landmarks[8]
            self.last_pinch_distance = math.hypot(thumb_tip.x - index_tip.x, thumb_tip.y - index_tip.y)
            is_pinching = self.last_pinch_distance < PINCH_DISTANCE_THRESHOLD

            pointer_state = self.get_pointer_state(landmarks)

            if pointer_state == "point":
                self.last_cursor_position = self.get_cursor_position(landmarks)

            if pointer_state is None and canned_name in ADJUSTMENT_GESTURES:
                adjustment_gesture = canned_name

        self.last_pointer_state = pointer_state
        self.last_adjustment_gesture = adjustment_gesture

        # Swipe tracking is only meaningful when the hand isn't busy doing
        # something else that also moves it around the frame.
        active_continuous_gesture = pointer_state is not None or adjustment_gesture is not None
        if landmarks and not active_continuous_gesture:
            wrist = landmarks[0]
            self.swipe_tracker.update(wrist.x, wrist.y, now)
        else:
            self.swipe_tracker.reset()

        if not active_continuous_gesture:
            swipe = self.swipe_tracker.detect_swipe()
            if swipe and now - self.last_swipe_fire_time > SWIPE_COOLDOWN_SECONDS:
                self.last_swipe_fire_time = now
                self.reset_static_debounce()
                self.adjustment_tracker.reset()
                return self.record_gesture_fired(swipe)

        if adjustment_gesture:
            wrist = landmarks[0]
            step = self.adjustment_tracker.update(wrist.x, wrist.y)
            if step:
                self.reset_static_debounce()
                return self.record_gesture_fired(f"{adjustment_gesture.lower()}_{step}")
        else:
            self.adjustment_tracker.reset()

        candidate_name = None
        if pointer_state in ("click_left", "click_right"):
            candidate_name = pointer_state
        elif pointer_state == "point":
            candidate_name = None  # continuous state, never a discrete/debounced event
        elif adjustment_gesture:
            candidate_name = None  # continuous state, handled above instead
        elif is_pinching:
            candidate_name = "Pinch"
        elif canned_name in STATIC_GESTURES:
            candidate_name = canned_name

        fired = self.debounce_static_gesture(candidate_name, now)
        if fired:
            return self.record_gesture_fired(fired.lower())

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

    def get_cursor_position(self, landmarks):
        """The point used to drive the mouse cursor while pointer_state ==
        'point': x is the midpoint between the index and middle fingertips;
        y follows whichever of the two sits higher on screen (smaller
        normalized y), so dropping one finger to click doesn't pull the
        cursor's height down with it. Returns (x, y) in normalized (0-1)
        coordinates."""
        index_tip = landmarks[8]
        middle_tip = landmarks[12]
        cursor_x = (index_tip.x + middle_tip.x) / 2
        cursor_y = min(index_tip.y, middle_tip.y)
        return cursor_x, cursor_y

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

    def open_camera(self, camera_index=0):
        """Opens the webcam via OpenCV. Returns True on success, False if the
        device couldn't be opened — the caller decides what to do about that
        (GestureController logs an error and stops)."""
        self.capture = cv2.VideoCapture(camera_index)
        return self.capture.isOpened()

    def read_frame(self):
        """Reads one frame from the camera, already mirrored (flipped
        horizontally) so left/right matches what the user sees of themselves.
        Returns None if the read failed (e.g. camera briefly busy)."""
        success, frame = self.capture.read()
        if not success:
            return None
        return cv2.flip(frame, 1)

    def record_gesture_fired(self, name):
        """Centralizes the "something fired" bookkeeping used by the preview
        window's brief 'FIRED: ...' flash, so every return path in
        process_frame that reports a discrete gesture goes through here."""
        self.last_fired_gesture = name
        self.last_fired_time = time.time()
        return name

    def render_preview(self, frame, active_region):
        """Draws landmarks + detection state onto frame and shows it in a
        window. active_region is (x_min, x_max, y_min, y_max), normalized
        0-1 — the camera-frame rectangle that GestureCommandController maps
        onto the full screen for cursor control (see
        GestureCommandController.get_active_region); drawn purely as a
        visualization aid, this method has no opinion on what the mapping
        means. Returns False if the user pressed 'q' to close the preview."""
        height, width = frame.shape[:2]

        x_min, x_max, y_min, y_max = active_region
        top_left = (int(x_min * width), int(y_min * height))
        bottom_right = (int(x_max * width), int(y_max * height))
        cv2.rectangle(frame, top_left, bottom_right, (0, 255, 255), 2)
        cv2.putText(frame, "cursor zone", (top_left[0], top_left[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        if self.last_hand_landmarks:
            self.draw_landmarks(frame, self.last_hand_landmarks)

            if self.last_cursor_position:
                cursor_x, cursor_y = self.last_cursor_position
                cv2.circle(frame, (int(cursor_x * width), int(cursor_y * height)), 8, (255, 0, 255), 2)

        raw_gesture = self.last_raw_gesture_name or "no hand / no gesture"
        cv2.putText(frame, f"raw: {raw_gesture}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        pointer_state = self.last_pointer_state or "none"
        cv2.putText(frame, f"pointer state: {pointer_state}", (10, 130),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)

        adjustment_gesture = self.last_adjustment_gesture or "none"
        cv2.putText(frame, f"adjustment: {adjustment_gesture}", (10, 160),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)

        if self.last_pinch_distance is not None:
            cv2.putText(frame, f"pinch dist: {self.last_pinch_distance:.3f}", (10, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        showing_fired = (self.last_fired_gesture
                         and time.time() - self.last_fired_time < FIRED_LABEL_DURATION_SECONDS)
        if showing_fired:
            cv2.putText(frame, f"FIRED: {self.last_fired_gesture}", (10, 65),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

        cv2.imshow(PREVIEW_WINDOW_NAME, frame)
        return cv2.waitKey(1) & 0xFF != ord("q")

    def draw_landmarks(self, frame, landmarks):
        height, width = frame.shape[:2]
        points = [(int(landmark.x * width), int(landmark.y * height)) for landmark in landmarks]

        for start_index, end_index in HAND_CONNECTIONS:
            cv2.line(frame, points[start_index], points[end_index], (0, 255, 0), 2)

        for point in points:
            cv2.circle(frame, point, 4, (0, 0, 255), -1)

        return frame

    def close(self):
        self.recognizer.close()

        if self.capture:
            self.capture.release()
            self.capture = None

        cv2.destroyAllWindows()