"""
HyperX Alloy Origins Core — iluminação tecla por tecla (sem SDK oficial).

Protocolo descoberto pela comunidade do OpenRGB (aqui reescrito do zero). Só usa
comandos de ILUMINAÇÃO; nada grava na memória do teclado nem mexe em firmware:
  0x10  consulta (modelo/layout)
  0xA2  cores das teclas (modo direto) — precisa ser reenviado sempre (~a cada 50 ms),
        senão o teclado volta pro perfil salvo nele.
Se algo der errado: desconectar e reconectar o cabo volta tudo ao normal.

Teste:  python hyperx.py
"""

import time

import hid

VIDS_PIDS = [(0x03F0, 0x098F), (0x0951, 0x16E6)]   # versão HP e versão Kingston
PAGINA_VENDOR = 0xFF13
TAM_BUFFER = 380            # 94 posições (8 grupos de 12, o último incompleto)

LAYOUT_ANSI, LAYOUT_ABNT2 = 0x09, 0x10      # byte 56 da resposta da consulta

# Tecla -> índice no buffer, por fileira. (nome, índice, x do centro, largura), em
# "unidades de tecla" (1u = 19,05 mm). Layout americano (ANSI) como base:
_F0 = [("Esc", 0, 0.5, 1), ("F1", 1, 2.5, 1), ("F2", 2, 3.5, 1), ("F3", 3, 4.5, 1),
       ("F4", 4, 5.5, 1), ("F5", 5, 7.0, 1), ("F6", 6, 8.0, 1), ("F7", 7, 9.0, 1),
       ("F8", 48, 10.0, 1), ("F9", 49, 11.5, 1), ("F10", 50, 12.5, 1), ("F11", 51, 13.5, 1),
       ("F12", 52, 14.5, 1), ("PrtSc", 53, 15.75, 1), ("ScrLk", 54, 16.75, 1),
       ("Pause", 55, 17.75, 1)]
_F1 = ([("`", 8, 0.5, 1)]
       + [(str((i + 1) % 10), idx, 1.5 + i, 1)
          for i, idx in enumerate([9, 10, 11, 12, 13, 14, 15, 16, 56, 57])]
       + [("-", 58, 11.5, 1), ("=", 59, 12.5, 1), ("Backspace", 60, 14.0, 2),
          ("Ins", 61, 15.75, 1), ("Home", 62, 16.75, 1), ("PgUp", 63, 17.75, 1)])
_LETRAS2 = [(k, idx, 2.0 + i, 1) for i, (k, idx) in enumerate(
    zip("QWERTYUIOP", [18, 19, 20, 21, 22, 23, 24, 64, 65, 66]))]
_NAV2 = [("Del", 70, 15.75, 1), ("End", 71, 16.75, 1), ("PgDn", 72, 17.75, 1)]
_LETRAS3 = [(k, idx, 2.25 + i, 1) for i, (k, idx) in enumerate(
    zip("ASDFGHJKL", [26, 27, 28, 29, 30, 31, 32, 73, 74]))]
_LETRAS4 = [(k, idx, 2.75 + i, 1) for i, (k, idx) in enumerate(
    zip("ZXCVBNM", [35, 36, 37, 38, 39, 40, 79]))]
_F5 = [("LCtrl", 41, 0.625, 1.25), ("Win", 42, 1.875, 1.25), ("Alt", 43, 3.125, 1.25),
       ("Espaco", 45, 6.875, 6.25), ("AltGr", 86, 10.625, 1.25), ("Fn", 87, 11.875, 1.25),
       ("Menu", 88, 13.125, 1.25), ("RCtrl", 89, 14.375, 1.25), ("Left", 90, 15.75, 1),
       ("Down", 91, 16.75, 1), ("Right", 92, 17.75, 1)]

TECLAS_ANSI = [
    _F0, _F1,
    [("Tab", 17, 0.75, 1.5)] + _LETRAS2
    + [("[", 67, 12.0, 1), ("]", 68, 13.0, 1), ("\\", 69, 14.25, 1.5)] + _NAV2,
    [("Caps", 25, 0.875, 1.75)] + _LETRAS3
    + [(";", 75, 11.25, 1), ("'", 76, 12.25, 1), ("Enter", 78, 13.875, 2.25)],
    [("LShift", 33, 1.125, 2.25)] + _LETRAS4
    + [(",", 80, 9.75, 1), (".", 81, 10.75, 1), ("/", 82, 11.75, 1),
       ("RShift", 84, 13.625, 2.75), ("Up", 85, 16.75, 1)],
    _F5,
]
# Brasileiro (ABNT2): Ç, ~ e ] na fileira do A, Enter alto, \ ao lado do Shift
# esquerdo, ; e / perto do Shift direito.
TECLAS_ABNT2 = [
    _F0, _F1,
    [("Tab", 17, 0.75, 1.5)] + _LETRAS2
    + [("´", 67, 12.0, 1), ("[", 68, 13.0, 1), ("Enter", 78, 14.125, 1.25)] + _NAV2,
    [("Caps", 25, 0.875, 1.75)] + _LETRAS3
    + [("Ç", 75, 11.25, 1), ("~", 76, 12.25, 1), ("]", 77, 13.25, 1),
       ("Enter ", 78, 14.125, 1.25)],
    [("LShift", 33, 0.625, 1.25), ("\\", 34, 1.75, 1)] + _LETRAS4
    + [(",", 80, 9.75, 1), (".", 81, 10.75, 1), (";", 82, 11.75, 1), ("/", 83, 12.75, 1),
       ("RShift", 84, 14.125, 1.75), ("Up", 85, 16.75, 1)],
    _F5,
]
TECLAS = TECLAS_ANSI
Y_FILEIRA = [0.5, 2.0, 3.0, 4.0, 5.0, 6.0]    # fileira das F tem um vão embaixo


