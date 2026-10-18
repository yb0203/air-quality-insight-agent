"""Synthesise the soundtrack from beatmap.json: a 120 BPM music bed plus beat-locked sound effects.

Everything is generated in code (NumPy + SciPy), seeded, so the same beat map always gives the
same audio and nothing needs licensing. The night section is low-passed (quiet hours sound muffled)
and opens at the 06:30 drop.

    python3 docs/demo/video/scripts/make_audio.py [--vo path/to/voiceover.wav]

Writes audio/music.wav, audio/sfx.wav and audio/mix.wav, then a loudness-normalised
composition/assets/audio/mix.m4a (about -14 LUFS, true peak <= -1 dBTP) for the composition.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import wave
from pathlib import Path

import numpy as np
from scipy import signal

VIDEO = Path(__file__).resolve().parents[1]
SR = 48_000
RNG = np.random.default_rng(20261018)

BM = json.loads((VIDEO / "beatmap.json").read_text())
DUR, BEAT, BAR = BM["duration"], BM["beat"], BM["bar"]
CUES = BM["cues"]
N = int(DUR * SR)

NOTE = {"A1": 55.0, "C2": 65.41, "D2": 73.42, "E2": 82.41, "F2": 87.31, "G2": 98.0, "A2": 110.0,
        "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61, "G3": 196.0, "A3": 220.0, "B3": 246.94,
        "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23, "G4": 392.0, "A4": 440.0, "B4": 493.88,
        "C5": 523.25, "D5": 587.33, "E5": 659.25, "G5": 783.99, "A5": 880.0}
CHORDS = {  # root for the bass, voicing for pad and arp
    "Am": ("A1", ["A3", "C4", "E4", "A4"]),
    "F": ("F2", ["F3", "A3", "C4", "F4"]),
    "C": ("C2", ["C4", "E4", "G4", "C5"]),
    "G": ("G2", ["G3", "B3", "D4", "G4"]),
}


def section(t: float) -> str:
    return next(s["id"] for s in BM["sections"] if s["start"] <= t < s["end"])


def chord_at(t: float) -> str:
    bar = int(t // BAR)
    if bar >= 29:
        return "C"
    if bar == 28:
        return "F"
    return BM["chords"][bar % 4]


# ---------- primitives ----------

def tvec(d: float) -> np.ndarray:
    return np.arange(int(d * SR)) / SR


def adsr(n: int, a: float, r: float) -> np.ndarray:
    e = np.ones(n)
    na, nr = min(int(a * SR), n), min(int(r * SR), n)
    if na:
        e[:na] = np.linspace(0, 1, na)
    if nr:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e


def lp(x: np.ndarray, hz: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(signal.butter(order, min(hz, SR / 2 - 100), "low", fs=SR, output="sos"), x)


def hp(x: np.ndarray, hz: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(signal.butter(order, hz, "high", fs=SR, output="sos"), x)


def bp(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return signal.sosfilt(signal.butter(2, [lo, hi], "band", fs=SR, output="sos"), x)


def saw(f: float, d: float, harmonics: int = 10) -> np.ndarray:
    t = tvec(d)
    return sum(np.sin(2 * np.pi * f * k * t) / k for k in range(1, harmonics + 1)) * 0.6


def noise(d: float) -> np.ndarray:
    return RNG.standard_normal(int(d * SR))


def sweep_filter(x: np.ndarray, f0: float, f1: float, kind: str = "low", blocks: int = 48) -> np.ndarray:
    """Filter x with a cutoff that moves exponentially from f0 to f1 (block-wise, state carried)."""
    out = np.zeros_like(x)
    edges = np.linspace(0, len(x), blocks + 1).astype(int)
    zi = None
    for i in range(blocks):
        f = f0 * (f1 / f0) ** (i / max(blocks - 1, 1))
        sos = signal.butter(2, min(f, SR / 2 - 100), kind, fs=SR, output="sos")
        if zi is None:
            zi = np.zeros((sos.shape[0], 2))
        out[edges[i]:edges[i + 1]], zi = signal.sosfilt(sos, x[edges[i]:edges[i + 1]], zi=zi)
    return out


# ---------- instruments ----------

def kick(gain=1.0):
    t = tvec(0.45)
    f = 45 + 110 * np.exp(-t * 32)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7.5)
    click = hp(noise(0.006), 2000) * 0.25
    body[: len(click)] += click
    return body * gain


def hat(open_=False, gain=1.0):
    d = 0.22 if open_ else 0.045
    x = hp(noise(d), 7000, 4)
    return x * np.exp(-tvec(d) * (14 if open_ else 80)) * 0.35 * gain


def clap(gain=1.0):
    x = np.zeros(int(0.2 * SR))
    for off in (0, 0.011, 0.022):
        b = bp(noise(0.18), 900, 2800) * np.exp(-tvec(0.18) * 22)
        i = int(off * SR)
        x[i:i + len(b)] += b[: len(x) - i]
    return x * 0.3 * gain


def bass(note: str, d: float, gain=1.0):
    x = lp(saw(NOTE[note], d, 8), 520) * adsr(int(d * SR), 0.005, 0.06)
    return x * gain


def pad(chord: str, d: float, gain=1.0):
    _, voicing = CHORDS[chord]
    x = sum(saw(NOTE[n] * det, d, 6) for n in voicing for det in (0.997, 1.0, 1.004))
    return lp(x, 1600) * adsr(int(d * SR), 0.35, 0.5) * 0.06 * gain


def pluck(f: float, d=0.5, gain=1.0, bright=1.0):
    t = tvec(d)
    x = sum(np.sin(2 * np.pi * f * k * t) * np.exp(-t * (5 + 7 * k / bright)) / k for k in range(1, 6))
    return x * 0.35 * gain * adsr(len(t), 0.002, 0.02)


def chime(f: float, d=1.8, gain=1.0):
    t = tvec(d)
    x = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * dk) for r, a, dk in
            ((1, 1, 2.2), (2.76, 0.45, 4), (5.4, 0.25, 7), (8.93, 0.12, 10)))
    return x * 0.25 * gain * adsr(len(t), 0.002, 0.05)


def sub_hit(gain=1.0, d=1.4):
    t = tvec(d)
    f = 42 + 30 * np.exp(-t * 6)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.6)
    x[: int(0.03 * SR)] += lp(noise(0.03), 1500) * 0.4
    return x * gain


def crash(gain=1.0):
    return hp(noise(2.0), 4000, 2) * np.exp(-tvec(2.0) * 2.2) * 0.22 * gain


def buzz(gain=1.0):
    t = tvec(0.2)
    x = np.tanh(3 * np.sin(2 * np.pi * 172 * t)) * (0.6 + 0.4 * np.sin(2 * np.pi * 26 * t))
    return lp(x, 2500) * adsr(len(t), 0.005, 0.03) * 0.35 * gain


def haptic(gain=1.0):
    x = np.zeros(int(0.35 * SR))
    for off in (0.0, 0.11):
        t = tvec(0.07)
        p = np.sin(2 * np.pi * 230 * t) * adsr(len(t), 0.003, 0.02)
        i = int(off * SR)
        x[i:i + len(p)] += p * 0.5
    t = tvec(0.35)
    x += np.sin(2 * np.pi * 55 * t) * np.exp(-t * 12) * 0.9
    return x * gain


def tick(f=2600, gain=1.0):
    t = tvec(0.03)
    return np.sin(2 * np.pi * f * t) * np.exp(-t * 220) * 0.4 * gain


def tap(gain=1.0):
    t = tvec(0.04)
    return (np.sin(2 * np.pi * 1900 * t) * 0.5 + hp(noise(0.04), 3000) * 0.3) * np.exp(-t * 160) * gain


def stamp(gain=1.0):
    t = tvec(0.4)
    x = np.sin(2 * np.pi * 78 * t) * np.exp(-t * 11) + lp(noise(0.4), 2200) * np.exp(-t * 28) * 0.6
    return x * 0.8 * gain


def pop(gain=1.0):
    t = tvec(0.09)
    f = 380 + 600 * (t / t[-1])
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 35) * 0.45 * gain


def whoosh(d: float, f0: float, f1: float, gain=1.0):
    x = sweep_filter(noise(d), f0, f1, "low", 32)
    env = np.sin(np.pi * np.linspace(0, 1, len(x))) ** 1.5
    return x * env * 0.25 * gain


def reverse_riser(d=2.0, gain=1.0):
    x = sweep_filter(noise(d), 300, 9000, "low", 64)
    env = np.linspace(0, 1, len(x)) ** 3
    return x * env * 0.45 * gain


def glitch(gain=1.0):
    x = noise(0.25)
    x = np.round(x * 3) / 3  # crush
    x = np.repeat(x[::12], 12)[: int(0.25 * SR)]
    return bp(x, 400, 5000) * adsr(len(x), 0.002, 0.03) * 0.35 * gain


# ---------- placing ----------

def place(buf: np.ndarray, x: np.ndarray, t: float, gain=1.0, pan=0.0):
    i = int(round(t * SR))
    if i >= buf.shape[0]:
        return
    n = min(len(x), buf.shape[0] - i)
    left, right = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:i + n, 0] += x[:n] * gain * left * 1.414
    buf[i:i + n, 1] += x[:n] * gain * right * 1.414


def beats(start: float, end: float, step=BEAT):
    return np.arange(start, end - 1e-9, step)


def music() -> np.ndarray:
    m = np.zeros((N, 2))
    # tension: 16th hats swelling, a rising drone
    for i, t in enumerate(beats(0, 4.0, BEAT / 4)):
        place(m, hat(gain=0.4 + 0.6 * t / 4), t, pan=0.3 if i % 2 else -0.3)
    drone = saw(NOTE["A1"], 4.0, 12)
    drone = lp(drone, 900) * np.linspace(0.05, 0.5, len(drone)) * 0.5
    place(m, drone, 0.0)
    # intro + everything after: pad per bar
    for bar in range(2, 30):
        t0 = bar * BAR
        start = max(t0, 5.0)
        place(m, pad(chord_at(t0), t0 + BAR - start + 0.4, gain=0.8 if t0 < 8 else 1.0), start)
    # arp from the build on: 8th notes through chord tones
    for t in beats(8.0, 56.0, BEAT / 2):
        sec = section(t)
        _, v = CHORDS[chord_at(t)]
        k = int(round(t / (BEAT / 2)))
        f = NOTE[v[k % 4]] * (2 if sec in ("drop", "rise") and k % 8 >= 4 else 1)
        g = {"build": 0.55, "groove": 0.35, "night": 0.3, "drop": 0.4, "rise": 0.5}[sec]
        place(m, pluck(f, 0.4, g, bright=0.7), t, pan=0.25 if k % 2 else -0.25)
    for t in beats(54.0, 56.0, BEAT / 4):  # the rise doubles up
        _, v = CHORDS[chord_at(t)]
        place(m, pluck(NOTE[v[int(t * 8) % 4]] * 2, 0.25, 0.25 + 0.3 * (t - 54) / 2), t)
    # drums and bass
    for t in beats(14.0, 58.0):
        sec = section(t)
        beat_in_bar = int(round((t % BAR) / BEAT))
        if sec == "night":
            if beat_in_bar == 0:  # heartbeat: lub-dub once a bar
                place(m, kick(0.8), t)
                place(m, kick(0.55), t + 0.25)
        else:
            place(m, kick(1.0 if sec != "resolve" else 0.7), t)
            place(m, hat(gain=0.7), t + BEAT / 2, pan=0.2)
            if sec in ("drop", "rise") and beat_in_bar in (1, 3):
                place(m, clap(1.0), t)
            if sec == "drop":
                place(m, hat(True, 0.5), t + BEAT / 2, pan=-0.2)
        root, _ = CHORDS[chord_at(t)]
        if sec == "night":
            if beat_in_bar == 0:
                place(m, bass(root, BAR * 0.95, 0.5), t)
        else:
            for off in (0.0, BEAT / 2):
                place(m, bass(root, BEAT / 2 * 0.9, 0.55 if sec != "groove" else 0.45), t + off)
    for t in beats(54.0, 56.0, BEAT / 4):  # clap roll into the end
        place(m, clap(0.3 + 0.5 * (t - 54) / 2), t)
    # night: everything through a closing low-pass, snapping open at the drop
    a, b = int(28.0 * SR), int(CUES["drop"] * SR)
    for ch in range(2):
        m[a:b, ch] = sweep_filter(m[a:b, ch], 5000, 320, "low", 96)
    # hard stop for the silence
    s0, s1 = int(4.0 * SR), int(5.0 * SR)
    fade = int(0.004 * SR)
    m[s0 - fade:s0] *= np.linspace(1, 0, fade)[:, None]
    m[s0:s1] = 0
    # final chord rings out
    for n in ("C3", "E4", "G4", "C5"):
        place(m, chime(NOTE[n], 2.0, 0.5), CUES["final_chord"])
    tail = int(1.6 * SR)
    m[-tail:] *= np.linspace(1, 0, tail)[:, None] ** 2
    return m


def sfx() -> np.ndarray:
    s = np.zeros((N, 2))
    c = CUES
    for i, t in enumerate(c["flood_notices"]):
        place(s, buzz(0.5 + 0.5 * i / len(c["flood_notices"])), t, pan=(-0.6, 0.6)[i % 2])
    place(s, reverse_riser(2.0), c["reverse_riser_end"] - 2.0)
    place(s, chime(NOTE["E5"], 1.8, 0.7), c["watch_in"])
    place(s, sub_hit(0.45), c["title"])
    for t, n in zip(c["city_bars"], ("A4", "C5", "D5", "E5", "G5")):
        place(s, pluck(NOTE[n], 0.6, 0.8, bright=1.5), t)
    for t in c["marker_rows"]:
        place(s, tick(1800, 0.6), t)
    place(s, pluck(NOTE["A5"], 0.25, 0.5, 2) + 0, c["helsinki_alarm"])
    place(s, pluck(NOTE["A5"], 0.25, 0.5, 2), c["helsinki_alarm"] + 0.125)
    place(s, pluck(NOTE["A3"], 0.8, 0.6, 0.8), c["delhi_calm"])
    place(s, whoosh(0.5, 600, 6000, 0.8), c["grid_draw"])
    for t in c["grid_quiet_cells"]:
        place(s, tick(900, 0.8), t)
    place(s, sub_hit(0.9), c["tell_them"])
    place(s, stamp(0.8), c["tell_them"])
    for i, t in enumerate(c["story_ticks"]):
        place(s, tick(1200, 0.5), t, pan=(-0.3, 0.3)[i % 2])
    place(s, whoosh(0.5, 4000, 400, 0.6), c["story_grey"] - 0.25)
    for t, n in zip(c["story_messages"], ("C5", "E5", "G5")):
        place(s, pluck(NOTE[n], 0.6, 0.9, 1.6), t)
    place(s, whoosh(0.5, 800, 5000, 0.5), c["story_bracket"] - 0.25)
    place(s, tap(0.8), c["chip_tap"])
    for t in c["night_ticks"]:
        place(s, lp(tick(1500, 0.6), 1800), t)
    place(s, whoosh(0.6, 3000, 300, 0.8), c["held"] - 0.1)
    place(s, lp(chime(NOTE["A4"], 1.2, 0.4), 1400), c["held"])
    for t in c["same_story"]:
        place(s, lp(tick(1100, 0.7), 1500), t)
    place(s, haptic(1.0), c["drop"])
    place(s, sub_hit(1.0), c["drop"])
    place(s, crash(1.0), c["drop"])
    place(s, buzz(0.6), c["drop"] + 0.05)
    place(s, tap(0.8), c["why_tap"])
    for i, t in enumerate(c["why_layers"]):
        place(s, tick(1600 + 300 * i, 0.8), t)
    for t in c["proof_cards"]:
        place(s, stamp(0.8), t)
        place(s, whoosh(0.3, 800, 6000, 0.4), t - 0.3)
    place(s, glitch(1.0), c["glitch_stamp"] - 0.25)
    place(s, stamp(0.7), c["glitch_stamp"])
    for i in range(16):
        place(s, tick((2200, 1800, 2000, 1600)[i % 4], 0.45), c["log_rows_start"] + i * c["log_rows_step"],
              pan=(-0.4, 0.4)[i % 2])
    place(s, whoosh(0.3, 500, 7000, 0.6), c["log_push"] - 0.05)
    for t in c["log_trace_lines"]:
        place(s, tick(2400, 0.5), t)
    t0, t1 = c["layer_tiles"]
    for i, t in enumerate(np.linspace(t0, t1, 18, endpoint=False)):
        place(s, tick(1400 + 60 * i, 0.3), t)
    place(s, pluck(NOTE["E4"], 0.8, 0.5, 0.8), c["stubs_amber"])
    for t in c["future_icons"]:
        place(s, pop(0.9), t)
    for t in c["end_lines"]:
        place(s, sub_hit(0.35, 1.0), t)
    place(s, chime(NOTE["G5"], 2.0, 0.6), c["end_repo"])
    return s


def write_wav(path: Path, x: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    x = np.clip(x, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def read_wav(path: Path) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype="<f4").reshape(-1, 2).astype(float)


def measure(path: Path) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBTP), from FFmpeg's EBU R128 meter."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    summary = err[err.rindex("Summary:"):]
    i = float(summary.split("I:")[1].split("LUFS")[0])
    tp = float(summary.split("Peak:")[1].split("dBFS")[0])
    return i, tp


def limit(x: np.ndarray, ceiling_db: float = -2.2, release_s: float = 0.08) -> np.ndarray:
    """Look-ahead peak limiter: never lets a sample past the ceiling, recovers smoothly."""
    from scipy.ndimage import minimum_filter1d
    c = 10 ** (ceiling_db / 20)
    peak = np.abs(x).max(axis=1)
    g = np.minimum(1.0, c / np.maximum(peak, 1e-9))
    look = int(0.005 * SR)
    g = minimum_filter1d(g, size=2 * look + 1)  # start reducing 5 ms before the peak
    a = np.exp(-1 / (release_s * SR))
    g = signal.lfilter([1 - a], [1, -a], g - 1) + 1  # smooth recovery
    g = np.minimum(g, minimum_filter1d(np.minimum(1.0, c / np.maximum(peak, 1e-9)), size=2 * look + 1))
    return x * g[:, None]


def loudnorm(src: Path, dst: Path, target: float = -14.0) -> dict:
    """Gain to -14 LUFS, limit peaks, encode AAC; linear, so the silence stays silent."""
    i, _ = measure(src)
    x = read_wav(src) * 10 ** ((target - i) / 20)
    x = limit(x)
    tmp = src.with_name(src.stem + "-norm.wav")
    write_wav(tmp, x)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-c:a", "aac", "-b:a", "256k", str(dst)], check=True)
    out_i, out_tp = measure(dst)
    return {"output_i": out_i, "output_tp": out_tp, "normalization_type": "gain + look-ahead limiter"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vo", type=Path, help="optional voice-over WAV, placed from 0 s; music is ducked under it")
    ap.add_argument("--out", default="mix", help="output name, e.g. mix or mix-vo")
    args = ap.parse_args()

    m, s = music(), sfx()
    write_wav(VIDEO / "audio" / "music.wav", m * 0.5)
    write_wav(VIDEO / "audio" / "sfx.wav", s * 0.5)
    mix = m * 0.55 + s * 0.6
    if args.vo:
        vo = read_wav(args.vo)[:N]
        env = np.abs(vo).max(axis=1)
        env = signal.sosfiltfilt(signal.butter(1, 4, "low", fs=SR, output="sos"), env)
        duck = 1 - 0.6 * np.clip(env / (env.max() * 0.25 + 1e-9), 0, 1)  # about -8 dB under speech
        mix[: len(vo)] *= duck[:, None]
        mix[: len(vo)] += vo * 1.1
    peak = np.abs(mix).max()
    mix = mix / peak * 0.89
    raw = VIDEO / "audio" / f"{args.out}.wav"
    write_wav(raw, mix)
    stats = loudnorm(raw, VIDEO / "composition" / "assets" / "audio" / f"{args.out}.m4a")
    print(json.dumps({k: stats[k] for k in ("output_i", "output_tp", "normalization_type")}))


if __name__ == "__main__":
    main()
