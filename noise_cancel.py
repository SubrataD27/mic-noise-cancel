#!/usr/bin/env python3
"""
noise_cancel.py - real-time microphone noise cancellation for calls & meetings.

Pipeline (per 10 ms frame, 48 kHz mono):

    earphone mic --> RNNoise (neural denoiser) --> voice gate --> virtual cable --> Teams / Zoom / Meet
                         |                            |
                         +-- speech probability ------+
                                                      +-- "near-voice" level gate (from calibration)

  1. RNNoise removes steady and non-speech noise: fans, AC, traffic, keyboard,
     horns, pressure cooker, etc.
  2. The voice gate mutes the output whenever RNNoise says "no speech", with a
     short hold so word endings are not clipped.
  3. The level gate (set by --calibrate) mutes speech that is much quieter than
     your own voice at the mic - i.e. people talking in the background or a TV.
     This is how the script approximates "only my voice": you are the closest,
     loudest talker at your own earphone mic.

Usage
    python noise_cancel.py --list                       # show audio devices
    python noise_cancel.py --calibrate                  # one-time: measure room + your voice
    python noise_cancel.py                              # run (uses saved settings)
    python noise_cancel.py --input 3 --output 7         # pick devices by index
    python noise_cancel.py --monitor                    # also hear the cleaned audio yourself
    python noise_cancel.py --file in.wav out.wav        # clean a recording (for testing)

While running:  Enter = toggle bypass (compare raw vs cleaned)   q + Enter = quit
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import platform
import queue
import sys
import threading
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 48_000          # RNNoise works natively at 48 kHz
FRAME = 480                   # 10 ms
CONFIG_PATH = Path(__file__).resolve().with_name(".noise_cancel.json")


# --------------------------------------------------------------------------- #
# RNNoise engine (native library shipped inside the `pyrnnoise` wheel)
# --------------------------------------------------------------------------- #
class RNNoiseEngine:
    """Thin ctypes wrapper. Loads the bundled library without importing the
    package's heavier Python layer."""

    _LIB_NAMES = {"Windows": "rnnoise.dll", "Darwin": "librnnoise.dylib", "Linux": "librnnoise.so"}

    def __init__(self) -> None:
        spec = importlib.util.find_spec("pyrnnoise")
        if spec is None or not spec.submodule_search_locations:
            sys.exit("pyrnnoise is not installed. Run:  pip install pyrnnoise")
        pkg_dir = Path(list(spec.submodule_search_locations)[0])
        lib_path = pkg_dir / self._LIB_NAMES.get(platform.system(), "")
        if not lib_path.exists():
            sys.exit(f"RNNoise native library not found at {lib_path}")

        lib = ctypes.CDLL(str(lib_path))
        lib.rnnoise_create.argtypes = [ctypes.c_void_p]
        lib.rnnoise_create.restype = ctypes.c_void_p
        lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
        lib.rnnoise_process_frame.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float)]
        lib.rnnoise_process_frame.restype = ctypes.c_float
        lib.rnnoise_get_frame_size.restype = ctypes.c_int
        if lib.rnnoise_get_frame_size() != FRAME:
            sys.exit("Unexpected RNNoise frame size.")
        self._lib = lib
        self._state = lib.rnnoise_create(None)
        self._buf = np.zeros(FRAME, dtype=np.float32)
        self._ptr = self._buf.ctypes.data_as(ctypes.POINTER(ctypes.c_float))

    def process(self, frame: np.ndarray) -> tuple[np.ndarray, float]:
        """frame: float32 in [-1, 1], length 480. Returns (denoised, speech_prob)."""
        self._buf[:] = frame * 32768.0           # RNNoise expects int16 range
        prob = self._lib.rnnoise_process_frame(self._state, self._ptr, self._ptr)
        return self._buf / 32768.0, float(prob)

    def __del__(self) -> None:
        if getattr(self, "_state", None):
            self._lib.rnnoise_destroy(self._state)
            self._state = None


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@dataclass
class Settings:
    input_device: int | str | None = None
    output_device: int | str | None = None
    vad_threshold: float = 0.60      # RNNoise speech probability needed to open the gate
    hold_ms: int = 250               # keep gate open this long after speech stops
    floor_db: float = -60.0          # attenuation when gate is closed (-60 dB is effectively mute)
    level_gate_db: float | None = None   # min frame level (dBFS) to count as *your* voice
    input_gain_db: float = 0.0       # boost a quiet earphone mic

    @classmethod
    def load(cls) -> "Settings":
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2))


