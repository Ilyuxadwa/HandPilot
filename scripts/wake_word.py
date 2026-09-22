import queue
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
from openwakeword.model import Model

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280
DETECTION_THRESHOLD = 0.5
COOLDOWN_SECONDS = 1.5

WAKEWORD_MODEL_PATHS = ["assets/models/wakeword/handy.onnx"]


class WakeWordListener:

    def __init__(
        self,
        on_detected: Callable[[str, float], None],
        model_paths: Optional[list[str]] = WAKEWORD_MODEL_PATHS,
        threshold: float = DETECTION_THRESHOLD,
        cooldown: float = COOLDOWN_SECONDS,
    ):
        self.on_detected = on_detected
        self.threshold = threshold
        self.cooldown = cooldown
        self.last_trigger_time = 0.0

        try:
            self.model = Model(wakeword_models=model_paths or [], inference_framework="onnx")
        except TypeError:
            try:
                self.model = Model(wakeword_model_paths=model_paths or [], inference_framework="onnx")
            except TypeError:
                self.model = Model(wakeword_model_paths=model_paths or [])

        self.audio_q: "queue.Queue[np.ndarray]" = queue.Queue()
        self.running = False

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"Mic status: {status}")
        pcm16 = (indata[:, 0] * 32767).astype(np.int16)
        self.audio_q.put(pcm16)


    def listen(self):
        self.running = True
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=FRAME_SAMPLES,
            callback=self._audio_callback,
        ):
            while self.running:
                chunk = self.audio_q.get()
                predictions = self.model.predict(chunk)

                now = time.time()
                if now - self.last_trigger_time < self.cooldown:
                    continue

                for name, score in predictions.items():
                    if score >= self.threshold:
                        self.last_trigger_time = now
                        self.on_detected(name, score)
                        break

    def stop(self):
        self.running = False