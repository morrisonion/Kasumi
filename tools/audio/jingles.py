"""Kasumi banner jingles, round two: Japanese (yo scale, koto) meets Frutiger
Aero (glass, water, airy shimmer). Pure Python, stereo, 32 kHz."""
import math, os, random, struct, sys, wave

RATE = 32000
OUT = sys.argv[1]
TAU = 2 * math.pi


def hz(n):
    return 440.0 * 2 ** ((n - 69) / 12)


class Mix:
    def __init__(self, sec):
        self.n = int(sec * RATE)
        self.l = [0.0] * self.n
        self.r = [0.0] * self.n

    def add(self, at, sig, gain=1.0, pan=0.0):
        # equal-power pan, -1 left .. 1 right
        a = (pan + 1) * math.pi / 4
        gl, gr = math.cos(a) * gain, math.sin(a) * gain
        i0 = int(at * RATE)
        for i, v in enumerate(sig):
            j = i0 + i
            if j >= self.n:
                break
            self.l[j] += v * gl
            self.r[j] += v * gr


def glass(freq, dur, ratio=3.0, index=2.2, decay=2.6):
    """FM glass-bell: bright mallet attack that melts into a pure tone."""
    out = []
    for i in range(int(dur * RATE)):
        t = i / RATE
        idx = index * math.exp(-t * 9)
        env = min(1.0, t / 0.003) * math.exp(-t * decay)
        body = math.sin(TAU * freq * t + idx * math.sin(TAU * freq * ratio * t))
        air = 0.18 * math.sin(TAU * freq * 2.0 * t) * math.exp(-t * decay * 1.6)
        out.append((body + air) * env)
    return out


def koto(freq, dur, bright=0.5):
    """Karplus-Strong pluck with a soft, rounded attack."""
    period = max(2, int(RATE / freq))
    rnd = random.Random(int(freq))
    line = [rnd.uniform(-1, 1) for _ in range(period)]
    for _ in range(3 - int(bright * 2)):
        line = [(line[i] + line[i - 1]) * 0.5 for i in range(period)]
    out, damp = [], 0.9965
    for i in range(int(dur * RATE)):
        j = i % period
        v = line[j]
        line[j] = damp * 0.5 * (line[j] + line[(j + 1) % period])
        out.append(v * min(1.0, i / 40))
    return out


def droplet(f0, dur=0.16):
    """Water drop: a sine whose pitch leaps up as it rings out."""
    out, ph = [], 0.0
    for i in range(int(dur * RATE)):
        t = i / RATE
        f = f0 * (1 + 1.8 * (1 - math.exp(-t * 35)))
        ph += TAU * f / RATE
        out.append(math.sin(ph) * math.exp(-t * 30) * min(1, t / 0.0015))
    return out


def shimmer(freqs, dur, attack=0.6, release=1.2):
    """Airy chorused pad: slightly detuned sines with a breath of 2nd harmonic."""
    out = []
    det = (-0.004, 0.0, 0.0045)
    for i in range(int(dur * RATE)):
        t = i / RATE
        env = min(1.0, t / attack) * (1.0 if t < dur - release else max(0.0, (dur - t) / release))
        v = 0.0
        for k, f in enumerate(freqs):
            for d in det:
                v += math.sin(TAU * f * (1 + d) * t + k * 1.3)
            v += 0.25 * math.sin(TAU * f * 2.002 * t)
        out.append(v * env / (len(freqs) * 3.3))
    return out


def chimes(mix, start, span, notes, count, gain, seed):
    rnd = random.Random(seed)
    for _ in range(count):
        at = start + rnd.random() * span
        n = rnd.choice(notes)
        mix.add(at, glass(hz(n), 1.2, ratio=4.0, index=1.2, decay=4.5),
                gain * rnd.uniform(0.5, 1.0), rnd.uniform(-0.8, 0.8))


def reverb(dry, delays, feedback=0.8, mix=0.35, predelay=0.018):
    pd = int(predelay * RATE)
    src = [0.0] * pd + dry[:len(dry) - pd]
    combs = []
    for d in delays:
        n, y, lp = int(d * RATE), [0.0] * len(src), 0.0
        for i, x in enumerate(src):
            fb = y[i - n] if i >= n else 0.0
            lp = 0.55 * lp + 0.45 * fb
            y[i] = x + feedback * lp
        combs.append(y)
    wet = [sum(c[i] for c in combs) / len(combs) for i in range(len(src))]
    for d in (0.0051, 0.0017):
        n, g, y = int(d * RATE), 0.7, [0.0] * len(wet)
        for i, x in enumerate(wet):
            y[i] = -g * x + (wet[i - n] if i >= n else 0.0) + g * (y[i - n] if i >= n else 0.0)
        wet = y
    return [(1 - mix) * a + mix * b for a, b in zip(dry, wet)]


