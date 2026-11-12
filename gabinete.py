"""
Mapa físico do gabinete: onde fica cada fan / o cooler da corrente do hub iCUE LINK.

O hub informa a ordem dos aparelhos na corrente (cabos) e quantos LEDs cada um tem,
mas não a posição no gabinete. O usuário diz a posição (com a ajuda do "Identificar",
que acende cada aparelho numa cor) e aqui isso vira coordenadas: cada LED ganha um
ponto no anel da fan, no lugar certo do gabinete.

Coordenadas: vista pelo vidro lateral. x = 0 (traseira, lado da placa-mãe/IO) → 1
(frente); y = 0 (topo) → 1 (base). Proporção do desenho: largura 1.0, altura ALTURA.
"""

import math

ALTURA = 0.62           # o gabinete (visto de lado) é mais largo que alto

# papel → (x, y, raio, nome)
# (x e raio em "larguras" do gabinete; y em "alturas"). Tudo cabe dentro da caixa,
# contando o quadrado da fan (meio-lado ≈ 1,18 × raio).
POSICOES = {
    "topo_tras":     (0.31, 0.17, 0.068, "Topo — trás"),
    "topo_meio":     (0.51, 0.17, 0.068, "Topo — meio"),
    "topo_frente":   (0.71, 0.17, 0.068, "Topo — frente"),
    "lateral_cima":  (0.875, 0.45, 0.068, "Lateral — cima"),
    "lateral_baixo": (0.875, 0.76, 0.068, "Lateral — baixo"),
    "traseira":      (0.085, 0.40, 0.060, "Traseira"),
    "frente_baixo":  (0.62, 0.86, 0.060, "Base / frente"),
    "bomba":         (0.30, 0.46, 0.046, "Cooler (bomba)"),
}
# Peças só de referência no desenho (x0, y0, x1, y1) em frações do gabinete
PLACA_MAE = (0.17, 0.30, 0.62, 0.90)
PENTES_RAM = [(0.415, 0.34, 0.428, 0.57), (0.445, 0.34, 0.458, 0.57)]
PLACA_VIDEO = (0.18, 0.66, 0.72, 0.77)
NOMES = {k: v[3] for k, v in POSICOES.items()}
TIPO_COOLER = 9                 # tipo de aparelho que o hub informa para a bomba

# cores do "Identificar" (uma por aparelho da corrente)
CORES_ID = ["#ff1a1a", "#1aff3c", "#1a8cff", "#ffe11a", "#ff1aff", "#1affff", "#ff8c1a",
            "#ffffff"]
NOMES_CORES_ID = ["vermelha", "verde", "azul", "amarela", "rosa", "ciano", "laranja", "branca"]


def mapa_padrao(subs):
    """Chute inicial pela ordem dos cabos: laterais antes do cooler, topo depois."""
    fans_antes, fans_depois = [], []
    viu_cooler = False
    mapa = {}
    for i, (tipo, _n, _ids) in enumerate(subs):
        if tipo == TIPO_COOLER:
            mapa[i], viu_cooler = "bomba", True
        else:
            (fans_depois if viu_cooler else fans_antes).append(i)
    for i, papel in zip(fans_antes, ["lateral_baixo", "lateral_cima", "traseira"]):
        mapa[i] = papel
    for i, papel in zip(fans_depois, ["topo_frente", "topo_meio", "topo_tras", "traseira"]):
        mapa[i] = papel
    for i in range(len(subs)):
        mapa.setdefault(i, "traseira")
    return mapa


def posicoes_hub(subs, mapa):
    """[(led_id, x_mm, y_mm)] — LEDs de cada aparelho num anel, no lugar dele.
    (escala ×1000 só pra ficar no mesmo 'jeitão' das posições do iCUE)"""
    out = []
    for i, (_tipo, _n, ids) in enumerate(subs):
        x, y, r, _ = POSICOES.get(mapa.get(i, "traseira"), POSICOES["traseira"])
        n = len(ids)
        for k, led in enumerate(ids):
            a = 2 * math.pi * k / max(1, n) - math.pi / 2
            # r está em "larguras"; na vertical vira r/ALTURA "alturas" (círculo redondo)
            out.append((led, (x + r * math.cos(a)) * 1000,
                        (y + r * math.sin(a) / ALTURA) * 1000))
    return out


def desenho_hub(subs, mapa):
    """Para a prévia: [(indice_sub, papel, [(led_id, x, y)])] em coordenadas 0..1."""
    out = []
    for i, (_tipo, _n, ids) in enumerate(subs):
        papel = mapa.get(i, "traseira")
        x, y, r, _ = POSICOES.get(papel, POSICOES["traseira"])
        leds = [(led, x + r * math.cos(2 * math.pi * k / len(ids) - math.pi / 2),
                 y + r * math.sin(2 * math.pi * k / len(ids) - math.pi / 2) / ALTURA)
                for k, led in enumerate(ids)]
        out.append((i, papel, leds))
    return out
