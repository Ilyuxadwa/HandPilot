from rapidfuzz import fuzz
import threading
import time
import cv2
import re

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

    CONTROL_PHRASES = {
        2: ["enable gestures", "turn on gestures", "start gestures", "gestures on"],
        -2: ["disable gestures", "turn off gestures", "stop gestures", "gestures off"],
        -3: ["disable voice", "turn off voice", "stop listening", "voice off",
             "disable voice control"],
    }

    def __init__(self, logger, game_controller=None):
        self.logger = logger
        self.commands = commands.COMMANDS
        self.game_controller = game_controller
        self.phrase_to_intent = {
            phrase: intent
            for intent, phrases in self.SPECIAL_PHRASES.items()
            for phrase in phrases
        }
        self.phrase_to_control = {
            phrase: code
            for code, phrases in self.CONTROL_PHRASES.items()
            for phrase in phrases
        }

    def command_names(self):
        return list(self.commands.keys())

    def game_action_names(self):
        names = set()
        if self.game_controller:
            for profiler in self.game_controller.profilers:
                for key in profiler.profile.bindings:
                    names.add(key.split(".", 1)[0])
        return names

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

    def parse_duration(self, parts):
        if not parts:
            return None
        joined = " ".join(parts)
        match = re.match(r"^(\d+)\s*(s|sec|secs|second|seconds)?$", joined)
        if match:
            return f"{match.group(1)}s"
        number = commands.parse_number(parts)
        if number is not None:
            return f"{number}s"
        return joined

    def execute(self, parts):
        if not parts:
            return -1

        control_key, control_score, _ = self.best_match(parts, self.phrase_to_control)
        phrase_key, phrase_score, _ = self.best_match(parts, self.phrase_to_intent)
        cmd_name, cmd_score, cmd_len = self.best_match(parts, self.commands)
        action_name, action_score, action_len = self.best_match(parts, self.game_action_names())

        if (control_score >= self.MATCH_THRESHOLD and control_score >= phrase_score
                and control_score >= action_score and control_score >= cmd_score):
            return self.phrase_to_control[control_key]

        if phrase_score >= self.MATCH_THRESHOLD and phrase_score >= cmd_score and phrase_score >= action_score:
            intent = self.phrase_to_intent[phrase_key]
            if self.logger:
                self.logger.info(f"Matched phrase '{phrase_key}' -> {intent} (score={phrase_score:.0f})")
            return intent

        if action_name and action_score >= self.MATCH_THRESHOLD and action_score >= cmd_score:
            remainder = parts[action_len:]
            argument = remainder[0] if remainder else None
            duration = self.parse_duration(remainder[1:]) if len(remainder) > 1 else None
            if self.logger:
                self.logger.info(f"Game action: {action_name} argument={argument} duration={duration} (score={action_score:.0f})")
            self.game_controller.action(action_name, argument, duration)
            return 1

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
    def __init__(self, logger, gesture_command_controller, game_callback=None, show_preview=False):
        self.logger = logger
        self.gesture_command_controller = gesture_command_controller
        self.game_callback = game_callback
        self.show_preview = show_preview
        self.game_mode = False
        self.running = False
        self.thread = None
        self.detector = None

    def set_game_mode(self, enabled):
        self.game_mode = enabled
        self.gesture_command_controller.set_mode("gaming" if enabled else "standard")

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

            events = self.detector.process_frame(frame)

            if not self.game_mode and self.detector.cursor_positions:
                self.gesture_command_controller.handle_move(self.detector.cursor_positions)

            for hand, gesture in events:
                if self.logger:
                    self.logger.info(f"Gesture recognized: {hand} {gesture}")
                if self.game_mode:
                    self.game_callback(hand, gesture)
                else:
                    self.gesture_command_controller.handle_gesture(hand, gesture)

            if self.show_preview:
                active_region = self.gesture_command_controller.get_active_region()
                if not self.detector.render_preview(frame, active_region):
                    self.running = False

        self.detector.close()
        self.detector = None




class GestureCommandController:
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
 
    def handle_gesture(self, hand, gesture_name):
        commands = self.MODES[self.mode]
        action = commands.get(f"{hand}_{gesture_name}") or commands.get(gesture_name)
 
        if not action:
            if self.logger:
                self.logger.info(f"No action bound to gesture '{hand}_{gesture_name}' in mode '{self.mode}'")
            return
 
        if self.logger:
            self.logger.info(f"Executing gesture action: {hand}_{gesture_name} (mode={self.mode})")
        action()
 
    def handle_move(self, positions):
        if self.mode != "standard":
            return
 
        for hand in gesture_commands.CURSOR_HAND_PRIORITY:
            if hand in positions:
                x, y = positions[hand]
                gesture_commands.move_mouse(x, y)
                return
 
    def get_active_region(self):
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

    def gesture(self, hand, gesture):
        names = (f"{hand}_{gesture}", gesture)
        for profiler in list(self.profilers):
            for key, assigned in profiler.get_keys().items():
                if assigned.lower() in names:
                    name, _, argument = key.partition(".")
                    profiler.action(name, argument or None)