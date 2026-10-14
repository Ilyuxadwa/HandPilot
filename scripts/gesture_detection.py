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

HAND_NAMES = ("left", "right")
SWAP_HANDEDNESS = False
HAND_CONTINUITY_DISTANCE = 0.2
HAND_COLORS = {"left": (0, 255, 0), "right": (0, 165, 255)}

STATIC_GESTURES = {"Thumb_Up", "Thumb_Down", "ILoveYou"}
ADJUSTMENT_GESTURES = {"Open_Palm", "Closed_Fist"}

SWIPE_HISTORY_SECONDS = 0.6
SWIPE_MIN_DISTANCE = 0.25
SWIPE_DOMINANCE_RATIO = 0.5
SWIPE_COOLDOWN_SECONDS = 1.0

STATIC_CONFIRM_FRAMES = 3
STATIC_COOLDOWN_SECONDS = 1.0

PINCH_DISTANCE_THRESHOLD = 0.06
FINGER_EXTENDED_MARGIN = 0.02
ADJUSTMENT_STEP_DISTANCE = 0.05

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
    if os.path.exists(GESTURE_MODEL_PATH):
        return

    os.makedirs(os.path.dirname(GESTURE_MODEL_PATH), exist_ok=True)

    if logger:
        logger.info("Downloading MediaPipe gesture recognizer model...")

    urllib.request.urlretrieve(GESTURE_MODEL_URL, GESTURE_MODEL_PATH)


class SwipeTracker:
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
            direction = "swipe_down" if delta_y > 0 else "swipe_up"
            self.history.clear()
            return direction

        return None

    def reset(self):
        self.history.clear()


class AdjustmentTracker:
    def __init__(self):
        self.reference_x = None
        self.reference_y = None

    def update(self, x, y):
        if self.reference_x is None:
            self.reference_x, self.reference_y = x, y
            return None

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


class HandState:
    def __init__(self):
        self.swipe_tracker = SwipeTracker()
        self.adjustment_tracker = AdjustmentTracker()
        self.pending_static_gesture = None
        self.pending_static_count = 0
        self.last_static_fire_time = 0.0
        self.last_swipe_fire_time = 0.0

        self.landmarks = None
        self.raw_gesture_name = None
        self.pinch_distance = None
        self.pointer_state = None
        self.adjustment_gesture = None
        self.cursor_position = None

    def clear(self):
        self.swipe_tracker.reset()
        self.adjustment_tracker.reset()
        self.reset_static_debounce()
        self.landmarks = None
        self.raw_gesture_name = None
        self.pinch_distance = None
        self.pointer_state = None
        self.adjustment_gesture = None
        self.cursor_position = None

    def update(self, landmarks, canned_name, now):
        self.landmarks = landmarks
        self.raw_gesture_name = canned_name
        self.cursor_position = None
        self.adjustment_gesture = None

        thumb_tip = landmarks[4]
        index_tip = landmarks[8]
        self.pinch_distance = math.hypot(thumb_tip.x - index_tip.x, thumb_tip.y - index_tip.y)
        is_pinching = self.pinch_distance < PINCH_DISTANCE_THRESHOLD

        self.pointer_state = self.get_pointer_state(landmarks)

        if self.pointer_state == "point":
            self.cursor_position = self.get_cursor_position(landmarks)

        if self.pointer_state is None and canned_name in ADJUSTMENT_GESTURES:
            self.adjustment_gesture = canned_name

        wrist = landmarks[0]
        active_continuous_gesture = self.pointer_state is not None or self.adjustment_gesture is not None

        if active_continuous_gesture:
            self.swipe_tracker.reset()
        else:
            self.swipe_tracker.update(wrist.x, wrist.y, now)
            swipe = self.swipe_tracker.detect_swipe()
            if swipe and now - self.last_swipe_fire_time > SWIPE_COOLDOWN_SECONDS:
                self.last_swipe_fire_time = now
                self.reset_static_debounce()
                self.adjustment_tracker.reset()
                return swipe

        if self.adjustment_gesture:
            step = self.adjustment_tracker.update(wrist.x, wrist.y)
            if step:
                self.reset_static_debounce()
                return f"{self.adjustment_gesture.lower()}_{step}"
        else:
            self.adjustment_tracker.reset()

        candidate_name = None
        if self.pointer_state in ("click_left", "click_right"):
            candidate_name = self.pointer_state
        elif self.pointer_state == "point" or self.adjustment_gesture:
            candidate_name = None
        elif is_pinching:
            candidate_name = "Pinch"
        elif canned_name in STATIC_GESTURES:
            candidate_name = canned_name

        fired = self.debounce_static_gesture(candidate_name, now)
        if fired:
            return fired.lower()

        return None

    def get_pointer_state(self, landmarks):
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
        index_tip = landmarks[8]
        middle_tip = landmarks[12]
        cursor_x = (index_tip.x + middle_tip.x) / 2
        cursor_y = min(index_tip.y, middle_tip.y)
        return cursor_x, cursor_y

    def debounce_static_gesture(self, candidate_name, now):
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


