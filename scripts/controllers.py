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
    def __init__(self, logger):
        self.logger = logger
        self.commands = commands.COMMANDS

    def command_names(self):
        return list(self.commands.keys())

    def execute(self, parts):
        if not parts:
            return
        best_name, best_score, arg_start = None, 0, 0
        for name in self.commands:
            word_count = len(name.split())
            if word_count > len(parts):
                continue
            candidate = " ".join(parts[:word_count])
            score = fuzz.WRatio(candidate, name)
            if score > best_score:
                best_name, best_score, arg_start = name, score, word_count

        if not best_name or best_score < 70:
            if self.logger:
                self.logger.info(f"No confident match for '{' '.join(parts)}'")
            return

        args = parts[arg_start:]
        if self.logger:
            self.logger.info(f"Executing: {best_name} (score={best_score:.0f}) args={args}")
        self.commands[best_name](args)