def dbfs(x: np.ndarray) -> float:
    return 20.0 * np.log10(np.sqrt(np.mean(x * x)) + 1e-9)


# --------------------------------------------------------------------------- #
# Processor: RNNoise + gates, frame-exact with a FIFO for odd block sizes
# --------------------------------------------------------------------------- #
class Processor:
    def __init__(self, s: Settings) -> None:
        self.s = s
        self.engine = RNNoiseEngine()
        self.floor = 10 ** (s.floor_db / 20)
        self.in_gain = 10 ** (s.input_gain_db / 20)
        self.hold_frames = max(1, s.hold_ms // 10)
        self.hold = 0
        self.gain = self.floor
        self.bypass = False
        self._in = np.zeros(0, dtype=np.float32)
        self._out = np.zeros(0, dtype=np.float32)
        # live stats for the meter
        self.last_prob = 0.0
        self.last_level = -120.0
        self.gate_open = False

    def _frame(self, x: np.ndarray) -> np.ndarray:
        x = np.clip(x * self.in_gain, -1.0, 1.0)
        y, prob = self.engine.process(x)
        level = dbfs(x)
        self.last_prob, self.last_level = prob, level

        is_voice = prob >= self.s.vad_threshold
        if self.s.level_gate_db is not None and level < self.s.level_gate_db:
            is_voice = False                           # speech, but too far away -> not you
        if is_voice:
            self.hold = self.hold_frames
        elif self.hold > 0:
            self.hold -= 1
        self.gate_open = self.hold > 0

        target = 1.0 if self.gate_open else self.floor
        # fast attack (~10 ms), slower release (~60 ms) to avoid choppy audio
        coef = 0.35 if target > self.gain else 0.85
        new_gain = coef * self.gain + (1 - coef) * target
        ramp = np.linspace(self.gain, new_gain, FRAME, dtype=np.float32)
        self.gain = new_gain

        if self.bypass:
            return x
        return np.clip(y * ramp, -1.0, 1.0)

    def process(self, block: np.ndarray) -> np.ndarray:
        """Process any-length mono float32 block; output has the same length."""
        n = len(block)
        if n % FRAME == 0 and len(self._in) == 0 and len(self._out) == 0:
            return np.concatenate([self._frame(block[i:i + FRAME]) for i in range(0, n, FRAME)])
        # irregular block sizes: buffer (adds <=10 ms latency)
        self._in = np.concatenate([self._in, block])
        while len(self._in) >= FRAME:
            self._out = np.concatenate([self._out, self._frame(self._in[:FRAME])])
            self._in = self._in[FRAME:]
        if len(self._out) >= n:
            out, self._out = self._out[:n], self._out[n:]
            return out
        out = np.zeros(n, dtype=np.float32)
        out[n - len(self._out):] = self._out
        self._out = np.zeros(0, dtype=np.float32)
        return out


# --------------------------------------------------------------------------- #
# Audio device helpers (sounddevice imported lazily so --file works without it)
# --------------------------------------------------------------------------- #
def _sd():
    try:
        import sounddevice as sd
        return sd
    except (ImportError, OSError) as e:
        sys.exit(f"sounddevice / PortAudio not available ({e}). Run:  pip install sounddevice")


def list_devices() -> None:
    sd = _sd()
    apis = sd.query_hostapis()
    print(f"{'#':>3}  {'in':>2} {'out':>3}  {'API':<18} name")
    for i, d in enumerate(sd.query_devices()):
        print(f"{i:>3}  {d['max_input_channels']:>2} {d['max_output_channels']:>3}  "
              f"{apis[d['hostapi']]['name']:<18} {d['name']}")
    print("\nInput  = your earphone mic.   Output = 'CABLE Input (VB-Audio Virtual Cable)'.")
    print("Tip: if a device fails to open at 48 kHz, pick its 'MME' entry - Windows resamples for you.")


def find_device(sd, name_part: str, kind: str) -> int | None:
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    for i, d in enumerate(sd.query_devices()):
        if d[key] > 0 and name_part.lower() in d["name"].lower():
            return i
    return None


def resolve_devices(sd, s: Settings) -> tuple:
    inp, out = s.input_device, s.output_device
    if isinstance(inp, str) and not inp.isdigit():
        inp = find_device(sd, inp, "input")
        if inp is None:
            sys.exit(f"Input device not found: {s.input_device}. Run --list.")
    if isinstance(out, str) and not out.isdigit():
        out = find_device(sd, out, "output")
        if out is None:
            sys.exit(f"Output device not found: {s.output_device}. Run --list.")
    if out is None:
        out = find_device(sd, "CABLE Input", "output")   # VB-Cable on Windows
    if out is None:
        out = find_device(sd, "BlackHole", "output")     # macOS equivalent
    if out is None:
        sys.exit("No virtual cable found. Install VB-Cable (Windows) or BlackHole (macOS), "
                 "or pass --output <index>. See --list.")
    return (int(inp) if inp is not None else None), int(out)


# --------------------------------------------------------------------------- #
# Calibration
# --------------------------------------------------------------------------- #
def record(sd, device, seconds: float) -> np.ndarray:
    data = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1,
                  dtype="float32", device=device)
    sd.wait()
    return data[:, 0]


