# Noise Cancel — mic cleanup for Teams / Zoom / Meet

Cleans your earphone mic in real time and feeds the clean audio to your meeting app through a virtual microphone.

```
Earphone mic → noise_cancel.py (RNNoise + voice gate) → VB-Cable → Teams / Zoom / Meet
```

## One-time setup (Windows)

1. **Install Python 3.10+** (python.org — tick "Add to PATH").
2. **Install VB-Cable** (free virtual mic): https://vb-audio.com/Cable/ → run `VBCABLE_Setup_x64.exe` as admin → restart.
3. **Install the libraries**:
   ```
   pip install pyrnnoise sounddevice numpy
   ```
4. **Find your devices**:
   ```
   python noise_cancel.py --list
   ```
   Note the index of your earphone mic (e.g. `Headset Microphone (boAt…)`).
5. **Calibrate** (wear earphones, normal room noise):
   ```
   python noise_cancel.py --input <mic index> --calibrate
   ```
   Stay silent for 4 s, then talk for 6 s. This sets the "my voice only" gate.

## Every meeting

```
python noise_cancel.py
```
Then in the meeting app:
- **Microphone → `CABLE Output (VB-Audio Virtual Cable)`**
- **Speaker → your earphones** (unchanged)
- **Teams noise suppression → Off or Low** (double processing makes your voice sound robotic)

Controls: **Enter** toggles bypass (A/B compare) · **q + Enter** quits.
Use `--monitor` to hear the cleaned audio yourself while testing.

## Tuning

| Problem | Fix |
|---|---|
| Background chatter / TV still gets through | Re-run `--calibrate`, or `--vad 0.75` |
| Start/end of your words get cut | `--vad 0.45` |
| You sound too quiet | Speak closer to the mic and re-calibrate (it adds gain automatically) |
| Device won't open at 48 kHz | Pick the **MME** entry of that device from `--list` |
| Bluetooth earbuds sound muffled | That's Bluetooth call mode (16 kHz). Wired or USB earphones sound better |
| Crackles / "glitches" counter rising | Close heavy apps; plug in the laptop |

## What it can and can't do

- **Removes well:** fans, AC, traffic, horns, keyboard, construction, pressure cooker, crowd hum.
- **Reduces:** people talking nearby — filtered by loudness, since you are the closest voice to your mic.
- **Can't fully remove:** someone talking loudly right next to you, or noise *while* you speak at the same volume as you. No software is 100% here.