def finish(name, m):
    base = (0.0297, 0.0371, 0.0411, 0.0437)
    left = reverb(m.l, base)
    right = reverb(m.r, [d * 1.083 for d in base])
    n, fade = m.n, int(0.4 * RATE)
    peak = max(max(map(abs, left)), max(map(abs, right))) or 1
    gain = 0.7 / peak
    with wave.open(os.path.join(OUT, name), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE)
        out = bytearray()
        for i in range(n):
            f = 1.0 if i < n - fade else ((n - i) / fade) ** 1.5
            for v in (left[i], right[i]):
                v = math.tanh(v * gain * f * 1.2) / math.tanh(1.2)  # gentle soft-clip
                out += struct.pack("<h", int(max(-1, min(1, v)) * 32767))
        w.writeframes(bytes(out))
    print("wrote", name, round(n / RATE, 2), "s")


# Yo scale on D (D E G A B): bright, folk-Japanese, and it sits happily
# over a lush major-9 chord, which is where the Aero sheen comes from.
D4, E4, G4, A4, B4 = 62, 64, 67, 69, 71

# 1. Kasumi Bloom: a water drop, koto root, glass arpeggio up the yo scale,
#    a Dmaj9 shimmer swells underneath, wind chimes sparkle out.
m = Mix(2.9)
m.add(0.00, droplet(hz(86)), 0.45, -0.3)
m.add(0.06, koto(hz(D4 - 12), 2.8), 0.5, -0.15)
for k, (n, pan) in enumerate([(D4 + 12, -0.5), (E4 + 12, -0.2), (G4 + 12, 0.1), (A4 + 12, 0.35), (D4 + 24, 0.0)]):
    m.add(0.12 + k * 0.13, glass(hz(n), 2.6 - k * 0.13), 0.42 if k < 4 else 0.55, pan)
m.add(0.30, shimmer([hz(n) for n in (D4 - 12, A4 - 12, E4, 66, B4)], 2.6), 0.55)  # D A E F# B: Dmaj9
chimes(m, 1.05, 0.9, [D4 + 24, E4 + 24, A4 + 24, B4 + 24], 6, 0.12, 3)
finish("kasumi-bloom.wav", m)

# 2. Sky Koto: koto carries the melody, bubbles rise beneath it, then a
#    glass chord opens like sky through mist.
m = Mix(2.9)
for k, (n, at, pan) in enumerate([(A4, 0.00, -0.3), (D4 + 12, 0.16, 0.0), (E4 + 12, 0.32, 0.25), (A4 + 12, 0.56, 0.0)]):
    m.add(at, koto(hz(n), 2.6, bright=0.8), 0.55, pan)
for k, at in enumerate([0.10, 0.22, 0.31, 0.45]):
    m.add(at, droplet(hz(79 + 2 * k)), 0.25, random.Random(k).uniform(-0.7, 0.7))
for n, pan in [(D4 + 12, -0.4), (G4 + 12, -0.1), (B4 + 12, 0.2), (E4 + 24, 0.45)]:
    m.add(0.62, glass(hz(n), 2.2, ratio=2.0, index=1.5, decay=1.8), 0.28, pan)
m.add(0.55, shimmer([hz(n) for n in (G4 - 12, D4, B4, E4 + 12)], 2.3, attack=0.4), 0.45)
chimes(m, 1.3, 0.8, [B4 + 24, D4 + 36, E4 + 36], 4, 0.1, 9)
finish("kasumi-sky-koto.wav", m)

# 3. Glass Garden: call and answer on glass, a single koto accent,
#    shorter and brighter -- closest to a console boot sound.
m = Mix(2.4)
m.add(0.00, droplet(hz(84)), 0.4, 0.3)
for n, at, pan in [(G4 + 12, 0.04, -0.4), (A4 + 12, 0.16, -0.1), (D4 + 24, 0.28, 0.2)]:
    m.add(at, glass(hz(n), 2.2), 0.45, pan)
m.add(0.52, koto(hz(B4), 1.9, bright=0.9), 0.4, 0.4)
for n, at, pan in [(B4 + 12, 0.60, 0.3), (E4 + 24, 0.70, 0.0)]:
    m.add(at, glass(hz(n), 1.8, ratio=2.0), 0.5, pan)
m.add(0.58, shimmer([hz(n) for n in (G4 - 12, D4, A4, B4)], 1.8, attack=0.25, release=1.0), 0.5)
chimes(m, 0.95, 0.6, [D4 + 36, E4 + 36, G4 + 36], 4, 0.08, 21)
finish("kasumi-glass-garden.wav", m)
