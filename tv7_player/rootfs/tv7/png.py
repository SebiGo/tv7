"""PNG decoder for the channel logos and the idle logo: premultiplied BGRA, the raw format of mpv's overlay-add.
Standard library only (the image has no imaging library)."""

import zlib


def png_to_bgra(path):
    """Decode a PNG file into premultiplied BGRA (mpv's overlay-add format). Returns (width, height, bytes)."""
    return png_bytes_to_bgra(open(path, "rb").read())


PNG_MAX_PIXELS = 2_000_000  # logos and the idle logo are far smaller


def png_bytes_to_bgra(data):
    """Decode an 8-bit PNG (grey, RGB, palette, each with or without alpha; not interlaced) into premultiplied BGRA.
    Standard library only: the image has no imaging library."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos, idat, w, h, ctype, palette, trns = 8, b"", 0, 0, 0, b"", b""
    while pos < len(data):
        n = int.from_bytes(data[pos : pos + 4], "big")
        kind, body = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            w, h = int.from_bytes(body[0:4], "big"), int.from_bytes(body[4:8], "big")
            depth, ctype, interlace = body[8], body[9], body[12]
            if depth != 8 or ctype not in (0, 2, 3, 4, 6) or interlace:
                raise ValueError("only 8-bit PNGs without interlacing are supported")
            if not 0 < w * h <= PNG_MAX_PIXELS:
                raise ValueError(f"image too large ({w}x{h})")
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    stride = w * bpp
    need = h * (stride + 1)
    raw = zlib.decompressobj().decompress(idat, need)  # never more than the image needs (no decompression bomb)
    if len(raw) < need:
        raise ValueError("PNG data incomplete")
    prev, out = bytearray(stride), bytearray()
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        for x in range(w):
            q = x * bpp
            if ctype == 6:
                r_, g, b_, al = line[q], line[q + 1], line[q + 2], line[q + 3]
            elif ctype == 2:
                r_, g, b_, al = line[q], line[q + 1], line[q + 2], 255
            elif ctype == 3:
                k = line[q]
                r_, g, b_ = palette[3 * k : 3 * k + 3] or b"\0\0\0"
                al = trns[k] if k < len(trns) else 255
            elif ctype == 4:
                r_ = g = b_ = line[q]
                al = line[q + 1]
            else:
                r_ = g = b_ = line[q]
                al = 255
            out += bytes((b_ * al // 255, g * al // 255, r_ * al // 255, al))
        prev = line
    return w, h, bytes(out)
