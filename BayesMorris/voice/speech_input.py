import array
import math
import threading
import time
from collections import deque


class SpeechInput:
    """
    Push-to-talk speech recognition that NEVER blocks the game window.

    Two microphone back-ends are supported:
      1. PyAudio       (speech_recognition.Microphone)   - the classic way
      2. sounddevice   (pip install sounddevice)         - fallback that needs
         no compiler / PyAudio wheel, so it works on new Python versions and
         on Windows where PyAudio often fails to install.

    start_listening() launches a background thread; the main loop polls
    poll() each frame. Status text and the real error (no backend, no
    microphone, no internet ...) are exposed so the GUI can show them.
    """

    RATE = 16000
    BLOCK = 1024
    LANGUAGE = "en-IN"           # Google recognizer; "en-US" also works
    # Input device for the sounddevice back-end: None = Windows default, or an
    # index / name.  Run  python voice_check.py  to see every device's level.
    # Can also be set with the environment variable BAYESMORRIS_MIC.
    DEVICE = None

    def __init__(self):
        self.available = False
        self.error = None            # short, user-facing reason
        self.details = []            # full technical reasons (printed to console)
        self.backend = None          # "pyaudio" | "sounddevice"
        self.rate = self.RATE        # sample rate used by the sounddevice backend
        self.peak = 0.0              # loudest level heard during the last listen
        self.level = 0.0             # live level (RMS) for the on-screen meter
        self.device_name = ""
        self.device = self._pick_device()
        self._pinned = self.device is not None
        self._candidates = [None]
        self._cand_pos = 0
        self._silent_tries = 0
        self.recognizer = None
        self.microphone = None
        self.sd = None
        self.sr = None
        self.listening = False
        self.status = ""
        self._result = None          # (kind, payload) set by worker thread
        self._lock = threading.Lock()
        self._calibrated = False
        self._noise = None

        try:
            import speech_recognition as sr
        except Exception as exc:
            self.error = "SpeechRecognition missing: pip install SpeechRecognition"
            self.details.append(f"speech_recognition: {type(exc).__name__}: {exc}")
            self._report()
            return
        self.sr = sr
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.6

        # --- back-end 1: PyAudio
        try:
            self.microphone = sr.Microphone()
            self.backend = "pyaudio"
        except Exception as exc:  # AttributeError (no PyAudio), OSError (no mic)
            self.details.append(f"PyAudio: {type(exc).__name__}: {exc}")

        # --- back-end 2: sounddevice
        if self.backend is None:
            try:
                import sounddevice as sd
                try:
                    sd.check_input_settings(device=self.device, channels=1, samplerate=self.RATE, dtype="int16")
                except Exception:
                    # Some Windows/macOS devices refuse 16 kHz: use the
                    # device's own rate (recognizer accepts any rate).
                    rate = int(sd.query_devices(self.device, kind="input")["default_samplerate"])
                    sd.check_input_settings(device=self.device, channels=1, samplerate=rate, dtype="int16")
                    self.rate = rate
                self.sd = sd
                self.backend = "sounddevice"
                try:
                    self.device_name = sd.query_devices(self.device, kind="input")["name"]
                except Exception:
                    self.device_name = str(self.device)
                # Unless the user pinned a device, remember the other input
                # devices so a silent one can be skipped automatically.
                self._pinned = self.device is not None
                self._candidates = self._build_candidates(sd)
                self._cand_pos = 0
                self._silent_tries = 0
            except Exception as exc:
                self.details.append(f"sounddevice: {type(exc).__name__}: {exc}")

        if self.backend:
            self.available = True
        else:
            self.error = "No microphone backend: pip install sounddevice"
            self._report()

    @staticmethod
    def _build_candidates(sd):
        """[system default] + every other real input device of the default
        host API (Windows lists each device once per API: MME, WASAPI ...)."""
        cands = [None]
        try:
            host = sd.default.hostapi
            default_index = sd.query_devices(None, kind="input").get("index")
            for i, d in enumerate(sd.query_devices()):
                name = d["name"].lower()
                if (d["max_input_channels"] < 1 or d["hostapi"] != host
                        or i == default_index or "mapper" in name
                        or "stereo mix" in name or "primary" in name):
                    continue
                cands.append(i)
        except Exception:
            pass
        return cands

    def _use_device(self, dev):
        sd = self.sd
        try:
            rate = self.RATE
            try:
                sd.check_input_settings(device=dev, channels=1, samplerate=rate, dtype="int16")
            except Exception:
                rate = int(sd.query_devices(dev, kind="input")["default_samplerate"])
                sd.check_input_settings(device=dev, channels=1, samplerate=rate, dtype="int16")
            self.device, self.rate = dev, rate
            self.device_name = sd.query_devices(dev, kind="input")["name"]
            return True
        except Exception:
            return False

    def _switch_to_next_device(self):
        n = len(self._candidates)
        for _ in range(n - 1):
            self._cand_pos = (self._cand_pos + 1) % n
            if self._use_device(self._candidates[self._cand_pos]):
                return True
        return False

    def _pick_device(self):
        import os
        choice = os.environ.get("BAYESMORRIS_MIC", self.DEVICE)
        if isinstance(choice, str) and choice.strip().isdigit():
            choice = int(choice)
        return choice if choice not in ("", None) else None

    def _report(self):
        print("[voice] unavailable -", self.error)
        for line in self.details:
            print("[voice]   ", line)

    # ----------------------------------------------------------------- API
    def start_listening(self, timeout=6, phrase_time_limit=5):
        if not self.available or self.listening:
            return False
        self.listening = True
        self.status = "Listening... speak now"
        threading.Thread(
            target=self._worker, args=(timeout, phrase_time_limit), daemon=True
        ).start()
        return True

    def poll(self):
        """Return (kind, payload) once when a result is ready, else None."""
        with self._lock:
            result, self._result = self._result, None
        return result

    # -------------------------------------------------------------- worker
    def _worker(self, timeout, phrase_time_limit):
        sr = self.sr
        result = ("error", "Unknown voice error")
        try:
            if self.backend == "pyaudio":
                audio = self._listen_pyaudio(timeout, phrase_time_limit)
            else:
                audio = self._listen_sounddevice(timeout, phrase_time_limit)
            self.status = "Recognizing..."
            text = self.recognizer.recognize_google(audio, language=self.LANGUAGE)
            result = ("text", text)
        except sr.WaitTimeoutError:
            if self.backend == "sounddevice" and self.peak < 3:
                old = self.device_name
                self._silent_tries += 1
                if self._pinned or len(self._candidates) < 2:
                    msg = ("Only silence from '%s'. Check Windows Sound > Input, "
                           "or run: python voice_check.py" % old[:30])
                elif self._silent_tries >= len(self._candidates):
                    self._silent_tries = 0
                    msg = ("No microphone gave any sound. Check mute / Windows "
                           "Sound > Input, then press V.")
                elif self._switch_to_next_device():
                    msg = ("Silent mic '%s'. Now trying '%s'. Press V again."
                           % (old[:22], self.device_name[:22]))
                else:
                    msg = "Only silence from '%s'." % old[:30]
            elif self.backend == "sounddevice":
                self._silent_tries = 0
                msg = ("Mic '%s' too quiet (level %.0f). Speak louder or raise mic "
                       "volume in Windows Sound settings." % (self.device_name[:30], self.peak))
            else:
                msg = "No speech heard. Check mic volume, press V again."
            result = ("none", msg)
        except sr.UnknownValueError:
            result = ("none", "Could not understand. Press V and try again.")
        except sr.RequestError as exc:
            result = ("error", f"Speech service unreachable (needs internet): {exc}")
        except Exception as exc:
            result = ("error", f"Microphone error: {type(exc).__name__}: {exc}")
        if result[0] == "error":
            print("[voice]", result[1])
        with self._lock:
            self._result = result
            self.listening = False
            self.level = 0.0

    def _listen_pyaudio(self, timeout, phrase_time_limit):
        with self.microphone as source:
            if not self._calibrated:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                self._calibrated = True
            return self.recognizer.listen(
                source, timeout=timeout, phrase_time_limit=phrase_time_limit)

    def _listen_sounddevice(self, timeout, phrase_time_limit):
        """Record one phrase: wait for speech, stop after a short silence."""
        rate, block = self.rate, self.BLOCK
        pause_blocks = max(1, int(0.7 * rate / block))
        with self.sd.RawInputStream(samplerate=rate, channels=1, dtype="int16",
                                    blocksize=block, device=self.device) as stream:

            def read_block():
                data, _ = stream.read(block)
                data = bytes(data)
                samples = array.array("h")
                samples.frombytes(data)
                rms = math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0
                return data, rms

            # Measure the room on every press (0.4 s).  The trigger level is
            # relative to the noise floor with a LOW minimum, so quiet laptop
            # microphones still work.
            levels = [read_block()[1] for _ in range(int(0.4 * rate / block) + 1)]
            noise = sum(levels) / len(levels)
            self.peak = max(levels)
            threshold = max(40.0, noise * 2.5 + 15.0)

            started = False
            frames, silent = [], 0
            lead_in = deque(maxlen=4)     # keep the syllable before the trigger
            began = time.time()
            speech_began = 0.0
            while True:
                data, rms = read_block()
                now = time.time()
                self.peak = max(self.peak, rms)
                self.level = rms
                if not started:
                    self.status = (f"Mic '{self.device_name[:20]}' level {int(rms)} "
                                   f"(need > {int(threshold)})")
                    lead_in.append(data)
                    if rms > threshold:
                        started, speech_began = True, now
                        frames.extend(lead_in)
                    elif now - began > timeout:
                        raise self.sr.WaitTimeoutError()
                else:
                    frames.append(data)
                    silent = silent + 1 if rms < threshold else 0
                    if silent >= pause_blocks or now - speech_began >= phrase_time_limit:
                        break
        return self.sr.AudioData(b"".join(frames), rate, 2)
