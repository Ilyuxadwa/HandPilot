from unified_ui.logger import Logger
from controllers import WakeWordController, VoiceCommandController, CommandController



logger = Logger()



def on_wake_word_detected(name, score):
    global voice_controller
    voice_controller.start()

def voice_command(parts):
    global commands_controller
    commands_controller.execute(parts)



wake_controller = WakeWordController(logger, on_wake_word_detected)
voice_controller = VoiceCommandController(logger, voice_command)
commands_controller = CommandController(logger)



async def start(app):
    wake_controller.start()


def toggle_voice_helper(state):
    #if state:
        #wake_controller.start()
    #else:
        #wake_controller.stop()
    
    pass
