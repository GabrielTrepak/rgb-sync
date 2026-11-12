"""
Ícone do RGB Sync: fogueira com uma espada longa fincada no meio, em estilo silhueta.

- Espada longa e fina, levemente inclinada, pomo em anel, ocupando a altura do ícone;
- chamas recortadas subindo pela lâmina, pintadas com o espectro RGB inteiro;
- núcleo da fogueira na base: branco-quente no ícone do app, ou a COR ATUAL dos LEDs
  no ícone da bandeja (icone(tam, cor_centro=(r, g, b)));
- cinzas e brasas embaixo.

Gerar os arquivos:  python icone.py   → assets/rgbsync.ico e assets/rgbsync.png
"""

import colorsys
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

FUNDO = (17, 14, 19, 255)
SS = 4                        # supersampling (desenha 4x maior e reduz = bordas suaves)
BASE_Y = 0.86                 # onde o fogo nasce
ESPADA_X = 0.50               # onde a lâmina entra nas cinzas
INCLINACAO = math.radians(5)  # espada levemente torta (topo pra esquerda)

# Línguas de fogo (x da base, altura, largura, curva da ponta, balanço).
# Valores de 0 a 1 relativos ao ícone. Juntas formam UMA silhueta de fogo.
LINGUAS = [
    (0.50, 0.44, 0.24, 0.00, 0.04),     # corpo principal
    (0.33, 0.45, 0.12, 0.08, -0.04),
    (0.67, 0.50, 0.12, -0.08, 0.04),
    (0.24, 0.31, 0.10, 0.09, -0.03),
    (0.77, 0.35, 0.10, -0.09, 0.03),
    (0.16, 0.18, 0.08, 0.06, -0.02),
    (0.85, 0.20, 0.08, -0.06, 0.02),
    (0.42, 0.58, 0.075, 0.05, 0.04),    # línguas finas subindo coladas na lâmina
    (0.585, 0.55, 0.075, -0.05, -0.04),
    (0.51, 0.69, 0.05, -0.02, 0.05),    # a mais alta, lambendo a lâmina
]


def _lingua(s, cx, h, w, ponta, onda, base_y=BASE_Y, n=72):
    """Uma língua de fogo: barriga embaixo, ponta fina e afiada que curva e balança,
    bordas com recortes (dá o aspecto 'agitado' de silhueta)."""
    cx, h, w, by = cx * s, h * s, w * s, base_y * s
    esq, dir_ = [], []
    for i in range(n + 1):
        t = i / n                                     # 0 = base, 1 = ponta
        meia = w / 2 * (1 - t) ** 1.25 * (0.9 + 0.3 * math.sin(math.pi * min(t * 2, 1.0)))
        x = cx + ponta * s * t ** 1.5 + onda * s * math.sin(math.pi * t * 1.6)
        y = by - h * t
        rec_e = 1 + 0.16 * math.sin(7.0 * math.pi * t) * t        # recortes, mais no alto
        rec_d = 1 + 0.16 * math.sin(7.0 * math.pi * t + 2.2) * t
        esq.append((x - meia * rec_e, y))
        dir_.append((x + meia * rec_d, y))
    fundo = [(cx + w / 2 * math.cos(a), by + w * 0.18 * math.sin(a))
             for a in [math.pi * k / 16 for k in range(17)]]
    return esq[::-1] + fundo[::-1] + dir_


def _mascara_fogo(s, escala=1.0, deslocar=0.0):
    m = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(m)
    for cx, h, w, ponta, onda in LINGUAS:
        d.polygon(_lingua(s, cx + deslocar, h * escala, w * escala, ponta * escala, onda),
                  fill=255)
    return m


def _arco_iris(s):
    """Espectro na horizontal (vermelho → magenta) + base mais quente e clara."""
    faixa = Image.new("RGB", (s, 1))
    px = faixa.load()
    for x in range(s):
        t = x / (s - 1)
        r, g, b = colorsys.hsv_to_rgb((0.0 + 0.86 * (t - 0.1) / 0.8) % 1.0
                                      if 0.1 <= t <= 0.9 else (0.0 if t < 0.1 else 0.86),
                                      0.92, 1.0)
        px[x, 0] = (round(r * 255), round(g * 255), round(b * 255))
    img = faixa.resize((s, s))
    # clareia em direção à base (fogo mais quente embaixo)
    clareia = Image.new("L", (1, s))
    pc = clareia.load()
    for y in range(s):
        t = max(0.0, (y / s - 0.55) / (BASE_Y - 0.55))
        pc[0, y] = round(min(1.0, t) ** 2 * 120)
    branco = Image.new("RGB", (s, s), (255, 236, 210))
    return Image.composite(branco, img, clareia.resize((s, s)))


