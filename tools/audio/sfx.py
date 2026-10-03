"""Kasumi UI sound effects, Japanese set: koto, wood (hyoshigi, mokugyo,
shishi-odoshi), the rin bowl, the furin wind chime, kotsuzumi and the
suikinkutsu water cave. Yo scale on D (D E G A B), the same key as the
banner jingle. Everything is synthesised here; nothing is sampled.

    python tools/audio/sfx.py resources/sfx

Writes one stereo 32 kHz WAV per effect, plus _all-preview.wav with every
effect in a row for listening. The sounds heard most (move, select, back)
are the simplest and quietest; only rare moments get a bigger sound.
"""
import math, os, random, struct, sys, wave

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
_argv = sys.argv
sys.argv = [sys.argv[0], OUT]
exec(open(os.path.join(HERE, "jingles.py"), encoding="utf-8").read().split("# Yo scale on D")[0])
sys.argv = _argv

# Yo scale on D.
D, E_, G, A, B = 62, 64, 67, 69, 71


def modes(freq, dur, ratios, amps, decays, attack=0.0008):
    """Modal synthesis: a struck object as a few ringing partials."""
    out = []
    for i in range(int(dur * RATE)):
        t = i / RATE
        env = min(1.0, t / attack)
        out.append(env * sum(a * math.exp(-t * d) * math.sin(TAU * freq * r * t)
                             for r, a, d in zip(ratios, amps, decays)))
    return out


def noise_hit(dur, color, decay, seed):
    """The 'tok' of a strike: a burst of noise, darker for lower `color`."""
    rnd = random.Random(seed)
    out, lp = [], 0.0
    for i in range(int(dur * RATE)):
        lp += color * (rnd.uniform(-1, 1) - lp)
        out.append(lp * math.exp(-i / RATE * decay))
    return out


def wood(freq, dur=0.12, seed=1, bright=0.5):
    """Small wooden block / bamboo: hollow, quick, warm."""
    body = modes(freq, dur, (1.0, 2.32, 4.1), (1.0, 0.35 * bright, 0.12 * bright), (55, 90, 140))
    hit = noise_hit(dur, 0.25 + 0.4 * bright, 300, seed)
    return [b + 0.35 * h for b, h in zip(body, hit)]


def hyoshigi(freq=1750, seed=3):
    """Wooden clappers: a crisp, dry 'kachi'."""
    body = modes(freq, 0.09, (1.0, 2.57, 4.3), (1.0, 0.5, 0.25), (70, 110, 160))
    hit = noise_hit(0.09, 0.8, 500, seed)
    return [b + 0.6 * h for b, h in zip(body, hit)]


def rin(freq, dur, gain_hi=1.0):
    """Rin (temple bowl): inharmonic partials in slow-beating pairs."""
    parts = ((1.0, 1.0, 0.9), (2.71, 0.45 * gain_hi, 1.6), (5.15, 0.2 * gain_hi, 2.6), (8.6, 0.08 * gain_hi, 4.0))
    out = []
    for i in range(int(dur * RATE)):
        t = i / RATE
        env = min(1.0, t / 0.002)
        v = 0.0
        for r, a, d in parts:
            f = freq * r
            v += a * math.exp(-t * d) * 0.5 * (math.sin(TAU * f * t) + math.sin(TAU * (f + 0.9) * t))
        out.append(v * env)
    return out


def furin(freq, dur, seed=1, strikes=3):
    """Furin (glass wind chime): a bright bell struck a few times by its clapper."""
    rnd = random.Random(seed)
    out = [0.0] * int(dur * RATE)
    at = 0.0
    for k in range(strikes):
        tone = modes(freq * rnd.uniform(0.998, 1.002), dur - at, (1.0, 2.76, 5.4),
                     (1.0, 0.35, 0.12), (5.5, 9, 14))
        g = 0.9 ** k * (1.0 if k == 0 else rnd.uniform(0.35, 0.6))
        i0 = int(at * RATE)
        for i, v in enumerate(tone):
            if i0 + i < len(out):
                out[i0 + i] += v * g
        at += rnd.uniform(0.07, 0.16)
    return out


