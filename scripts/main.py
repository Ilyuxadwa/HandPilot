from unified_ui.logger import Logger
from unified_ui.audio import AudioController
from controllers import WakeWordController, VoiceCommandController, CommandController



logger = Logger()
audio_controller = None



def on_wake_word_detected(name, score):
    global voice_controller
    audio_controller.play("assets/sounds/misc/waiting.mp3")
    voice_controller.start()

def voice_command(parts):
    global commands_controller
    commands_controller.execute(parts)



wake_controller = WakeWordController(logger, on_wake_word_detected)
voice_controller = VoiceCommandController(logger, voice_command)
commands_controller = CommandController(logger)



async def start(app):
    global audio_controller
    audio_controller = AudioController(app.page)


def toggle_voice_helper(state):
    if state:
        wake_controller.start()
    else:
        wake_controller.stop()