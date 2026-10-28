"""
Voice diagnostic:  python voice_check.py
Walks through every step voice control needs and says exactly which one fails.
"""
import sys
sys.dont_write_bytecode = True
import socket
import time


def step(title):
    print(f"\n== {title}")


def main():
    print("Python", sys.version.split()[0])

    step("1. SpeechRecognition package")
    try:
        import speech_recognition as sr
        print("OK  version", sr.__version__)
    except Exception as exc:
        print("FAIL", type(exc).__name__, exc)
        print("FIX  pip install SpeechRecognition   (Python 3.13 also needs: pip install audioop-lts)")
        return

    step("2. Microphone back-ends")
    try:
        import pyaudio  # noqa: F401
        print("PyAudio     : installed")
    except Exception as exc:
        print("PyAudio     : not available (", type(exc).__name__, ") - optional")
    try:
        import sounddevice as sd
        print("sounddevice : installed")
        print("Input devices:")
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                print(f"   [{i}] {d['name']}  ({int(d['default_samplerate'])} Hz)")
        print("Default input:", sd.query_devices(kind="input")["name"])
    except Exception as exc:
        print("sounddevice : FAIL", type(exc).__name__, exc)
        print("FIX  pip install sounddevice   (Linux: sudo apt install libportaudio2)")

    step("2b. Microphone level test - SPEAK continuously for the next few seconds")
    try:
        import array, math, sounddevice as sd
        results = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] <= 0:
                continue
            try:
                rate = int(d["default_samplerate"])
                rec = sd.rec(int(1.5 * rate), samplerate=rate, channels=1,
                             dtype="int16", device=i)
                sd.wait()
                samples = array.array("h", rec.tobytes())
                step_ = max(1, rate // 20)
                peak = max(math.sqrt(sum(x * x for x in samples[k:k + step_]) / len(samples[k:k + step_]))
                           for k in range(0, len(samples) - step_, step_))
                results.append((peak, i, d["name"]))
                print(f"   [{i}] peak level {peak:7.0f}   {d['name']}")
            except Exception as exc:
                print(f"   [{i}] cannot open: {type(exc).__name__}: {str(exc)[:60]}   {d['name']}")
        if results:
            best = max(results)
            if best[0] < 3:
                print("ALL devices are silent -> microphone muted/blocked. Windows: Settings > "
                      "Privacy & security > Microphone > turn ON 'Let desktop apps access your microphone'.")
            else:
                print(f"Best device: [{best[1]}] {best[2]}")
                print(f"If the game does not hear you, set it in Windows terminal before running:")
                print(f"   $env:BAYESMORRIS_MIC={best[1]}      (PowerShell)")
    except Exception as exc:
        print("level test skipped:", type(exc).__name__, exc)

    step("3. Internet (the free Google recognizer needs it)")
    try:
        socket.create_connection(("www.google.com", 443), timeout=4).close()
        print("OK  reached google.com")
    except Exception as exc:
        print("FAIL", exc, "- voice cannot recognise speech offline")

    step("4. Game voice engine")
    from voice.speech_input import SpeechInput
    from voice.command_parser import parse_command
    speech = SpeechInput()
    if not speech.available:
        print("FAIL", speech.error)
        for line in speech.details:
            print("    ", line)
        print("Also check OS microphone permission for your terminal / VS Code.")
        return
    print("OK  backend:", speech.backend, "| rate:", getattr(speech, "rate", "-"))

    step("5. Live test - after 'Listening', say:  place twelve")
    speech.start_listening()
    started = time.time()
    while time.time() - started < 20:
        result = speech.poll()
        if result:
            kind, payload = result
            print("result:", kind, "|", payload)
            if kind == "text":
                print("parsed:", parse_command(payload))
            return
        time.sleep(0.1)
    print("FAIL no result after 20 s")


if __name__ == "__main__":
    main()