def tsuzumi(freq, dur=0.3, seed=2):
    """Kotsuzumi 'pon': a hand drum whose pitch sags as it rings."""
    out, ph = [], 0.0
    hit = noise_hit(dur, 0.2, 120, seed)
    for i in range(int(dur * RATE)):
        t = i / RATE
        f = freq * (1 + 0.45 * math.exp(-t * 25))
        ph += TAU * f / RATE
        out.append(math.sin(ph) * min(1.0, t / 0.002) * math.exp(-t * 14) + 0.3 * hit[i])
    return out


def drop(freq, dur=0.1):
    """A water drop: a sine that leaps up in pitch."""
    out, ph = [], 0.0
    for i in range(int(dur * RATE)):
        t = i / RATE
        f = freq * (1 + 1.4 * (1 - math.exp(-t * 45)))
        ph += TAU * f / RATE
        out.append(math.sin(ph) * min(1.0, t / 0.0015) * math.exp(-t * 40))
    return out


def suikinkutsu(freq, dur):
    """Water dripping into a buried jar: a drop, then a soft metallic ring."""
    out = [v * 0.6 for v in drop(freq * 1.5, 0.08)] + [0.0] * int(dur * RATE)
    ring = modes(freq, dur, (1.0, 2.24, 3.9), (1.0, 0.3, 0.1), (6, 10, 16), attack=0.004)
    i0 = int(0.012 * RATE)
    for i, v in enumerate(ring):
        if i0 + i < len(out):
            out[i0 + i] += v * 0.8
    return out[:int(dur * RATE)]


def breath(dur, lo, hi, tone_hz, seed=4):
    """Shakuhachi breath / a folding fan: soft air with a hint of pitch."""
    rnd = random.Random(seed)
    out, s1, s2 = [], 0.0, 0.0
    n = int(dur * RATE)
    for i in range(n):
        x = i / n
        fc = lo * (hi / lo) ** x
        f = 2 * math.sin(math.pi * fc / RATE)
        s2 += f * s1
        s1 += f * (rnd.uniform(-1, 1) - s2 - 0.5 * s1)
        env = math.sin(math.pi * x) ** 1.6
        out.append((s1 + 0.15 * math.sin(TAU * tone_hz * i / RATE)) * env)
    return out


EFFECTS = {}


def effect(name, peak_db, dur, room=0.15, cave=False):
    """Render: a small wooden room, or a long cave for the water sounds."""
    def wrap(fn):
        m = Mix(dur)
        fn(m)
        rooms = (0.0389, 0.0453, 0.0511, 0.0577) if cave else (0.0117, 0.0149, 0.0171, 0.0203)
        fb = 0.82 if cave else 0.62
        left = reverb(m.l, rooms, feedback=fb, mix=room, predelay=0.01 if cave else 0.003)
        right = reverb(m.r, [d * 1.07 for d in rooms], feedback=fb, mix=room, predelay=0.01 if cave else 0.003)
        fade = int(0.02 * RATE)
        for i in range(fade):
            left[-1 - i] *= i / fade
            right[-1 - i] *= i / fade
        peak = max(max(map(abs, left)), max(map(abs, right))) or 1
        gain = 10 ** (peak_db / 20) / peak
        EFFECTS[name] = ([v * gain for v in left], [v * gain for v in right])
        return fn
    return wrap


# Frequent: one simple, quiet sound each.
@effect("move", -21, 0.07, room=0.06)
def _(m):
    m.add(0, wood(hz(A + 24), 0.06, seed=1, bright=0.6), 1.0, 0.0)


@effect("bump", -19, 0.14, room=0.06)
def _(m):
    m.add(0, wood(hz(D), 0.13, seed=2, bright=0.2), 1.0, 0.0)  # shishi-odoshi 'kon'


