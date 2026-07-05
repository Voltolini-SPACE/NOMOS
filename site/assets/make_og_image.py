#!/usr/bin/env python3
"""Gera site/assets/og-image.png (1200x630) na identidade do Brandbook v1.0 (congelado).

Paleta congelada: fundo #0A0F0D, verde-neon #5AF78E, texto #E8FFE8, monospace.
Fonte editável de referência: og-image.svg. Requer Pillow (dependência de dev).

Uso:
    python site/assets/make_og_image.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
BG = (10, 15, 13)          # #0A0F0D preto terminal
SURFACE = (17, 24, 20)     # #111814
LINE = (36, 56, 42)        # #24382a
NEON = (90, 247, 142)      # #5AF78E verde-neon
NEON_DIM = (43, 217, 104)  # #2BD968
TEXT = (232, 255, 232)     # #E8FFE8
TEXT2 = (159, 184, 165)    # #9fb8a5
FAINT = (111, 138, 118)    # #6f8a76

MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
OUT = Path(__file__).resolve().parent / "og-image.png"


def _font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size=size)


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # moldura sutil de terminal
    d.rectangle([28, 28, W - 28, H - 28], outline=LINE, width=2)
    # barra de "janela" de terminal
    d.rectangle([28, 28, W - 28, 74], fill=SURFACE, outline=LINE, width=2)
    for i, col in enumerate(((255, 92, 87), (242, 193, 78), (90, 247, 142))):
        d.ellipse([54 + i * 26, 44, 68 + i * 26, 58], fill=col)
    d.text((150, 44), "nomos — local por lei", font=_font(MONO, 20), fill=FAINT)

    # prompt + wordmark NOMOS com "glow" (subcamadas neon-dim)
    d.text((78, 150), "$ nomos", font=_font(MONO, 30), fill=NEON_DIM)
    word_font = _font(MONO_BOLD, 132)
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        d.text((78 + dx, 196 + dy), "NOMOS", font=word_font, fill=NEON_DIM)
    d.text((78, 196), "NOMOS", font=word_font, fill=NEON)
    # cursor piscante (estático na imagem)
    d.text((640, 196), "▋", font=word_font, fill=NEON)

    # tagline (Brandbook §2)
    d.text((80, 372), "Seu agente. Sua máquina. Suas regras.",
           font=_font(MONO_BOLD, 34), fill=TEXT)
    d.text((80, 430), "Agente pessoal de IA que roda 100% no seu computador.",
           font=_font(MONO, 24), fill=TEXT2)

    # selo "local por lei"
    badge = "local por lei"
    bf = _font(MONO_BOLD, 24)
    bb = d.textbbox((0, 0), badge, font=bf)
    bw = bb[2] - bb[0]
    d.rounded_rectangle([80, 484, 80 + bw + 44, 534], radius=8,
                        fill=SURFACE, outline=NEON, width=2)
    d.text((102, 496), badge, font=bf, fill=NEON)

    # rodapé
    d.text((W - 52, 556), "github.com/Voltolini-SPACE/NOMOS",
           font=_font(MONO, 22), fill=FAINT, anchor="rs")

    img.save(OUT, "PNG")
    print(f"OK: {OUT} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
