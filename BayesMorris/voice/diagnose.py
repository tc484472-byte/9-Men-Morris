"""
Voice troubleshooting.  Run from the project folder:

    python -m voice.diagnose

It checks every link in the chain (libraries, microphone, internet, speech
service) and tells you which one is broken.
"""
import platform
import sys
import time
import urllib.request


def step(name, ok, info=""):
    print(f"[{'OK' if ok else 'FAIL'}] {name} {info}")
    return ok


def main():
    print(f"Python {sys.version.split()[0]} on {platform.platform()}\n")

    try:
        import speech_recognition as sr
        step("SpeechRecognition installed", True, sr.__version__)
    except Exception as exc:
        step("SpeechRecognition installed", False,
             f"-> pip install SpeechRecognition   ({exc})")
        return

    have_pyaudio = have_sd = False
    try:
        import pyaudio  # noqa: F401
        have_pyaudio = True
    except Exception:
        pass
    step("PyAudio installed", have_pyaudio, "" if have_pyaudio else "(optional)")
    try:
        import sounddevice as sd
        have_sd = True
        devices = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
        step("sounddevice installed", True, f"input devices: {devices or 'NONE'}")
    except Exception as exc:
        step("sounddevice installed", False,
             f"-> pip install sounddevice   ({type(exc).__name__}: {exc})")
    if not (have_pyaudio or have_sd):
        print("\nFIX: run   pip install sounddevice   (no compiler needed) and re-run this.")
        return

    try:
        from speech_recognition.audio import get_flac_converter
        step("FLAC converter (needed by Google recognizer)", True, get_flac_converter())
    except Exception as exc:
        step("FLAC converter (needed by Google recognizer)", False, str(exc))

    try:
        urllib.request.urlopen("https://www.google.com", timeout=6)
        step("Internet / Google reachable", True)
    except Exception as exc:
        step("Internet / Google reachable", False,
             f"-> voice needs internet ({type(exc).__name__}: {exc})")

    from voice.speech_input import SpeechInput
    speech = SpeechInput()
    if not step(f"Microphone opened (backend: {speech.backend})", speech.available,
                speech.error or ""):
        for line in speech.details:
            print("      ", line)
        return

    print("\nSpeak now, e.g. 'place twelve' ...")
    speech.start_listening(timeout=8)
    result = None
    t = time.time()
    while result is None and time.time() - t < 20:
        result = speech.poll()
        time.sleep(0.05)
    kind, payload = result or ("error", "timed out")
    step("Heard you", kind == "text", payload)
    if kind == "none":
        print("\nNo speech reached the app. Windows: Settings > Privacy & security >"
              " Microphone > allow desktop apps; also check the input device/volume.")
    if kind == "text":
        from voice.command_parser import parse_command
        print("Parsed as:", parse_command(payload))


if __name__ == "__main__":
    main()