def calibrate(s: Settings) -> None:
    sd = _sd()
    inp = s.input_device
    if isinstance(inp, str) and not inp.isdigit():
        inp = find_device(sd, inp, "input")
        if inp is None:
            sys.exit(f"Input device not found: {s.input_device}. Run --list.")
    inp = int(inp) if inp is not None else None
    print("\nCalibration - wear your earphones as you would in a call.\n")
    input("Step 1/2: stay SILENT (let the room noise play). Press Enter, then wait 4 s...")
    noise = record(sd, inp, 4.0)
    input("Step 2/2: TALK normally for 6 s (read anything aloud). Press Enter to start...")
    voice = record(sd, inp, 6.0)

    eng = RNNoiseEngine()
    voice_levels = []
    for i in range(0, len(voice) - FRAME, FRAME):
        f = voice[i:i + FRAME]
        _, p = eng.process(f)
        if p > 0.7:
            voice_levels.append(dbfs(f))
    noise_level = np.percentile([dbfs(noise[i:i + FRAME]) for i in range(0, len(noise) - FRAME, FRAME)], 90)

    if len(voice_levels) < 50:
        print("\nCould not detect enough speech. Speak a bit louder / closer and run --calibrate again.")
        return
    voice_level = float(np.percentile(voice_levels, 20))   # quieter end of your own speech
    if voice_level < -50:
        s.input_gain_db = round(min(18.0, -40 - voice_level), 1)
        print(f"Your mic is quiet; adding {s.input_gain_db} dB input gain.")
        voice_level += s.input_gain_db
        noise_level += s.input_gain_db
    # gate sits between background and your voice, never closer than 6 dB to your voice
    s.level_gate_db = round(float(min(voice_level - 6, max(noise_level + 6, voice_level - 15))), 1)
    s.save()
    print(f"\nRoom noise ~{noise_level:.1f} dBFS | your voice ~{voice_level:.1f} dBFS "
          f"| voice gate set to {s.level_gate_db} dBFS")
    print(f"Saved to {CONFIG_PATH}. Now run:  python noise_cancel.py")


