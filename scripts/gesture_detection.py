import os
import time
import urllib.request

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mpPython
from mediapipe.tasks.python import vision as mpVision

GESTURE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
GESTURE_MODEL_PATH = "assets/models/cv/gesture_recogniser.task"

STATIC_GESTURES = {"Open_Palm", "Closed_Fist", "Thumb_Up", "Thumb_Down", "Victory"}

SWIPE_HISTORY_SECONDS = 0.6
SWIPE_MIN_DISTANCE = 0.25
SWIPE_MAX_VERTICAL_RATIO = 0.5
SWIPE_COOLDOWN_SECONDS = 1.0

STATIC_CONFIRM_FRAMES = 3
STATIC_COOLDOWN_SECONDS = 1.0


def downloadGestureModel(logger=None):
    if os.path.exists(GESTURE_MODEL_PATH):
        return

    os.makedirs(os.path.dirname(GESTURE_MODEL_PATH), exist_ok=True)

    if logger:
        logger.info("Downloading MediaPipe gesture recognizer model...")

    urllib.request.urlretrieve(GESTURE_MODEL_URL, GESTURE_MODEL_PATH)


class SwipeTracker:

    def __init__(self):
        self.history = []

    def update(self, x, y, timestamp):
        self.history.append((timestamp, x, y))
        cutoff = timestamp - SWIPE_HISTORY_SECONDS
        self.history = [entry for entry in self.history if entry[0] >= cutoff]

    def detectSwipe(self):
        if len(self.history) < 2:
            return None

        startTime, startX, startY = self.history[0]
        endTime, endX, endY = self.history[-1]

        deltaX = endX - startX
        deltaY = endY - startY

        if abs(deltaX) < SWIPE_MIN_DISTANCE:
            return None

        if abs(deltaY) > abs(deltaX) * SWIPE_MAX_VERTICAL_RATIO:
            return None

        direction = "swipe_right" if deltaX > 0 else "swipe_left"
        self.history.clear()
        return direction

    def reset(self):
        self.history.clear()


class GestureDetector:

    def __init__(self, logger=None):
        self.logger = logger
        downloadGestureModel(logger)

        baseOptions = mpPython.BaseOptions(model_asset_path=GESTURE_MODEL_PATH)
        options = mpVision.GestureRecognizerOptions(
            base_options=baseOptions,
            running_mode=mpVision.RunningMode.VIDEO,
            num_hands=1,
        )
        self.recognizer = mpVision.GestureRecognizer.create_from_options(options)

        self.swipeTracker = SwipeTracker()
        self.pendingStaticGesture = None
        self.pendingStaticCount = 0
        self.lastStaticFireTime = 0.0
        self.lastSwipeFireTime = 0.0
        self.startTime = time.time()

        self.lastHandLandmarks = None
        self.lastRawGestureName = None

    def processFrame(self, frame):
        rgbFrame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mpImage = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgbFrame)
        timestampMs = int((time.time() - self.startTime) * 1000)

        result = self.recognizer.recognize_for_video(mpImage, timestampMs)
        now = time.time()

        self.lastHandLandmarks = result.hand_landmarks[0] if result.hand_landmarks else None
        self.lastRawGestureName = None
        if result.gestures and result.gestures[0]:
            self.lastRawGestureName = result.gestures[0][0].category_name

        if result.hand_landmarks:
            wrist = result.hand_landmarks[0][0]
            self.swipeTracker.update(wrist.x, wrist.y, now)
        else:
            self.swipeTracker.reset()

        swipe = self.swipeTracker.detectSwipe()
        if swipe and now - self.lastSwipeFireTime > SWIPE_COOLDOWN_SECONDS:
            self.lastSwipeFireTime = now
            self.pendingStaticGesture = None
            self.pendingStaticCount = 0
            return swipe

        if result.gestures and result.gestures[0]:
            topGesture = result.gestures[0][0]
            name = topGesture.category_name

            if name in STATIC_GESTURES:
                if name == self.pendingStaticGesture:
                    self.pendingStaticCount += 1
                else:
                    self.pendingStaticGesture = name
                    self.pendingStaticCount = 1

                confirmed = self.pendingStaticCount >= STATIC_CONFIRM_FRAMES
                cooledDown = now - self.lastStaticFireTime > STATIC_COOLDOWN_SECONDS

                if confirmed and cooledDown:
                    self.lastStaticFireTime = now
                    self.pendingStaticCount = 0
                    return name.lower()
            else:
                self.pendingStaticGesture = None
                self.pendingStaticCount = 0
        else:
            self.pendingStaticGesture = None
            self.pendingStaticCount = 0

        return None

    def close(self):
        self.recognizer.close()