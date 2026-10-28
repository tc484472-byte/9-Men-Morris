import queue
import threading


class SpeechOutput:
    """
    Text-to-speech on a background thread. pyttsx3's runAndWait() blocks, so
    calling it from the game loop used to freeze the window on every AI move.
    The engine is created inside the worker thread (required on Windows).
    """

    def __init__(self):
        self.available = False
        self._queue = queue.Queue()
        try:
            import pyttsx3  # noqa: F401
            self.available = True
        except Exception:
            return
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 165)
        except Exception:
            self.available = False
            return
        while True:
            text = self._queue.get()
            # Skip stale lines if several are queued.
            while not self._queue.empty():
                text = self._queue.get_nowait()
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception:
                pass

    def speak(self, text):
        if self.available:
            self._queue.put(text)
