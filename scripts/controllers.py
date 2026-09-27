import threading

from wake_word import WakeWordListener
from listener import CommandListener
from rapidfuzz import fuzz, process
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