class GestureDetector:
    def __init__(self, logger=None):
        self.logger = logger
        download_gesture_model(logger)

        base_options = mp_python.BaseOptions(model_asset_path=GESTURE_MODEL_PATH)
        options = mp_vision.GestureRecognizerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=2,
        )
        self.recognizer = mp_vision.GestureRecognizer.create_from_options(options)
        self.capture = None
        self.start_time = time.time()

        self.hands = {hand: HandState() for hand in HAND_NAMES}
        self.cursor_positions = {}
        self.last_fired_label = None
        self.last_fired_time = 0.0

    def process_frame(self, frame):
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        timestamp_ms = int((time.time() - self.start_time) * 1000)

        result = self.recognizer.recognize_for_video(mp_image, timestamp_ms)
        now = time.time()

        assigned = self.assign_hands(result)
        events = []

        for hand in HAND_NAMES:
            state = self.hands[hand]

            if hand not in assigned:
                state.clear()
                continue

            landmarks, canned_name = assigned[hand]
            gesture = state.update(landmarks, canned_name, now)

            if gesture:
                self.last_fired_label = f"{hand}_{gesture}"
                self.last_fired_time = time.time()
                events.append((hand, gesture))

        self.cursor_positions = {
            hand: state.cursor_position
            for hand, state in self.hands.items()
            if state.cursor_position
        }

        return events

    def top_category(self, categories_per_hand, index):
        if index < len(categories_per_hand) and categories_per_hand[index]:
            return categories_per_hand[index][0].category_name
        return None

    def assign_hands(self, result):
        entries = []
        for index, landmarks in enumerate(result.hand_landmarks):
            entries.append((
                landmarks,
                self.top_category(result.gestures, index),
                self.top_category(result.handedness, index),
            ))

        if not entries:
            return {}

        if len(entries) >= 2:
            entries.sort(key=lambda entry: entry[0][0].x)
            return {
                "left": (entries[0][0], entries[0][1]),
                "right": (entries[-1][0], entries[-1][1]),
            }

        landmarks, canned_name, label = entries[0]
        wrist = landmarks[0]

        hand = self.nearest_previous_hand(wrist)

        if hand is None:
            hand = "left" if wrist.x < 0.5 else "right"
            if label and label.lower() in HAND_NAMES:
                hand = label.lower()
                if SWAP_HANDEDNESS:
                    hand = "right" if hand == "left" else "left"

        return {hand: (landmarks, canned_name)}

    def nearest_previous_hand(self, wrist):
        best_hand, best_distance = None, HAND_CONTINUITY_DISTANCE
        for hand, state in self.hands.items():
            if not state.landmarks:
                continue
            previous = state.landmarks[0]
            distance = math.hypot(wrist.x - previous.x, wrist.y - previous.y)
            if distance < best_distance:
                best_hand, best_distance = hand, distance
        return best_hand

    def open_camera(self, camera_index=0):
        self.capture = cv2.VideoCapture(camera_index)
        return self.capture.isOpened()

    def read_frame(self):
        success, frame = self.capture.read()
        if not success:
            return None
        return cv2.flip(frame, 1)

    def render_preview(self, frame, active_region):
        height, width = frame.shape[:2]

        x_min, x_max, y_min, y_max = active_region
        top_left = (int(x_min * width), int(y_min * height))
        bottom_right = (int(x_max * width), int(y_max * height))
        cv2.rectangle(frame, top_left, bottom_right, (0, 255, 255), 2)
        cv2.putText(frame, "cursor zone", (top_left[0], top_left[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        for hand in HAND_NAMES:
            state = self.hands[hand]
            color = HAND_COLORS[hand]
            tag = hand[0].upper()
            column_x = 10 if hand == "left" else width // 2 + 10

            if state.landmarks:
                self.draw_landmarks(frame, state.landmarks, color)

                wrist = state.landmarks[0]
                cv2.putText(frame, tag, (int(wrist.x * width) - 8, int(wrist.y * height) + 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

                if state.cursor_position:
                    cursor_x, cursor_y = state.cursor_position
                    cv2.circle(frame, (int(cursor_x * width), int(cursor_y * height)), 8, (255, 0, 255), 2)

            lines = [
                f"{tag} raw: {state.raw_gesture_name or 'none'}",
                f"{tag} pointer: {state.pointer_state or 'none'}",
                f"{tag} adjust: {state.adjustment_gesture or 'none'}",
            ]
            if state.pinch_distance is not None:
                lines.append(f"{tag} pinch: {state.pinch_distance:.3f}")

            for line_index, line in enumerate(lines):
                cv2.putText(frame, line, (column_x, 30 + line_index * 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        showing_fired = (self.last_fired_label
                         and time.time() - self.last_fired_time < FIRED_LABEL_DURATION_SECONDS)
        if showing_fired:
            cv2.putText(frame, f"FIRED: {self.last_fired_label}", (10, height - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

        cv2.imshow(PREVIEW_WINDOW_NAME, frame)
        return cv2.waitKey(1) & 0xFF != ord("q")

    def draw_landmarks(self, frame, landmarks, color):
        height, width = frame.shape[:2]
        points = [(int(landmark.x * width), int(landmark.y * height)) for landmark in landmarks]

        for start_index, end_index in HAND_CONNECTIONS:
            cv2.line(frame, points[start_index], points[end_index], color, 2)

        for point in points:
            cv2.circle(frame, point, 4, (0, 0, 255), -1)

        return frame

    def close(self):
        self.recognizer.close()

        if self.capture:
            self.capture.release()
            self.capture = None

        cv2.destroyAllWindows()