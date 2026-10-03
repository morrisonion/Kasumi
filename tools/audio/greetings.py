"""In-app voice cues for Kasumi: おかえり〜 (app opens) and いってらっしゃい
(game starting), each wrapped in the same glass / water / mist palette as the
banner jingles."""
import math, os, random, struct, sys, wave

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "jingles.py"), encoding="utf-8").read()
OUT = sys.argv[2]
sys_argv_backup = sys.argv
sys.argv = [sys.argv[0], OUT]
exec(src.split("# Yo scale on D")[0])  # glass, koto, droplet, shimmer, chimes, reverb, Mix, hz
sys.argv = sys_argv_backup
VOICES = sys.argv[1]

D4, E4, G4, A4, B4 = 62, 64, 67, 69, 71


def read_voice(path):
    w = wave.open(path)
    p = w.getparams()
    d = w.readframes(p.nframes)
    x = [v / 32768 for v in struct.unpack("<%dh" % (len(d) // 2), d)]
    th = 0.01
    a = next(i for i, v in enumerate(x) if abs(v) > th)
    b = len(x) - next(i for i, v in enumerate(reversed(x)) if abs(v) > th)
    x = x[max(0, a - int(0.02 * p.framerate)):b + int(0.06 * p.framerate)]
    # Catmull-Rom resample to 32 kHz
    n = int(len(x) * RATE / p.framerate)
    out = []
    for i in range(n):
        pos = i * p.framerate / RATE
        k, t = int(pos), pos - int(pos)
        q = [x[min(max(k + j, 0), len(x) - 1)] for j in (-1, 0, 1, 2)]
        out.append(0.5 * (2 * q[1] + (-q[0] + q[2]) * t + (2 * q[0] - 5 * q[1] + 4 * q[2] - q[3]) * t * t
                          + (-q[0] + 3 * q[1] - 3 * q[2] + q[3]) * t ** 3))
    # high-pass the rumble
    a_ = 1 / (1 + 2 * math.pi * 110 / RATE)
    y, px, py = [], 0.0, 0.0
    for v in out:
        py = a_ * (py + v - px); px = v; y.append(py)
    peak = max(map(abs, y))
    return [v / peak for v in y]


def mist(dur, lo, hi, attack, release, seed=1):
    """Breathy filtered noise -- the 'kasumi' haze. Cutoff glides lo -> hi."""
    rnd = random.Random(seed)
    out, s1, s2 = [], 0.0, 0.0
    n = int(dur * RATE)
    for i in range(n):
        t = i / RATE
        fc = lo * (hi / lo) ** (i / n)
        f = 2 * math.sin(math.pi * fc / RATE)
        x = rnd.uniform(-1, 1)
        s2 += f * s1          # state-variable band-pass
        s1 += f * (x - s2 - 0.5 * s1)
        env = min(1.0, t / attack) * min(1.0, max(0.0, (dur - t) / release))
        out.append(s1 * env)
    return out


def place_voice(m, at, voice, gain):
    m.add(at, voice, gain, 0.0)


def render(name, m, voice_at, voice, vgain, dur):
    """Mix music (reverbed) + voice (light reverb), duck music under the word."""
    base = (0.0297, 0.0371, 0.0411, 0.0437)
    ml = reverb(m.l, base)
    mr = reverb(m.r, [d * 1.083 for d in base])
    vl_wet = reverb(voice + [0.0] * int(0.6 * RATE), base, mix=1.0)
    vr_wet = reverb(voice + [0.0] * int(0.6 * RATE), [d * 1.083 for d in base], mix=1.0)
    n = m.n
    s0, s1 = int(voice_at * RATE), int(voice_at * RATE) + len(voice)
    ramp = int(0.12 * RATE)
    mpeak = max(max(map(abs, ml)), max(map(abs, mr)))
    out = []
    for i in range(n):
        if i < s0 - ramp or i > s1 + 3 * ramp:
            g = 1.0
        elif i < s0:
            g = 1.0 - 0.45 * (i - (s0 - ramp)) / ramp
        elif i <= s1:
            g = 0.55
        else:
            g = 0.55 + 0.45 * (i - s1) / (3 * ramp)
        l, r = ml[i] * g, mr[i] * g
        j = i - s0
        if 0 <= j < len(voice):
            l += voice[j] * vgain * mpeak; r += voice[j] * vgain * mpeak
        if 0 <= j < len(vl_wet):
            l += vl_wet[j] * vgain * mpeak * 0.25; r += vr_wet[j] * vgain * mpeak * 0.25
        out.append((l, r))
    peak = max(max(abs(a), abs(b)) for a, b in out)
    gain = 0.75 / peak
    fade = int(0.4 * RATE)
    with wave.open(os.path.join(OUT, name), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE)
        b = bytearray()
        for i, (l, r) in enumerate(out):
            f = 1.0 if i < n - fade else ((n - i) / fade) ** 1.5
            for v in (l, r):
                v = math.tanh(v * gain * f * 1.2) / math.tanh(1.2)
                b += struct.pack("<h", int(max(-1, min(1, v)) * 32767))
        w.writeframes(bytes(b))
    print("wrote", name, f"{dur:.2f} s, voice at {voice_at:.2f} s")


okaeri = read_voice(os.path.join(VOICES, "okaeri-tsumugi.wav"))
itte = read_voice(os.path.join(VOICES, "itterasshai-tsumugi.wav"))

# おかえり〜 -- coming home: mist rolls in, a warm Dmaj9 opens, a drop of
# water, the greeting, then glass settles down the scale like a sigh.
DUR = 3.6
m = Mix(DUR)
m.add(0.00, mist(DUR, 500, 1400, 0.8, 1.6, seed=2), 0.10, -0.4)
m.add(0.00, mist(DUR, 650, 1800, 1.0, 1.6, seed=5), 0.10, 0.4)
m.add(0.05, shimmer([hz(n) for n in (D4 - 12, A4 - 12, E4, 66, B4)], DUR - 0.05, attack=0.9, release=1.6), 0.55)
m.add(0.30, droplet(hz(84)), 0.35, -0.35)
m.add(0.42, droplet(hz(88)), 0.22, 0.4)
for k, (n, pan) in enumerate([(A4 + 12, 0.35), (G4 + 12, 0.1), (E4 + 12, -0.15), (D4 + 12, -0.35)]):
    m.add(1.35 + k * 0.17, glass(hz(n), 2.0, decay=2.2), 0.32, pan)
m.add(1.35, koto(hz(D4 - 12), 2.2), 0.35, -0.1)
chimes(m, 2.2, 0.8, [D4 + 24, E4 + 24, A4 + 24], 4, 0.08, 31)
render("okaeri.wav", m, 0.55, okaeri, 0.9, DUR)

# いってらっしゃい -- off you go: the send-off, then bubbles rise and the
# mist sweeps upward into a bright glass run, like heading into the sky.
DUR = 3.2
m = Mix(DUR)
m.add(0.00, mist(DUR, 400, 900, 0.5, 1.2, seed=7), 0.08, -0.3)
m.add(0.00, shimmer([hz(n) for n in (G4 - 12, D4, B4, E4 + 12)], DUR, attack=0.5, release=1.4), 0.45)
m.add(1.05, mist(1.6, 600, 5200, 0.7, 0.6, seed=11), 0.22, 0.0)   # upward whoosh
for k, at in enumerate([1.10, 1.20, 1.28, 1.38, 1.45]):
    m.add(at, droplet(hz(79 + 2 * k)), 0.22, random.Random(40 + k).uniform(-0.7, 0.7))
for k, (n, pan) in enumerate([(D4 + 12, -0.45), (E4 + 12, -0.2), (G4 + 12, 0.05), (A4 + 12, 0.25), (B4 + 12, 0.4), (D4 + 24, 0.0)]):
    m.add(1.45 + k * 0.09, glass(hz(n), 1.7 - k * 0.05, decay=2.6), 0.33 if k < 5 else 0.45, pan)
m.add(1.45, koto(hz(G4 - 12), 1.7, bright=0.8), 0.3, 0.2)
chimes(m, 2.05, 0.6, [D4 + 36, E4 + 36, B4 + 24], 4, 0.07, 53)
render("itterasshai.wav", m, 0.10, itte, 0.95, DUR)
