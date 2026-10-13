from unified_ui.logger import Logger
from unified_ui.audio import AudioController
from time import sleep

import utils
from game_profiler import GameProfiler
from controllers import WakeWordController, VoiceCommandController, CommandController, GestureController, GestureCommandController, GameProfilerController



logger = Logger()
audio_controller = None
voice_toggle = None
gesture_toggle = None

profilers: dict[str, GameProfiler] = {}



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
        elif execution == -2: 
            disable_gestures_controls()
        elif execution == 2:
            enable_gestures_controls()
        elif execution == -3:
            disable_voice_helper()
        else:
            audio_controller.play(utils.choose_sound(execution))
        wake_controller.start()



wake_controller = WakeWordController(logger, on_wake_word_detected)
voice_controller = VoiceCommandController(logger, voice_command)
profiler_controller = GameProfilerController()
commands_controller = CommandController(logger, profiler_controller)
gesture_command_controller = GestureCommandController(logger)
gesture_controller = GestureController(logger, gesture_command_controller, show_preview=True)



async def start(app):
    global audio_controller
    global profilers
    profilers = utils.get_games()
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
    audio_controller.add_sound("gestures_off", "english/gesture_control_off.mp3")

    audio_controller.on_ready(lambda: app.navigate("main_page"))

def disable_voice_helper():
    global voice_toggle
    if voice_toggle.value:
        wake_controller.stop()
        voice_toggle.value = False
        voice_toggle.update()
        audio_controller.play(utils.choose_sound("farewell"))

def enable_gestures_controls():
    global gesture_toggle
    if not gesture_toggle.value:
        gesture_controller.start()
        gesture_toggle.value = True
        gesture_toggle.update()
        audio_controller.play("gestures_on")

def disable_gestures_controls():
    global gesture_toggle
    if gesture_toggle.value:
        gesture_controller.stop()
        gesture_toggle.value = False
        gesture_toggle.update()
        audio_controller.play("gestures_off")

def toggle_voice_helper(state):
    if state:
        wake_controller.start()
        audio_controller.play(utils.choose_sound("greetings"))
    else:
        wake_controller.stop()
        audio_controller.play(utils.choose_sound("farewell"))

def toggle_gestures_controls(state):
    if state:
        gesture_controller.start()
        audio_controller.play("gestures_on")
    else:
        gesture_controller.stop()
        audio_controller.play("gestures_off")

def toggle_game_profiler(name, enabled):
    profiler = profilers[name]
    if enabled:
        profiler_controller.add(profiler)
    else:
        profiler_controller.remove(profiler)
    