from unified_ui.logger import Logger
from unified_ui.audio import AudioController
from time import sleep

import utils
from controllers import WakeWordController, VoiceCommandController, CommandController, GestureController, GestureCommandController



logger = Logger()
audio_controller = None
voice_toggle = None
gesture_toggle = None



def on_wake_word_detected(name, score):
    wake_controller.stop()
    audio_controller.play("waiting")
    voice_controller.start()

def voice_command(parts):
    if parts == -1:
        audio_controller.play("wrong")
        wake_controller.start()
    else:
        execution, answer = commands_controller.execute(parts)
        if execution == 1:
            audio_controller.play("ok")
            sleep(1)
            audio_controller.play(utils.choose_sound("done"))
            voice_controller.start()
        elif execution == 0:
            audio_controller.play("wrong")
            sleep(1)
            audio_controller.play(utils.choose_sound("unknown"))
        elif execution == -1:
            audio_controller.play("wrong")
        elif execution == -2: #disable voice
            pass
        elif execution == 2: #enable gestures
            pass
        else:
            audio_controller.play(utils.choose_sound(answer))
        wake_controller.start()

def gesture_processor(gesture):
    pass



wake_controller = WakeWordController(logger, on_wake_word_detected)
voice_controller = VoiceCommandController(logger, voice_command)
commands_controller = CommandController(logger)
gesture_command_controller = GestureCommandController(logger)
gesture_controller = GestureController(logger, gesture_command_controller, show_preview=True)



async def start(app):
    global audio_controller
    audio_controller = AudioController(app.page)
    audio_controller.set_volume(0.5)
    audio_controller.add_sound("ok", "misc/ok.mp3")
    audio_controller.add_sound("wrong", "misc/wrong.mp3")
    audio_controller.add_sound("waiting", "misc/waiting.mp3")

    audio_controller.add_sound("hey_help", "english/hey_help.mp3")
    audio_controller.add_sound("greetings", "english/greetings.mp3")
    audio_controller.add_sound("nice_to_meet", "english/nice_to_meet.mp3")

    audio_controller.add_sound("see_you", "english/see_you.mp3")
    audio_controller.add_sound("goodbye", "english/goodbye.mp3")
    audio_controller.add_sound("bye_now", "english/bye_now.mp3")

    audio_controller.add_sound("helper", "english/helper.mp3")
    audio_controller.add_sound("assistant", "english/assistant.mp3")
    audio_controller.add_sound("handy", "english/handy.mp3")

    audio_controller.add_sound("youre_welcome", "english/youre_welcome.mp3")
    audio_controller.add_sound("no_problem", "english/no_problem.mp3")
    audio_controller.add_sound("thats_my_job", "english/thats_my_job.mp3")

    audio_controller.add_sound("you_may_ask", "english/you_may_ask.mp3")
    audio_controller.add_sound("i_can_help", "english/i_can_help.mp3")

    audio_controller.add_sound("awesome", "english/awesome.mp3")
    audio_controller.add_sound("fine", "english/fine.mp3")
    audio_controller.add_sound("best", "english/best.mp3")
    
    audio_controller.add_sound("done", "english/done.mp3")
    audio_controller.add_sound("sure", "english/sure.mp3")
    audio_controller.add_sound("your_wish", "english/your_wish.mp3")

    audio_controller.add_sound("unrecognised", "english/unrecognised_command.mp3")
    audio_controller.add_sound("not_understand", "english/not_understand.mp3")

    audio_controller.add_sound("gestures_on", "english/gesture_control_on.mp3")



def toggle_voice_helper(state):
    if state:
        wake_controller.start()
    else:
        wake_controller.stop()

def toggle_gestures_controls(state):
    if state:
        gesture_controller.start()
    else:
        gesture_controller.stop()
    