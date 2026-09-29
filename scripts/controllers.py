from rapidfuzz import fuzz
import threading
import time
import cv2

from gesture_detection import GestureDetector
from wake_word import WakeWordListener
from listener import CommandListener
import gesture_commands
import commands


class WakeWordController:
    def __init__(self, logger, callback):
        self.logger = logger
        self.callback = callback
        self.listener = WakeWordListener(on_detected=self.handle_detected)
        self.thread: threading.Thread | None = None

    def start(self):
        if self.thread and self.thread.is_alive():
            if self.listener.running:
                return
            if self.thread is not threading.current_thread():
                self.thread.join(timeout=1.0)
        self.listener.running = True
        self.thread = threading.Thread(target=self.listener.listen, daemon=True)
        self.thread.start()

    def stop(self):
        self.listener.stop()

    def handle_detected(self, name: str, score: float):
        if self.logger:
            self.logger.info(f"Wake word '{name}' detected ({score:.2f})")
        self.callback(name, score)


class VoiceCommandController:
    def __init__(self, logger, function):
        self.logger = logger
        self.function = function
        self.listener = CommandListener()

    def start(self, *_args):
        threading.Thread(target=self.listen, daemon=True).start()

    def listen(self):
        text = self.listener.listen_for_command()
        if text:
            self.function(text.split())
        else:
            self.logger.info("Nothing heard...")



class CommandController:
    MATCH_THRESHOLD = 70

    SPECIAL_PHRASES = {
        "greetings": ["hello", "hi", "hi there", "hey", "hey there",
                     "good morning", "good afternoon", "good evening"],
        "farewell": ["bye", "goodbye", "see you", "see you later",
                     "talk to you later"],
        "thanks": ["thank you", "thanks", "cheers"],
        "identity": ["who are you", "what are you", "what's your name"],
        "capabilities": ["what can you do", "what can you help with",
                          "help me", "what commands do you know"],
        "how_are_you": ["how are you", "how's it going", "how are you doing"],
    }


    def __init__(self, logger):
        self.logger = logger
        self.commands = commands.COMMANDS
        self.phrase_to_intent = {
            phrase: intent
            for intent, phrases in self.SPECIAL_PHRASES.items()
            for phrase in phrases
        }


    def command_names(self):
        return list(self.commands.keys())


    def best_match(self, parts, candidates):
        best_key, best_score, words_consumed = None, 0, 0
        for key in candidates:
            word_count = len(key.split())
            if word_count > len(parts):
                continue
            candidate = " ".join(parts[:word_count])
            score = fuzz.WRatio(candidate, key)
            if score > best_score:
                best_key, best_score, words_consumed = key, score, word_count
        return best_key, best_score, words_consumed


    def execute(self, parts):
        if not parts:
            return -1

        phrase_key, phrase_score, _ = self.best_match(parts, self.phrase_to_intent)
        cmd_name, cmd_score, cmd_len = self.best_match(parts, self.commands)

        if phrase_key and phrase_score >= self.MATCH_THRESHOLD and phrase_score >= cmd_score:
            intent = self.phrase_to_intent[phrase_key]
            if self.logger:
                self.logger.info(f"Matched phrase '{phrase_key}' -> {intent} (score={phrase_score:.0f})")
            return intent

        if not cmd_name or cmd_score < self.MATCH_THRESHOLD:
            if self.logger:
                self.logger.info(f"No confident match for '{' '.join(parts)}'")
            return 0

        args = parts[cmd_len:]
        if self.logger:
            self.logger.info(f"Executing: {cmd_name} (score={cmd_score:.0f}) args={args}")
        self.commands[cmd_name](args)
        return 1



import threading
import time

import cv2

from gesture_detection import GestureDetector


