"""Gera rabisco.ico (multi-tamanho) com Pillow. Uso: python make_icon.py <saida.ico> [preview.png]"""
import sys
from PIL import Image, ImageDraw

YELLOW_TOP = (255, 217, 90)
YELLOW_BOT = (242, 179, 46)
INK = (38, 32, 22)
SS = 4  # supersampling


def note_base(size):
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # gradiente vertical
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        c = tuple(int(YELLOW_TOP[i] + (YELLOW_BOT[i] - YELLOW_TOP[i]) * t) for i in range(3))
        gd.line([(0, y), (S, y)], fill=c + (255,))
    mask = Image.new("L", (S, S), 0)
    m = ImageDraw.Draw(mask)
    pad = round(S * 0.06)
    m.rounded_rectangle([pad, pad, S - pad - 1, S - pad - 1], radius=round(S * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)
    return img, S


def draw_large(size):
    img, S = note_base(size)
    d = ImageDraw.Draw(img)
    r = S * 0.072
    cx = S * 0.29
    rows = [0.31, 0.50, 0.69]
    ends = [0.74, 0.76, 0.62]
    lw = round(S * 0.062)
    for i, (cy, ex) in enumerate(zip(rows, ends)):
        cy *= S
        box = [cx - r, cy - r, cx + r, cy + r]
        if i == 0:
            d.ellipse(box, fill=INK + (255,))
            # check amarelo dentro
            pts = [(cx - r * 0.48, cy + r * 0.02), (cx - r * 0.1, cy + r * 0.40), (cx + r * 0.52, cy - r * 0.38)]
            d.line(pts, fill=YELLOW_TOP + (255,), width=round(r * 0.32), joint="curve")
            line_col = INK + (110,)
        else:
            d.ellipse(box, outline=INK + (255,), width=round(S * 0.032))
            line_col = INK + (235,)
        x0, x1 = S * 0.42, S * ex
        d.rounded_rectangle([x0, cy - lw / 2, x1, cy + lw / 2], radius=lw / 2, fill=line_col)
    return img.resize((size, size), Image.LANCZOS)


def draw_small(size):
    img, S = note_base(size)
    d = ImageDraw.Draw(img)
    w = round(S * 0.14)
    pts = [(S * 0.27, S * 0.52), (S * 0.43, S * 0.68), (S * 0.74, S * 0.35)]
    d.line(pts, fill=INK + (255,), width=w, joint="curve")
    for x, y in (pts[0], pts[-1]):  # pontas arredondadas
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=INK + (255,))
    return img.resize((size, size), Image.LANCZOS)


def main():
    out = sys.argv[1]
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    imgs = [draw_small(s) if s <= 32 else draw_large(s) for s in sizes]
    big = imgs[-1]
    big.save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[:-1])
    if len(sys.argv) > 2:
        sheet = Image.new("RGBA", (sum(sizes) + 10 * len(sizes), 256), (40, 40, 46, 255))
        x = 0
        for im in imgs:
            sheet.paste(im, (x, 0), im)
            x += im.width + 10
        sheet.save(sys.argv[2])


if __name__ == "__main__":
    main()
