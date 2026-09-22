import json
import sounddevice as sd
from vosk import KaldiRecognizer, Model



SAMPLE_RATE = 16000
VOSK_MODEL_PATH = "assets/models/vosk/vosk-model-small-en-us-0.15"
COMMAND_RECORD_SECONDS = 4.0



class CommandListener:
    def __init__(self, model_path=VOSK_MODEL_PATH):
        self.model = Model(model_path)
        self.recognizer = KaldiRecognizer(self.model, SAMPLE_RATE)

    def record_clip(self, seconds=COMMAND_RECORD_SECONDS):
        audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
        sd.wait()
        return audio.flatten()

    def transcribe(self, audio):
        self.recognizer.Reset()
        self.recognizer.AcceptWaveform(audio.tobytes())
        result = json.loads(self.recognizer.FinalResult())
        return result.get("text", "").strip()

    def listen_for_command(self):
        audio = self.record_clip()
        return self.transcribe(audio)