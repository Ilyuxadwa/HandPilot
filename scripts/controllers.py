from rapidfuzz import fuzz
import threading
import time
import cv2

from gesture_detection import GestureDetector
from wake_word import WakeWordListener
from game_profiler import GameProfiler
from listener import CommandListener
from game_parser import parse_hpgame
from pathlib import Path
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



class GestureController:
    """Runs webcam capture + gesture detection on a background thread and
    dispatches everything into a single GestureCommandController. Has no
    OpenCV dependency at all — camera capture and frame reading live in
    GestureDetector (open_camera/read_frame), and all preview rendering
    lives in GestureDetector.render_preview. This controller only starts/
    stops the loop and sends whatever GestureDetector reports:
    - gesture_command_controller.handle_gesture(name): once per discrete
      gesture (static poses, swipes, click_left, click_right,
      open_palm_increase/decrease, closed_fist_increase/decrease) after it's
      confirmed/debounced.
    - gesture_command_controller.handle_move(x, y): every frame the hand is
      in the "point" pointer state, with the tracked cursor position.
 
    Deliberately holds a reference to gesture_command_controller rather than
    a bare (logger, callback) pair — unlike the voice pipeline's controllers,
    which stay wiring-agnostic in main.py, this one is tied directly to its
    command controller by design.
 
    show_preview: when True, shows an OpenCV window (via
    GestureDetector.render_preview) with hand landmarks and detection state
    overlaid. Intended for development/tuning only. Press 'q' in the preview
    window to stop the controller."""
 
    def __init__(self, logger, gesture_command_controller, show_preview=False):
        self.logger = logger
        self.gesture_command_controller = gesture_command_controller
        self.show_preview = show_preview
        self.running = False
        self.thread = None
        self.detector = None
 
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
 
        if self.detector:
            self.detector.close()
            self.detector = None
 
    def run(self):
        self.detector = GestureDetector(logger=self.logger)
 
        if not self.detector.open_camera():
            if self.logger:
                self.logger.error("GestureController could not open webcam")
            self.running = False
            return
 
        if self.logger:
            self.logger.info("GestureController started")
 
        while self.running:
            frame = self.detector.read_frame()
 
            if frame is None:
                continue
 
            gesture = self.detector.process_frame(frame)
 
            if self.detector.last_cursor_position:
                cursor_x, cursor_y = self.detector.last_cursor_position
                self.gesture_command_controller.handle_move(cursor_x, cursor_y)
 
            if gesture:
                if self.logger:
                    self.logger.info(f"Gesture recognized: {gesture}")
                self.gesture_command_controller.handle_gesture(gesture)
 
            if self.show_preview:
                active_region = self.gesture_command_controller.get_active_region()
                if not self.detector.render_preview(frame, active_region):
                    self.running = False
 
        self.detector.close()
        self.detector = None



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
 
    def get_active_region(self):
        """Returns (x_min, x_max, y_min, y_max) of the camera-frame rectangle
        that gesture_commands.move_mouse maps onto the full screen — used by
        GestureController to draw it in the preview window."""
        return (
            gesture_commands.ACTIVE_REGION_X_MIN,
            gesture_commands.ACTIVE_REGION_X_MAX,
            gesture_commands.ACTIVE_REGION_Y_MIN,
            gesture_commands.ACTIVE_REGION_Y_MAX,
        )



class GameProfilerController:
    def __init__(self):
        self.profilers = []

    def add(self, profiler):
        if profiler not in self.profilers:
            profiler.start()
            self.profilers.append(profiler)

    def remove(self, profiler):
        if profiler in self.profilers:
            profiler.stop()
            self.profilers.remove(profiler)

    def action(self, name, argument=None, duration=None):
        for profiler in self.profilers:
            profiler.action(name, argument, duration)

    def release(self, name, argument=None):
        for profiler in self.profilers:
            profiler.release(name, argument)

    def release_all(self):
        for profiler in self.profilers:
            profiler.release_all()