# --------------------------------------------------------------------------- #
# Live mode
# --------------------------------------------------------------------------- #
def run_live(s: Settings, monitor: bool) -> None:
    sd = _sd()
    inp, out = resolve_devices(sd, s)
    proc = Processor(s)
    mon_q: queue.Queue = queue.Queue(maxsize=20)
    status_flags = {"xruns": 0}

    def callback(indata, outdata, frames, time_info, status):
        if status:
            status_flags["xruns"] += 1
        y = proc.process(indata[:, 0].astype(np.float32))
        outdata[:] = y.reshape(-1, 1).repeat(outdata.shape[1], axis=1)
        if monitor:
            try:
                mon_q.put_nowait(y.copy())
            except queue.Full:
                pass

    try:
        stream = sd.Stream(device=(inp, out), samplerate=SAMPLE_RATE, blocksize=FRAME,
                           dtype="float32", channels=(1, min(2, sd.query_devices(out)["max_output_channels"])),
                           latency="low", callback=callback)
    except Exception as e:
        sys.exit(f"Could not open audio devices at 48 kHz: {e}\n"
                 "Run --list and choose the 'MME' version of your mic / CABLE Input.")

    mon_stream = None
    if monitor:
        def mon_cb(outdata, frames, t, status):
            try:
                outdata[:, 0] = mon_q.get_nowait()[:frames]
            except queue.Empty:
                outdata.fill(0)
        mon_stream = sd.OutputStream(samplerate=SAMPLE_RATE, blocksize=FRAME, channels=1,
                                     dtype="float32", callback=mon_cb)

    stop = threading.Event()

    def keys():
        for line in sys.stdin:
            if line.strip().lower() == "q":
                stop.set()
                return
            proc.bypass = not proc.bypass

    threading.Thread(target=keys, daemon=True).start()

    devs = sd.query_devices()
    print(f"\nMic   : {devs[inp]['name'] if inp is not None else 'system default'}")
    print(f"Output: {devs[out]['name']}")
    if "cable" in devs[out]['name'].lower():
        print("In Teams/Zoom/Meet set Microphone = 'CABLE Output (VB-Audio Virtual Cable)'.")
    else:
        print("Listening test: cleaned audio is playing through the selected output.")
    print("Enter = toggle bypass   q + Enter = quit\n")

    with stream:
        if mon_stream:
            mon_stream.start()
        try:
            while not stop.is_set():
                bar = "#" * int(max(0, min(30, (proc.last_level + 70) / 2)))
                state = "BYPASS " if proc.bypass else ("VOICE  " if proc.gate_open else "muted  ")
                sys.stdout.write(f"\r[{state}] speech {proc.last_prob:4.2f}  level {proc.last_level:6.1f} dB "
                                 f"|{bar:<30}| glitches {status_flags['xruns']}   ")
                sys.stdout.flush()
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            if mon_stream:
                mon_stream.stop()
                mon_stream.close()
    print("\nStopped.")


# --------------------------------------------------------------------------- #
# File mode (test the processing without any audio devices)
# --------------------------------------------------------------------------- #
def process_file(s: Settings, src: str, dst: str) -> None:
    with wave.open(src, "rb") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        sys.exit("Only 16-bit PCM WAV files are supported.")
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32).reshape(-1, ch).mean(axis=1) / 32768.0
    if rate != SAMPLE_RATE:   # linear resample - fine for speech testing
        t_new = np.arange(int(len(x) * SAMPLE_RATE / rate)) / SAMPLE_RATE
        x = np.interp(t_new, np.arange(len(x)) / rate, x).astype(np.float32)
    pad = (-len(x)) % FRAME
    y = Processor(s).process(np.pad(x, (0, pad)))[:len(x)]
    with wave.open(dst, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f"Wrote {dst}  (input {dbfs(x):.1f} dBFS -> output {dbfs(y):.1f} dBFS)")


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Real-time mic noise cancellation for calls.")
    ap.add_argument("--list", action="store_true", help="list audio devices")
    ap.add_argument("--calibrate", action="store_true", help="measure room noise and your voice")
    ap.add_argument("--input", help="input device index or name part (your earphone mic)")
    ap.add_argument("--output", help="output device index or name part (virtual cable)")
    ap.add_argument("--vad", type=float, help="speech threshold 0-1 (higher = stricter, default 0.6)")
    ap.add_argument("--floor", type=float, help="closed-gate level in dB (default -60)")
    ap.add_argument("--no-level-gate", action="store_true", help="disable the 'near voice only' gate")
    ap.add_argument("--monitor", action="store_true", help="play cleaned audio to your earphones")
    ap.add_argument("--file", nargs=2, metavar=("IN_WAV", "OUT_WAV"), help="process a WAV file")
    a = ap.parse_args()

    if a.list:
        return list_devices()
    s = Settings.load()
    if a.input is not None:
        s.input_device = int(a.input) if a.input.isdigit() else a.input
    if a.output is not None:
        s.output_device = int(a.output) if a.output.isdigit() else a.output
    if a.vad is not None:
        s.vad_threshold = a.vad
    if a.floor is not None:
        s.floor_db = a.floor
    if a.input is not None or a.output is not None or a.vad is not None or a.floor is not None:
        s.save()
    if a.no_level_gate:
        s.level_gate_db = None

    if a.file:
        return process_file(s, *a.file)
    if a.calibrate:
        return calibrate(s)
    if s.level_gate_db is None and not a.no_level_gate:
        print("Tip: run  python noise_cancel.py --calibrate  once for 'my voice only' filtering.")
    run_live(s, a.monitor)


if __name__ == "__main__":
    main()