class GestureController:
    """Runs webcam capture + gesture detection on a background thread and
    dispatches everything into a single GestureCommandController:
    - gesture_command_controller.handle_gesture(name): once per discrete
      gesture (static poses, swipes, click_left, click_right) after it's
      confirmed/debounced.
    - gesture_command_controller.handle_move(x, y): every frame the hand is
      in the "point" pointer state, with the index fingertip's normalized
      (0-1) position.

    Deliberately holds a reference to gesture_command_controller rather than
    a bare (logger, callback) pair — unlike the voice pipeline's controllers,
    which stay wiring-agnostic in main.py, this one is tied directly to its
    command controller by design.

    show_preview: when True, opens an OpenCV window showing the webcam feed
    with hand landmarks, the current pointer state, and the currently
    recognized gesture overlaid. Intended for development/tuning only — leave
    off for the real app, since it opens a visible window and blocks on
    cv2.waitKey each frame. Press 'q' in the preview window to stop the
    controller."""

    # Standard 21-point MediaPipe hand landmark topology. Stable across API
    # versions even though mediapipe.solutions.drawing_utils (which used to
    # draw this for you) was removed from the package.
    hand_connections = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (5, 9), (9, 10), (10, 11), (11, 12),
        (9, 13), (13, 14), (14, 15), (15, 16),
        (13, 17), (17, 18), (18, 19), (19, 20),
        (0, 17),
    ]

    fired_label_duration_seconds = 1.0

    def __init__(self, logger, gesture_command_controller, show_preview=False):
        self.logger = logger
        self.gesture_command_controller = gesture_command_controller
        self.show_preview = show_preview
        self.running = False
        self.thread = None
        self.detector = None
        self.capture = None
        self.last_fired_gesture = None
        self.last_fired_time = 0.0

    def start(self):
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

        if self.thread:
            self.thread.join(timeout=2)

        if self.capture:
            self.capture.release()
            self.capture = None

        if self.detector:
            self.detector.close()
            self.detector = None

        if self.show_preview:
            cv2.destroyAllWindows()

    def run(self):
        self.detector = GestureDetector(logger=self.logger)
        self.capture = cv2.VideoCapture(0)

        if not self.capture.isOpened():
            if self.logger:
                self.logger.error("GestureController could not open webcam")
            self.running = False
            return

        if self.logger:
            self.logger.info("GestureController started")

        while self.running:
            success, frame = self.capture.read()

            if not success:
                continue

            # Mirror so movement direction matches what the user sees of themselves.
            frame = cv2.flip(frame, 1)
            gesture = self.detector.process_frame(frame)

            if self.detector.last_pointer_state == "point" and self.detector.last_hand_landmarks:
                index_tip = self.detector.last_hand_landmarks[8]
                self.gesture_command_controller.handle_move(index_tip.x, index_tip.y)

            if gesture:
                if self.logger:
                    self.logger.info(f"Gesture recognized: {gesture}")
                self.last_fired_gesture = gesture
                self.last_fired_time = time.time()
                self.gesture_command_controller.handle_gesture(gesture)

            if self.show_preview:
                if not self.render_preview(frame):
                    self.running = False

        self.capture.release()
        self.capture = None
        self.detector.close()
        self.detector = None

        if self.show_preview:
            cv2.destroyAllWindows()

    def render_preview(self, frame):
        """Draws landmarks + gesture text onto frame and shows it in a window.
        Returns False if the user pressed 'q' to close the preview."""
        if self.detector.last_hand_landmarks:
            self.draw_landmarks(frame, self.detector.last_hand_landmarks)

        raw_gesture = self.detector.last_raw_gesture_name or "no hand / no gesture"
        cv2.putText(frame, f"raw: {raw_gesture}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        pointer_state = self.detector.last_pointer_state or "none"
        cv2.putText(frame, f"pointer state: {pointer_state}", (10, 130),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)

        if self.detector.last_pinch_distance is not None:
            cv2.putText(frame, f"pinch dist: {self.detector.last_pinch_distance:.3f}", (10, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        showing_fired = (self.last_fired_gesture
                         and time.time() - self.last_fired_time < self.fired_label_duration_seconds)
        if showing_fired:
            cv2.putText(frame, f"FIRED: {self.last_fired_gesture}", (10, 65),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

        cv2.imshow("HandPilot Gesture Preview", frame)
        return cv2.waitKey(1) & 0xFF != ord("q")

    def draw_landmarks(self, frame, landmarks):
        height, width = frame.shape[:2]
        points = [(int(landmark.x * width), int(landmark.y * height)) for landmark in landmarks]

        for start_index, end_index in self.hand_connections:
            cv2.line(frame, points[start_index], points[end_index], (0, 255, 0), 2)

        for point in points:
            cv2.circle(frame, point, 4, (0, 0, 255), -1)

        return frame



class GestureCommandController:
    """Owns the active control mode (standard/gaming) and dispatches events
    from GestureController into gesture_commands.py action functions. Mirrors
    CommandController's role on the voice side, but does exact-name lookup
    instead of fuzzy matching, since gesture names carry no free-text args."""

    MODES = {
        "standard": gesture_commands.STANDARD_GESTURE_COMMANDS,
        "gaming": gesture_commands.GAMING_GESTURE_COMMANDS,
    }

    def __init__(self, logger):
        self.logger = logger
        self.mode = "standard"

    def set_mode(self, mode):
        if mode not in self.MODES:
            if self.logger:
                self.logger.error(f"Unknown gesture mode: {mode}")
            return

        self.mode = mode
        gesture_commands.reset_mouse_smoothing()

        if self.logger:
            self.logger.info(f"Gesture control mode set to: {mode}")

    def handle_gesture(self, gesture_name):
        commands = self.MODES[self.mode]
        action = commands.get(gesture_name)

        if not action:
            if self.logger:
                self.logger.info(f"No action bound to gesture '{gesture_name}' in mode '{self.mode}'")
            return

        if self.logger:
            self.logger.info(f"Executing gesture action: {gesture_name} (mode={self.mode})")
        action()

    def handle_move(self, x, y):
        if self.mode != "standard":
            return
        gesture_commands.move_mouse(x, y)
