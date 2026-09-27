from unified_ui.logger import Logger
from unified_ui.audio import AudioController
from time import sleep

import utils
from controllers import WakeWordController, VoiceCommandController, CommandController, GestureController



logger = Logger()
audio_controller = None



def on_wake_word_detected(name, score):
    wake_controller.stop()
    audio_controller.play("waiting")
    voice_controller.start()

def voice_command(parts):
    if parts == -1:
        audio_controller.play("wrong")
        wake_controller.start()
    else:
        execution = commands_controller.execute(parts)
        if execution == 1:
            audio_controller.play("ok")
            sleep(1)
            audio_controller.play(utils.choose_sound("done"))
        elif execution == 0:
            audio_controller.play("wrong")
            sleep(1)
            audio_controller.play(utils.choose_sound("unknown"))
        elif execution == -1:
            audio_controller.play("wrong")
        else:
            audio_controller.play(utils.choose_sound(execution))
        wake_controller.start()

def gesture_processor(gesture):
    pass



wake_controller = WakeWordController(logger, on_wake_word_detected)
voice_controller = VoiceCommandController(logger, voice_command)
commands_controller = CommandController(logger)
gestures_controller = GestureController(logger, gesture_processor, True)



async def start(app):
    global audio_controller
    audio_controller = AudioController(app.page)
    audio_controller.set_volume(0.5)
    audio_controller.add_sound("ok", "misc/ok.mp3")
    audio_controller.add_sound("wrong", "misc/wrong.mp3")
    audio_controller.add_sound("waiting", "misc/waiting.mp3")

    audio_controller.add_sound("done", "english/done.mp3")
    audio_controller.add_sound("sure", "english/sure.mp3")
    audio_controller.add_sound("greeting_1", "english/greeting_1.mp3")
    audio_controller.add_sound("unrecognised", "english/unrecognised_command.mp3")
    audio_controller.add_sound("not_understand", "english/not_understand.mp3")


def toggle_voice_helper(state):
    if state:
        wake_controller.start()
    else:
        wake_controller.stop()

def toggle_gestures_controls(state):
    if state:
        gestures_controller.start()
    else:
        gestures_controller.stop()
    