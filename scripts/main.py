from unified_ui.logger import Logger
from unified_ui.audio import AudioController
from controllers import WakeWordController, VoiceCommandController, CommandController



logger = Logger()
audio_controller = None



def on_wake_word_detected(name, score):
    wake_controller.stop()
    audio_controller.play("waiting")
    voice_controller.start()

def voice_command(parts):
    commands_controller.execute(parts)
    voice_controller.stop()
    wake_controller.start()

wake_controller = WakeWordController(logger, on_wake_word_detected)
voice_controller = VoiceCommandController(logger, voice_command)
commands_controller = CommandController(logger)



async def start(app):
    global audio_controller
    audio_controller = AudioController(app.page)
    audio_controller.set_volume(0.5)
    audio_controller.add_sound("ok", "misc/ok.mp3")
    audio_controller.add_sound("wrong", "misc/wrong.mp3")
    audio_controller.add_sound("waiting", "misc/waiting.mp3")


def toggle_voice_helper(state):
    if state:
        wake_controller.start()
    else:
        wake_controller.stop()