@effect("select", -13, 0.5, room=0.12)
def _(m):
    m.add(0, koto(hz(D + 24), 0.48, bright=0.9), 0.8, 0.05)


@effect("back", -16, 0.45, room=0.12)
def _(m):
    m.add(0.00, koto(hz(A + 12), 0.4, bright=0.6), 0.6, 0.1)
    m.add(0.06, koto(hz(D + 12), 0.38, bright=0.5), 0.55, -0.1)


@effect("toggle_on", -14, 0.45, room=0.12)
def _(m):
    m.add(0.00, koto(hz(D + 12), 0.4, bright=0.8), 0.55, -0.15)
    m.add(0.07, koto(hz(A + 12), 0.38, bright=0.9), 0.65, 0.15)


@effect("toggle_off", -16, 0.42, room=0.12)
def _(m):
    m.add(0.00, koto(hz(A + 12), 0.36, bright=0.6), 0.55, 0.15)
    m.add(0.07, koto(hz(D + 12), 0.35, bright=0.5), 0.55, -0.15)


# Occasional: a little more character.
@effect("open", -14, 0.9, cave=True, room=0.3)
def _(m):
    m.add(0.0, suikinkutsu(hz(A + 12), 0.85), 1.0, -0.1)
    m.add(0.09, drop(hz(E_ + 24), 0.08), 0.25, 0.35)


@effect("close", -16, 0.8, cave=True, room=0.28)
def _(m):
    m.add(0.0, suikinkutsu(hz(D + 12), 0.75), 1.0, 0.1)


@effect("tab", -16, 0.25, room=0.1)
def _(m):
    m.add(0.0, breath(0.2, 700, 2600, hz(A + 12)), 0.9, 0.0)  # a fan flicked open


@effect("notice", -14, 1.3, room=0.2)
def _(m):
    m.add(0.0, furin(hz(B + 24), 1.25, seed=5, strikes=3), 0.9, 0.2)


@effect("error", -15, 0.5, room=0.1)
def _(m):
    m.add(0.00, tsuzumi(hz(A - 12), 0.22, seed=3), 0.85, -0.1)
    m.add(0.14, tsuzumi(hz(G - 12), 0.3, seed=6), 0.8, 0.1)


@effect("screenshot", -12, 0.3, room=0.1)
def _(m):
    m.add(0.000, hyoshigi(1750, seed=3), 0.9, -0.15)
    m.add(0.055, hyoshigi(1690, seed=7), 0.8, 0.15)


# Rare: your game is ready. Rin bowl, a koto phrase up the yo scale, water.
@effect("queue_ready", -10, 2.6, room=0.22)
def _(m):
    m.add(0.0, rin(hz(D + 12), 2.5, gain_hi=0.8), 0.7, 0.0)
    for k, (n, pan) in enumerate(((D + 12, -0.4), (E_ + 12, -0.2), (A + 12, 0.0), (B + 12, 0.2), (D + 24, 0.35))):
        m.add(0.35 + k * 0.11, koto(hz(n), 1.6, bright=0.8), 0.45, pan)
    m.add(1.05, suikinkutsu(hz(A + 24), 1.2), 0.3, 0.4)


def write(path, left, right):
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<hh", int(max(-1, min(1, a)) * 32767), int(max(-1, min(1, b)) * 32767))
                               for a, b in zip(left, right)))


ORDER = ("move", "bump", "select", "back", "open", "close", "toggle_on", "toggle_off",
         "tab", "notice", "error", "screenshot", "queue_ready")
pl, pr = [], []
gap = [0.0] * int(0.6 * RATE)
for name in ORDER:
    left, right = EFFECTS[name]
    write(os.path.join(OUT, name + ".wav"), left, right)
    pl += left + gap
    pr += right + gap
    print(f"{name:12s} {len(left) / RATE:.2f} s")
write(os.path.join(OUT, "_all-preview.wav"), pl, pr)
