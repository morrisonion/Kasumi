"""Lay the VOICEVOX "かすみ" over the end of each banner jingle."""
import math, struct, sys, wave

RATE = 32000
voice_path, folder = sys.argv[1], sys.argv[2]


def read(path):
    w = wave.open(path)
    p = w.getparams()
    d = w.readframes(p.nframes)
    s = struct.unpack("<%dh" % (len(d) // 2), d)
    ch = p.nchannels
    return p.framerate, [[s[i + c] / 32768 for i in range(0, len(s), ch)] for c in range(ch)]


def resample(x, src, dst):
    """Catmull-Rom cubic resampling, plenty for a short voice clip."""
    n = int(len(x) * dst / src)
    out = []
    for i in range(n):
        pos = i * src / dst
        k = int(pos)
        t = pos - k
        p = [x[min(max(k + j, 0), len(x) - 1)] for j in (-1, 0, 1, 2)]
        out.append(0.5 * (2 * p[1] + (-p[0] + p[2]) * t + (2 * p[0] - 5 * p[1] + 4 * p[2] - p[3]) * t * t
                          + (-p[0] + 3 * p[1] - 3 * p[2] + p[3]) * t ** 3))
    return out


def highpass(x, fc=110):
    a = 1 / (1 + 2 * math.pi * fc / RATE)
    y, prev_x, prev_y = [], 0.0, 0.0
    for v in x:
        prev_y = a * (prev_y + v - prev_x)
        prev_x = v
        y.append(prev_y)
    return y


def reverb(dry, delays, feedback=0.78, predelay=0.02):
    pd = int(predelay * RATE)
    src = [0.0] * pd + dry
    combs = []
    for d in delays:
        n, y, lp = int(d * RATE), [0.0] * len(src), 0.0
        for i, x in enumerate(src):
            lp = 0.55 * lp + 0.45 * (y[i - n] if i >= n else 0.0)
            y[i] = x + feedback * lp
        combs.append(y)
    wet = [sum(c[i] for c in combs) / len(combs) for i in range(len(src))]
    for d in (0.0051, 0.0017):
        n, g, y = int(d * RATE), 0.7, [0.0] * len(wet)
        for i, x in enumerate(wet):
            y[i] = -g * x + (wet[i - n] if i >= n else 0.0) + g * (y[i - n] if i >= n else 0.0)
        wet = y
    return wet


# Voice: trim the silence, bring to 32 kHz, take out rumble.
vr, (voice,) = read(voice_path)
th = 0.01
first = next(i for i, v in enumerate(voice) if abs(v) > th)
last = len(voice) - next(i for i, v in enumerate(reversed(voice)) if abs(v) > th)
voice = voice[max(0, first - int(0.02 * vr)):last + int(0.06 * vr)]
voice = highpass(resample(voice, vr, RATE))
vpeak = max(map(abs, voice))
voice = [v / vpeak for v in voice]
vlen = len(voice) / RATE

base = (0.0297, 0.0371, 0.0411, 0.0437)
wet_l = reverb(voice, base)
wet_r = reverb(voice, [d * 1.083 for d in base])

for name in ("kasumi-bloom", "kasumi-sky-koto", "kasumi-glass-garden"):
    rate, (jl, jr) = read(f"{folder}/{name}.wav")
    assert rate == RATE
    total = min(3.0, len(jl) / RATE + 0.15)  # Home Menu cuts off near 3 s
    n = int(total * RATE)
    jl += [0.0] * (n - len(jl)); jr += [0.0] * (n - len(jr))
    start = total - vlen - 0.55  # leave the word's echo room to ring
    s0 = int(start * RATE)
    jpeak = max(max(map(abs, jl)), max(map(abs, jr)))
    vgain = 0.85 * jpeak
    # Duck the music a little while the word is spoken, with soft ramps.
    duck_from, duck_to, ramp = s0 - int(0.08 * RATE), s0 + len(voice), int(0.12 * RATE)
    out_l, out_r = [], []
    for i in range(n):
        if i < duck_from - ramp or i > duck_to + ramp * 3:
            g = 1.0
        elif i < duck_from:
            g = 1.0 - 0.45 * (i - (duck_from - ramp)) / ramp
        elif i <= duck_to:
            g = 0.55
        else:
            g = 0.55 + 0.45 * (i - duck_to) / (ramp * 3)
        l, r = jl[i] * g, jr[i] * g
        j = i - s0
        if 0 <= j < len(voice):
            l += voice[j] * vgain
            r += voice[j] * vgain
        if 0 <= j < len(wet_l):
            l += wet_l[j] * vgain * 0.28
            r += wet_r[j] * vgain * 0.28
        out_l.append(l); out_r.append(r)
    fade = int(0.25 * RATE)
    peak = max(max(map(abs, out_l)), max(map(abs, out_r)))
    gain = 0.75 / peak
    path = f"{folder}/{name}-voice.wav"
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE)
        b = bytearray()
        for i in range(n):
            f = 1.0 if i < n - fade else (n - i) / fade
            for v in (out_l[i], out_r[i]):
                b += struct.pack("<h", int(max(-1, min(1, v * gain * f)) * 32767))
        w.writeframes(bytes(b))
    print(f"wrote {path}: {total:.2f} s, voice at {start:.2f}-{start + vlen:.2f} s")
