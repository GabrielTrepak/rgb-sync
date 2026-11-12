"""
Ícone do RGB Sync: anel com o espectro de cores (como o anel de uma fan RGB)
sobre um quadrado escuro arredondado. Na bandeja, o centro mostra a cor atual.

Gerar os arquivos:  python icone.py   → assets/rgbsync.ico e assets/rgbsync.png
"""

import colorsys
import math
import os

from PIL import Image, ImageDraw, ImageFilter

FUNDO = (20, 20, 26, 255)


def _anel(tam):
    """Anel cônico (matiz girando) com anti-aliasing por supersampling."""
    s = tam * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    px = img.load()
    c = s / 2
    r_ext, r_int = s * 0.40, s * 0.27
    for y in range(s):
        dy = y + 0.5 - c
        for x in range(s):
            dx = x + 0.5 - c
            d = math.hypot(dx, dy)
            if r_int <= d <= r_ext:
                h = (math.atan2(dy, dx) / (2 * math.pi) + 0.25) % 1.0
                r, g, b = colorsys.hsv_to_rgb(h, 0.85, 1.0)
                px[x, y] = (int(r * 255), int(g * 255), int(b * 255), 255)
    return img.resize((tam, tam), Image.Resampling.LANCZOS)


_cache_anel = {}


def icone(tam=256, cor_centro=None, fundo=True):
    """cor_centro: (r, g, b) ou None (centro escuro com brilho do anel)."""
    if tam not in _cache_anel:
        _cache_anel[tam] = _anel(tam)
    base = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    if fundo:
        mask = Image.new("L", (tam * 4, tam * 4), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, tam * 4 - 1, tam * 4 - 1), radius=tam * 4 * 0.22, fill=255)
        mask = mask.resize((tam, tam), Image.Resampling.LANCZOS)
        base.paste(Image.new("RGBA", (tam, tam), FUNDO), (0, 0), mask)
    anel = _cache_anel[tam]
    # leve brilho em volta do anel
    brilho = anel.filter(ImageFilter.GaussianBlur(tam * 0.04))
    base.alpha_composite(Image.blend(Image.new("RGBA", (tam, tam), (0, 0, 0, 0)), brilho, 0.6))
    base.alpha_composite(anel)
    if cor_centro is not None:
        s = tam * 4
        m = Image.new("L", (s, s), 0)
        ImageDraw.Draw(m).ellipse((s * 0.33, s * 0.33, s * 0.67, s * 0.67), fill=255)
        m = m.resize((tam, tam), Image.Resampling.LANCZOS)
        base.paste(Image.new("RGBA", (tam, tam), tuple(cor_centro) + (255,)), (0, 0), m)
    return base


def gerar_arquivos(pasta):
    os.makedirs(pasta, exist_ok=True)
    grande = icone(256)
    grande.save(os.path.join(pasta, "rgbsync.png"))
    tamanhos = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    imgs = [icone(t) for t in tamanhos]
    imgs[-1].save(os.path.join(pasta, "rgbsync.ico"), sizes=[(t, t) for t in tamanhos],
                  append_images=imgs[:-1])


if __name__ == "__main__":
    gerar_arquivos(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets"))
    print("ok")