def teclas(layout=LAYOUT_ANSI):
    return TECLAS_ABNT2 if layout == LAYOUT_ABNT2 else TECLAS_ANSI


def posicoes(layout=LAYOUT_ANSI):
    """[(indice, x_mm, y_mm)] — mesmo formato das posições de LED do iCUE. Uma tecla
    que aparece duas vezes (o Enter alto do ABNT2) entra uma vez só."""
    vistos, out = set(), []
    for f, linha in enumerate(teclas(layout)):
        for _n, idx, x, _w in linha:
            if idx not in vistos:
                vistos.add(idx)
                out.append((idx, x * 19.05, Y_FILEIRA[f] * 19.05))
    return out


def desenho(layout=LAYOUT_ANSI):
    """[(indice, x_centro_u, fileira, largura_u)] para desenhar a prévia."""
    return [(idx, x, f, w) for f, linha in enumerate(teclas(layout))
            for _n, idx, x, w in linha]


def _offsets(n):
    """Onde ficam G, R e B do LED n no buffer: grupos de 12 LEDs (48 bytes) com
    três planos de 16 bytes (G, R, B); cada plano tem 2 setores de 6 bytes + 2 vazios."""
    grupo, pos = divmod(n, 12)
    setor, i = divmod(pos, 6)
    base = grupo * 48 + setor * 8 + i
    return base, base + 16, base + 32


class TecladoHyperX:
    def __init__(self):
        self.dev = None
        self.nome = None
        self.buf = bytearray(TAM_BUFFER)

    def conectar(self):
        for vid, pid in VIDS_PIDS:
            for d in hid.enumerate(vid, pid):
                if d["usage_page"] == PAGINA_VENDOR:
                    dev = hid.device()
                    dev.open_path(d["path"])
                    self.dev, self.nome = dev, d["product_string"]
                    return True
        return False

    def consultar(self):
        """Pede as informações do teclado. Devolve (bytes da resposta, layout).
        A resposta começa com 0x10; o layout fica no byte 56. Se outro programa
        (ex.: NGENUITY) estiver mandando cores, a resposta vem 'trocada'."""
        self.dev.write([0x00, 0x10] + [0x00] * 63)
        for _ in range(5):
            resp = bytes(self.dev.read(65, 500))
            if resp[:1] == bytes([0x10]) and len(resp) > 56:
                return resp, resp[56]
        return resp, None

    def definir(self, cores):
        """cores: {indice: (r, g, b)} — o resto fica apagado."""
        self.buf = bytearray(TAM_BUFFER)
        for n, (r, g, b) in cores.items():
            og, orr, ob = _offsets(n)
            if ob < TAM_BUFFER:
                self.buf[og], self.buf[orr], self.buf[ob] = g, r, b

    def enviar(self):
        """Manda o buffer em pacotes de até 60 bytes (comando 0xA2 + sequência)."""
        seq = 0
        for i in range(0, TAM_BUFFER, 60):
            parte = self.buf[i:i + 60]
            self.dev.write([0x00, 0xA2, seq, 0x00, len(parte)] + list(parte))
            seq += 1

    def fechar(self):
        if self.dev:
            self.dev.close()
            self.dev = None


def _segurar(tec, segundos):
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        tec.enviar()
        time.sleep(0.05)


if __name__ == "__main__":
    tec = TecladoHyperX()
    if not tec.conectar():
        raise SystemExit("teclado não encontrado")
    print("conectado:", tec.nome)
    resp = tec.consultar()
    print("resposta da consulta (%d bytes):" % len(resp), resp.hex(" "))
    if len(resp) > 56:
        print("  texto:", resp[9:34].split(b"\0")[0].decode("ascii", "replace"),
              "| layout (byte 56):", hex(resp[56]))
    todas = [idx for linha in TECLAS for _n, idx, _x in linha]
    print("1) todas azuis por 5 s")
    tec.definir({i: (0, 80, 255) for i in todas})
    _segurar(tec, 5)
    nomes = ["Esc/F1…", "números", "Q…", "A…", "Z…", "espaço/setas"]
    for f, linha in enumerate(TECLAS):
        print(f"2.{f + 1}) fileira {nomes[f]} em verde")
        tec.definir({idx: (0, 255, 60) for _n, idx, _x, _w in linha})
        _segurar(tec, 1.5)
    print("3) fim — parando de enviar (o teclado deve voltar ao perfil dele)")
    tec.fechar()
