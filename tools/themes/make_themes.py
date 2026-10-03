#!/usr/bin/env python3
"""Bottom-screen wallpapers for the themes.

    python tools/themes/make_themes.py

For each source image in resources/themes/<name>.(png|webp|jpg) it writes
  gfx/bg_<name>.png     320x240, cropped to fill the lower screen and
                        darkened so the UI's light text stays readable;
  gfx/glass_<name>.png  160x120, the same picture blurred and darker: the
                        3DS can't blur live, so buttons and cards draw the
                        part of this that lies behind them ("frosted glass").
Needs ffmpeg on the PATH (it decodes WebP and does the blur); no Python
packages. The sources are not in git (see .gitignore): check their licence
before shipping a wallpaper.
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, 'resources', 'themes')
OUT = os.path.join(ROOT, 'gfx')

# Brightest the backdrop gets (98th percentile of luminance, 0..1): under
# this, the UI's near-white text keeps its contrast over any pattern.
BACKDROP_PEAK = 0.40
# ...and its average, so an evenly bright picture (orange clouds) is dimmed too.
BACKDROP_MEAN = 0.20
# The glass's average luminance: dark enough that text on buttons and cards
# reads as on a solid panel, light enough to show the colour behind it.
GLASS_MEAN = 0.11


def read_png(path):
    data = open(path, 'rb').read()
    pos, idat, w, h, ct = 8, b'', 0, 0, 0
    while pos < len(data):
        n, kind = struct.unpack('>I4s', data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b'IHDR':
            w, h, depth, ct, _, _, interlace = struct.unpack('>IIBBBBB', chunk)
            assert depth == 8 and interlace == 0 and ct in (2, 6), path
        elif kind == b'IDAT':
            idat += chunk
    ch = 4 if ct == 6 else 3
    raw, stride, prev, rows, p = zlib.decompress(idat), w * ch, bytearray(w * ch), [], 0
    for _ in range(h):
        f = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        for x in range(stride):
            a = line[x - ch] if x >= ch else 0
            b = prev[x]
            c = prev[x - ch] if x >= ch else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append([tuple(line[x * ch:x * ch + 3]) for x in range(w)])
        prev = line
    return w, h, rows


def write_png(path, w, h, rows):
    raw = bytearray()
    for row in rows:
        raw.append(0)
        for px in row:
            raw += bytes(px)

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF)

    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
                           chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))


def ffmpeg(src, dst, vf):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-vf', vf, '-frames:v', '1', dst], check=True)


def luminance(px):
    return (0.2126 * px[0] + 0.7152 * px[1] + 0.0722 * px[2]) / 255.0


def scaled(rows, k):
    return [[tuple(min(255, int(c * k + 0.5)) for c in px) for px in row] for row in rows]


def make(name, src, work):
    cover = 'scale=320:240:force_original_aspect_ratio=increase:flags=lanczos,crop=320:240'
    sharp = os.path.join(work, name + '_sharp.png')
    soft = os.path.join(work, name + '_soft.png')
    ffmpeg(src, sharp, cover + ',format=rgb24')
    ffmpeg(src, soft, cover + ',scale=160:120:flags=area,gblur=sigma=6,format=rgb24')

    w, h, rows = read_png(sharp)
    lum = sorted(luminance(px) for row in rows for px in row)
    peak = lum[int(len(lum) * 0.98)] or 1.0
    average = sum(lum) / len(lum) or 1.0
    k = min(1.0, BACKDROP_PEAK / peak, BACKDROP_MEAN / average)
    write_png(os.path.join(OUT, 'bg_%s.png' % name), w, h, scaled(rows, k))

    w2, h2, rows2 = read_png(soft)
    mean = sum(luminance(px) for row in rows2 for px in row) / (w2 * h2) or 1.0
    write_png(os.path.join(OUT, 'glass_%s.png' % name), w2, h2, scaled(rows2, min(1.0, GLASS_MEAN / mean)))
    print('%-7s backdrop x%.2f (peak %.2f), glass x%.2f (mean %.2f)' % (name, k, peak, GLASS_MEAN / mean, mean))


def main():
    names = sys.argv[1:]
    with tempfile.TemporaryDirectory() as work:
        for file in sorted(os.listdir(SRC)):
            name, ext = os.path.splitext(file)
            if ext.lower() in ('.png', '.webp', '.jpg', '.jpeg') and (not names or name in names):
                make(name, os.path.join(SRC, file), work)


if __name__ == '__main__':
    main()
