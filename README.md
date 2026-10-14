# Mic Noise Cancel — free AI noise cancellation for Teams, Zoom & Google Meet

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-lightgrey.svg)

**Free, open-source, real-time background noise removal for your microphone.** A lightweight alternative to Krisp / NVIDIA Broadcast that runs on any laptop CPU, with no GPU, no account and no cloud.

It cleans your earphone or laptop mic live with the **RNNoise** neural denoiser plus a "my voice only" gate, and feeds the clean audio to any meeting app through a virtual microphone (VB-Cable).

```
Mic → noise_cancel.py (RNNoise + voice gate) → VB-Cable → Teams / Zoom / Meet / Discord / OBS
```

## Features

- 🎧 **Real-time noise suppression** with about 10 ms frames and low latency
- 🧠 **AI denoiser (RNNoise)**: removes fans, AC, traffic, horns, keyboard typing, construction, pressure cooker and crowd hum
- 🗣️ **"Only my voice" gate**: after a 10-second calibration it mutes quieter voices in the background (TV, family, colleagues)
- 🔁 **A/B bypass**: press Enter to compare raw and cleaned audio live
- 💻 **CPU only**: works on any Windows laptop, offline and private
- 🎙️ Works with **Microsoft Teams, Zoom, Google Meet, Discord, Skype, OBS** or any app that lets you pick a microphone
- 📁 Can also clean a recorded `.wav` file

## Quick start (Windows)

1. **Install Python 3.10+** from [python.org](https://www.python.org/downloads/) and tick "Add to PATH".
2. **Install VB-Cable** (free virtual mic) from https://vb-audio.com/Cable/: run `VBCABLE_Setup_x64.exe` as admin, then restart.
3. **Download this project**:
   ```
   git clone https://github.com/SubrataD27/mic-noise-cancel.git
   cd mic-noise-cancel
   ```
   or click **Code → Download ZIP** and extract it.
4. **Install the dependencies**: double-click `Install.cmd`, or run:
   ```
   pip install -r requirements.txt
   ```
5. **Find your devices**:
   ```
   python noise_cancel.py --list
   ```
   Note your mic's name or index, for example `Headset Microphone (boAt…)`.
6. **Calibrate** with your earphones on and normal room noise:
   ```
   python noise_cancel.py --input <mic index or name> --calibrate
   ```
   Stay silent for 4 s, then talk for 6 s. This sets the "my voice only" gate.

> The `.cmd` launchers (`Calibrate Mic.cmd`, `Start Noise Canceller.cmd`, `Test in Earphones.cmd`) are double-click shortcuts. They are set up for a Realtek mic. Open them in Notepad and change the device names to match yours from `--list`.

## Every meeting

```
python noise_cancel.py --output "CABLE Input"
```

Then in your meeting app:
- **Microphone → `CABLE Output (VB-Audio Virtual Cable)`**
- **Speaker → your earphones** (unchanged)
- **Built-in noise suppression → Off or Low** (processing the audio twice makes your voice sound robotic)

Controls: **Enter** toggles bypass (A/B compare) · **q + Enter** quits.
Use `--monitor` to hear the cleaned audio yourself while testing.

## Command-line options

| Option | What it does |
|---|---|
| `--list` | List audio devices |
| `--calibrate` | Measure room noise and your voice (saved for next time) |
| `--input X` | Mic device, by index or part of its name |
| `--output X` | Output device (the virtual cable), by index or part of its name |
| `--vad 0.6` | Speech threshold 0–1 (higher = stricter) |
| `--floor -60` | Level when the gate is closed, in dB |
| `--no-level-gate` | Turn off the "only my voice" gate |
| `--monitor` | Play the cleaned audio to your earphones |
| `--file in.wav out.wav` | Clean a WAV recording |

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
- **Reduces:** people talking nearby. They are filtered by loudness, since you are the closest voice to your mic.
- **Can't fully remove:** someone talking loudly right next to you, or noise *while* you speak at the same volume as you. No software is 100% here.

## How it works

Each 10 ms frame at 48 kHz mono goes through three steps:

1. **RNNoise** (a recurrent neural network denoiser) removes steady and non-speech noise and gives a speech probability.
2. A **voice gate** mutes the output when there is no speech, with a short hold so word endings aren't clipped.
3. A **level gate**, set by calibration, mutes speech much quieter than your own voice, such as background talkers.

## Contributing

Issues and pull requests are welcome, whether it's a bug report, macOS/Linux support, a GUI or a tray app. If this project helped you, please ⭐ **star the repo** so more people can find it.

## License

[MIT](LICENSE) © 2026 SubrataD27. Free to use, modify and share, including commercially, as long as the copyright notice is kept.

Built on [RNNoise](https://github.com/xiph/rnnoise) (Xiph.Org, BSD license) via [pyrnnoise](https://pypi.org/project/pyrnnoise/), and [VB-Cable](https://vb-audio.com/Cable/) (donationware by VB-Audio, installed separately).
