from rapidfuzz import fuzz
import threading
import time
import cv2

from gesture_detection import GestureDetector
from wake_word import WakeWordListener
from listener import CommandListener
import commands


class WakeWordController:
    def __init__(self, logger, callback):
        self.logger = logger
        self.callback = callback
        self.listener = WakeWordListener(on_detected=self.handle_detected)
        self.thread: threading.Thread | None = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.listener._running = True
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
    handConnections = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (5, 9), (9, 10), (10, 11), (11, 12),
        (9, 13), (13, 14), (14, 15), (15, 16),
        (13, 17), (17, 18), (18, 19), (19, 20),
        (0, 17),
    ]
 
    firedLabelDurationSeconds = 1.0
 
    def __init__(self, logger, callback, showPreview=False):
        self.logger = logger
        self.callback = callback
        self.showPreview = showPreview
        self.running = False
        self.thread = None
        self.detector = None
        self.capture = None
        self.lastFiredGesture = None
        self.lastFiredTime = 0.0
 
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
 
        if self.showPreview:
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

            frame = cv2.flip(frame, 1)
            gesture = self.detector.processFrame(frame)
 
            if gesture:
                if self.logger:
                    self.logger.info(f"Gesture recognized: {gesture}")
                self.lastFiredGesture = gesture
                self.lastFiredTime = time.time()
                self.callback(gesture)
 
            if self.showPreview:
                if not self.renderPreview(frame):
                    self.running = False
 
        self.capture.release()
        self.capture = None
        self.detector.close()
        self.detector = None
 
        if self.showPreview:
            cv2.destroyAllWindows()
 
    def renderPreview(self, frame):
        if self.detector.lastHandLandmarks:
            self.drawLandmarks(frame, self.detector.lastHandLandmarks)
 
        rawGesture = self.detector.lastRawGestureName or "no hand / no gesture"
        cv2.putText(frame, f"raw: {rawGesture}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
 
        showingFired = (self.lastFiredGesture
                        and time.time() - self.lastFiredTime < self.firedLabelDurationSeconds)
        if showingFired:
            cv2.putText(frame, f"FIRED: {self.lastFiredGesture}", (10, 65),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
 
        cv2.imshow("HandPilot Gesture Preview", frame)
        return cv2.waitKey(1) & 0xFF != ord("q")
 
    def drawLandmarks(self, frame, landmarks):
        height, width = frame.shape[:2]
        points = [(int(landmark.x * width), int(landmark.y * height)) for landmark in landmarks]
 
        for startIndex, endIndex in self.handConnections:
            cv2.line(frame, points[startIndex], points[endIndex], (0, 255, 0), 2)
 
        for point in points:
            cv2.circle(frame, point, 4, (0, 0, 255), -1)
 
        return frame