def _espada(s):
    """Camada RGBA da espada (desenhada reta e girada em torno do ponto nas cinzas)."""
    cam = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(cam)
    x = ESPADA_X * s
    aco, fio, escuro = (226, 218, 210, 255), (255, 250, 244, 255), (120, 110, 112, 255)
    topo_lamina, ponta_lamina = 0.255 * s, (BASE_Y + 0.03) * s
    lw = 0.030 * s
    d.polygon([(x - lw, topo_lamina), (x + lw, topo_lamina),
               (x + lw * 0.8, ponta_lamina - lw), (x, ponta_lamina),
               (x - lw * 0.8, ponta_lamina - lw)], fill=aco)                       # lâmina
    d.polygon([(x - lw * 0.15, topo_lamina + 4), (x + lw * 0.35, topo_lamina + 4),
               (x + lw * 0.25, ponta_lamina - lw * 2), (x - lw * 0.15, ponta_lamina - lw * 2)],
              fill=fio)                                                             # brilho
    d.rounded_rectangle((x - 0.13 * s, 0.225 * s, x + 0.13 * s, 0.258 * s),
                        radius=0.012 * s, fill=aco)                                 # guarda
    d.rounded_rectangle((x - 0.018 * s, 0.115 * s, x + 0.018 * s, 0.228 * s),
                        radius=0.008 * s, fill=escuro)                              # cabo
    r_ext, r_int = 0.048 * s, 0.024 * s                                             # pomo-anel
    cy = 0.072 * s
    d.ellipse((x - r_ext, cy - r_ext, x + r_ext, cy + r_ext), fill=aco)
    d.ellipse((x - r_int, cy - r_int, x + r_int, cy + r_int), fill=(0, 0, 0, 0))
    return cam.rotate(math.degrees(INCLINACAO), resample=Image.Resampling.BICUBIC,
                      center=(x, BASE_Y * s))


def _clarear(rgb, k):
    return tuple(round(c + (255 - c) * k) for c in rgb[:3])


def icone(tam=256, cor_centro=None, fundo=True):
    s = tam * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    quadro = Image.new("L", (s, s), 0)
    ImageDraw.Draw(quadro).rounded_rectangle((0, 0, s - 1, s - 1), radius=s * 0.22, fill=255)

    if fundo:
        base = Image.new("RGBA", (s, s), FUNDO)
        brilho = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(brilho).ellipse((s * 0.08, s * 0.40, s * 0.92, s * 1.10),
                                       fill=(255, 110, 40, 80))
        base.alpha_composite(brilho.filter(ImageFilter.GaussianBlur(s * 0.10)))
        img.paste(base, (0, 0), quadro)

    mascara = _mascara_fogo(s)
    cores = _arco_iris(s).convert("RGBA")

    # halo colorido do fogo
    halo = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    halo.paste(cores, (0, 0), mascara.filter(ImageFilter.GaussianBlur(s * 0.05)))
    img.alpha_composite(Image.blend(Image.new("RGBA", (s, s), (0, 0, 0, 0)), halo, 0.75))

    # a espada fica ATRÁS das línguas da frente: desenha fogo de trás, espada, fogo da frente
    tras = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    tras.paste(cores, (0, 0), mascara)
    img.alpha_composite(tras)
    img.alpha_composite(_espada(s))
    frente = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(frente)
    for cx, h, w, ponta, onda in LINGUAS[:7]:            # só as línguas baixas cobrem a lâmina
        d.polygon(_lingua(s, cx, h * 0.62, w * 0.95, ponta * 0.6, onda), fill=255)
    camada_frente = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    camada_frente.paste(cores, (0, 0), frente)
    img.alpha_composite(camada_frente)

    # núcleo (cor atual ou branco-quente)
    if cor_centro is None:
        baixo, alto = (255, 244, 220), (255, 200, 120)
    else:
        rgb = tuple(cor_centro[:3])
        if sum(rgb) < 45:
            rgb = (70, 60, 60)                            # LEDs apagados: brasa fraca
        baixo, alto = _clarear(rgb, 0.35), rgb
    nucleo = Image.new("L", (s, s), 0)
    ImageDraw.Draw(nucleo).polygon(_lingua(s, 0.5, 0.30, 0.24, 0.0, 0.02), fill=255)
    grad = Image.new("RGB", (1, s))
    pg = grad.load()
    for y in range(s):
        t = min(1.0, max(0.0, ((BASE_Y * s) - y) / (0.30 * s)))
        pg[0, y] = tuple(round(a + (b - a) * t) for a, b in zip(baixo, alto))
    cam_n = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    cam_n.paste(grad.resize((s, s)).convert("RGBA"), (0, 0), nucleo)
    img.alpha_composite(cam_n.filter(ImageFilter.GaussianBlur(s * 0.015)))
    img.alpha_composite(cam_n)

    # cinzas e brasas
    d = ImageDraw.Draw(img)
    d.ellipse((s * 0.16, s * 0.83, s * 0.84, s * 0.95), fill=(40, 34, 36, 255))
    d.ellipse((s * 0.24, s * 0.835, s * 0.76, s * 0.90), fill=(62, 52, 50, 255))
    for px, py in [(0.34, 0.875), (0.44, 0.86), (0.57, 0.865), (0.66, 0.88), (0.50, 0.89)]:
        d.ellipse((s * (px - 0.014), s * (py - 0.009), s * (px + 0.014), s * (py + 0.009)),
                  fill=(255, 150, 60, 255))
    # faíscas
    for px, py, r in [(0.27, 0.40, 0.011), (0.76, 0.33, 0.013), (0.83, 0.52, 0.009),
                      (0.18, 0.56, 0.009), (0.68, 0.18, 0.008)]:
        d.ellipse((s * (px - r), s * (py - r), s * (px + r), s * (py + r)),
                  fill=(255, 214, 150, 230))

    if fundo:
        img.putalpha(ImageChops.multiply(img.getchannel("A"), quadro))
    return img.resize((tam, tam), Image.Resampling.LANCZOS)


def gerar_arquivos(pasta):
    os.makedirs(pasta, exist_ok=True)
    icone(256).save(os.path.join(pasta, "rgbsync.png"))
    tamanhos = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    imgs = [icone(t) for t in tamanhos]
    imgs[-1].save(os.path.join(pasta, "rgbsync.ico"), sizes=[(t, t) for t in tamanhos],
                  append_images=imgs[:-1])


if __name__ == "__main__":
    gerar_arquivos(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets"))
    print("ok")
