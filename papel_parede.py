"""
Lê o papel de parede e escolhe a cor para os LEDs.

Fonte da imagem, em ordem:
  1. Wallpaper Engine: captura a janela onde ele desenha (PrintWindow). Pega o
     papel de parede de verdade — animado, playlist, o que for — e NÃO pega as
     janelas abertas por cima.
  2. Papel de parede normal do Windows (arquivo TranscodedWallpaper).

Uso de teste:  python papel_parede.py [saida.png]
"""

import colorsys
import ctypes
import os
import time
from ctypes import wintypes as W

from PIL import Image

u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32
u32.GetDC.restype = W.HDC
u32.GetDC.argtypes = [W.HWND]
u32.ReleaseDC.argtypes = [W.HWND, W.HDC]
u32.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
u32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
u32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
g32.CreateCompatibleDC.restype = W.HDC
g32.CreateCompatibleDC.argtypes = [W.HDC]
g32.CreateCompatibleBitmap.restype = W.HBITMAP
g32.CreateCompatibleBitmap.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]
g32.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
g32.DeleteObject.argtypes = [W.HGDIOBJ]
g32.DeleteDC.argtypes = [W.HDC]
g32.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, ctypes.c_void_p,
                          ctypes.c_void_p, W.UINT]
g32.SetStretchBltMode.argtypes = [W.HDC, ctypes.c_int]
g32.SetBrushOrgEx.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
g32.StretchBlt.argtypes = ([W.HDC] + [ctypes.c_int] * 4 + [W.HDC] + [ctypes.c_int] * 4
                           + [W.DWORD])
u32.IsWindow.argtypes = [W.HWND]
HALFTONE, SRCCOPY = 4, 0x00CC0020

EnumProc = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
MonitorProc = ctypes.WINFUNCTYPE(W.BOOL, W.HMONITOR, W.HDC, ctypes.POINTER(W.RECT), W.LPARAM)
PER_MONITOR_V2 = ctypes.c_void_p(-4)


class _BMI(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG),
                ("biPlanes", W.WORD), ("biBitCount", W.WORD), ("biCompression", W.DWORD),
                ("biSizeImage", W.DWORD), ("biXPelsPerMeter", W.LONG),
                ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD), ("biClrImportant", W.DWORD)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT),
                ("dwFlags", W.DWORD)]


# ------------------------------------------------------------- Wallpaper Engine
def _janela_wallpaper_engine(com_raiz=False):
    """Janela onde o Wallpaper Engine desenha. Vídeo: WPEVideoWallpaper; cena/web:
    WPEDesktopDX11Window (e outras WPE*). Com com_raiz=True devolve (janela, raiz),
    onde raiz é a camada da área de trabalho que a contém (Progman ou WorkerW)."""
    achadas = []
    raiz_atual = [None]

    def cb(h, _):
        cls = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(h, cls, 64)
        if cls.value.startswith("WPE") and u32.IsWindowVisible(h):
            r = W.RECT()
            u32.GetClientRect(h, ctypes.byref(r))
            achadas.append((r.right * r.bottom, h, raiz_atual[0]))
        return True

    p = u32.FindWindowW("Progman", None)
    if p:
        raiz_atual[0] = p
        u32.EnumChildWindows(p, EnumProc(cb), 0)
    # Em algumas versões do Windows ele fica dentro de um WorkerW de topo
    if not achadas:
        def topo(h, _):
            cls = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(h, cls, 64)
            if cls.value == "WorkerW":
                raiz_atual[0] = h
                u32.EnumChildWindows(h, EnumProc(cb), 0)
            return True
        u32.EnumWindows(EnumProc(topo), 0)
    if not achadas:
        return (None, None) if com_raiz else None
    _, h, raiz = max(achadas)                          # a maior (a que cobre a tela)
    return (h, raiz) if com_raiz else h


def _capturar_janela(hwnd):
    r = W.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right, r.bottom
    if w <= 0 or h <= 0:
        return None
    hdc = u32.GetDC(hwnd)
    mem = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    g32.SelectObject(mem, bmp)
    try:
        if not u32.PrintWindow(hwnd, mem, 0):
            return None
        bmi = _BMI(ctypes.sizeof(_BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        g32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
        img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    finally:
        g32.DeleteObject(bmp)
        g32.DeleteDC(mem)
        u32.ReleaseDC(hwnd, hdc)
    wr = W.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(wr))
    return img, (wr.left, wr.top)


def monitores():
    """[(rect, principal?)] em coordenadas da área de trabalho virtual."""
    lista = []

    def cb(hmon, _hdc, _r, _):
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        u32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        rc = mi.rcMonitor
        lista.append(((rc.left, rc.top, rc.right, rc.bottom), bool(mi.dwFlags & 1)))
        return True

    u32.EnumDisplayMonitors(None, None, MonitorProc(cb), 0)
    return lista


def _recortar_monitor(img, origem, qual):
    """qual: 'ambos' | 'principal' | 'secundario'."""
    if qual == "ambos":
        return img
    mons = monitores()
    alvo = next((m for m, prim in mons if prim == (qual == "principal")), None)
    if not alvo:
        return img
    ox, oy = origem
    caixa = (alvo[0] - ox, alvo[1] - oy, alvo[2] - ox, alvo[3] - oy)
    caixa = (max(0, caixa[0]), max(0, caixa[1]),
             min(img.width, caixa[2]), min(img.height, caixa[3]))
    if caixa[2] - caixa[0] < 10 or caixa[3] - caixa[1] < 10:
        return img
    return img.crop(caixa)


# ------------------------------------------------------------- Windows normal
def _papel_parede_windows():
    p = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Themes\TranscodedWallpaper")
    try:
        with Image.open(p) as im:
            return im.convert("RGB")
    except Exception:
        return None


def capturar(qual="ambos"):
    """Devolve (imagem, fonte) ou (None, motivo)."""
    antigo = u32.SetThreadDpiAwarenessContext(PER_MONITOR_V2)
    try:
        hwnd = _janela_wallpaper_engine()
        if hwnd:
            res = _capturar_janela(hwnd)
            if res:
                img, origem = res
                return _recortar_monitor(img, origem, qual), "Wallpaper Engine"
        img = _papel_parede_windows()
        if img:
            return img, "Windows"
        return None, "papel de parede não encontrado"
    finally:
        if antigo:
            u32.SetThreadDpiAwarenessContext(antigo)


# ------------------------------------------------------------- captura rápida (modo ao vivo)
class Capturador:
    """Versão otimizada de capturar() para rodar várias vezes por segundo.

    - Reaproveita os buffers do Windows entre quadros (nada é criado a cada quadro).
    - Reduz a imagem DENTRO do Windows (StretchBlt com média, modo HALFTONE) antes
      de passar para o Python: em vez de copiar 3840×1080 (16 MB) por quadro, copia
      192×108 (80 KB). ~20 ms → ~5 ms por quadro.
    - Procura a janela do Wallpaper Engine de novo a cada 2 s (ela muda quando o
      papel de parede troca entre vídeo e cena) e os monitores a cada 10 s.
    Deve ser usado sempre pela mesma thread.
    """

    LARGURA, ALTURA = 192, 108

    def __init__(self):
        self.hwnd = None
        self.hwnd_t = 0.0
        self.mons = None
        self.mons_t = 0.0
        self.grande = None        # (hdc_janela_hwnd, mem, bmp, w, h)
        mem = g32.CreateCompatibleDC(None)
        self.mem_p = mem
        self.bmp_p = None
        self.buf = ctypes.create_string_buffer(self.LARGURA * self.ALTURA * 4)
        self.bmi = _BMI(ctypes.sizeof(_BMI), self.LARGURA, -self.ALTURA, 1, 32, 0, 0, 0, 0, 0, 0)
        self.windows_cache = (None, None)   # (mtime, imagem pequena)
        self.raiz = None
        self.modo = "janela"
        self.lento = False

    def _liberar_grande(self):
        if self.grande:
            _, mem, bmp, _, _ = self.grande
            g32.DeleteObject(bmp)
            g32.DeleteDC(mem)
            self.grande = None

    def _buffers(self, hwnd, w, h):
        if self.grande and self.grande[0] == hwnd and self.grande[3:] == (w, h):
            return self.grande[1]
        self._liberar_grande()
        hdc = u32.GetDC(hwnd)
        mem = g32.CreateCompatibleDC(hdc)
        bmp = g32.CreateCompatibleBitmap(hdc, w, h)
        g32.SelectObject(mem, bmp)
        if self.bmp_p is None:
            self.bmp_p = g32.CreateCompatibleBitmap(hdc, self.LARGURA, self.ALTURA)
            g32.SelectObject(self.mem_p, self.bmp_p)
            g32.SetStretchBltMode(self.mem_p, HALFTONE)
            g32.SetBrushOrgEx(self.mem_p, 0, 0, None)
        u32.ReleaseDC(hwnd, hdc)
        self.grande = (hwnd, mem, bmp, w, h)
        return mem

    def _regiao(self, hwnd, w, h, qual):
        """Retângulo (x, y, w, h) dentro da janela para o monitor escolhido."""
        if qual == "ambos":
            return 0, 0, w, h
        agora = time.monotonic()
        if self.mons is None or agora - self.mons_t > 10:
            self.mons, self.mons_t = monitores(), agora
        alvo = next((m for m, prim in self.mons if prim == (qual == "principal")), None)
        if not alvo:
            return 0, 0, w, h
        wr = W.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(wr))
        x0, y0 = max(0, alvo[0] - wr.left), max(0, alvo[1] - wr.top)
        x1, y1 = min(w, alvo[2] - wr.left), min(h, alvo[3] - wr.top)
        if x1 - x0 < 10 or y1 - y0 < 10:
            return 0, 0, w, h
        return x0, y0, x1 - x0, y1 - y0

    def _windows(self):
        p = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Themes\TranscodedWallpaper")
        try:
            mt = os.path.getmtime(p)
        except OSError:
            return None
        if self.windows_cache[0] != mt:
            with Image.open(p) as im:
                pequena = im.convert("RGB").resize((self.LARGURA, self.ALTURA),
                                                   Image.Resampling.BOX)
            self.windows_cache = (mt, pequena)
        return self.windows_cache[1]

    def _ler(self, alvo, flag, qual):
        """PrintWindow(alvo) → reduz no Windows → imagem 192×108 (ou None)."""
        r = W.RECT()
        u32.GetClientRect(alvo, ctypes.byref(r))
        w, h = r.right, r.bottom
        if w <= 0 or h <= 0:
            return None
        mem = self._buffers(alvo, w, h)
        if not u32.PrintWindow(alvo, mem, flag):
            return None
        x, y, cw, ch = self._regiao(alvo, w, h, qual)
        g32.StretchBlt(self.mem_p, 0, 0, self.LARGURA, self.ALTURA, mem, x, y, cw, ch, SRCCOPY)
        g32.GetDIBits(self.mem_p, self.bmp_p, 0, self.ALTURA, self.buf, ctypes.byref(self.bmi), 0)
        return Image.frombuffer("RGB", (self.LARGURA, self.ALTURA), self.buf,
                                "raw", "BGRX", 0, 1).copy()

    @staticmethod
    def _preta(img):
        return max(img.getextrema(), key=lambda e: e[1])[1] < 6

    def capturar(self, qual="principal"):
        """Devolve (imagem 192×108, fonte) ou (None, motivo).

        Dois jeitos de ler o Wallpaper Engine:
          - "janela": PrintWindow na janela dele. Rápido (~2 ms), funciona com vídeo.
          - "area": cenas/web usam DirectX e a janela volta PRETA; aí lemos a camada
            da área de trabalho com PW_RENDERFULLCONTENT (~20 ms). Janelas abertas
            continuam de fora; os ícones da área de trabalho entram, mas são pequenos.
        self.lento fica True no modo "area" (o laço ao vivo diminui o ritmo).
        """
        antigo = u32.SetThreadDpiAwarenessContext(PER_MONITOR_V2)
        try:
            agora = time.monotonic()
            if (not self.hwnd or agora - self.hwnd_t > 2 or not u32.IsWindow(self.hwnd)):
                novo, raiz = _janela_wallpaper_engine(com_raiz=True)
                if novo != self.hwnd:
                    self.modo = "janela"           # janela nova: tenta o jeito rápido primeiro
                self.hwnd, self.raiz, self.hwnd_t = novo, raiz, agora
            if self.hwnd:
                img = None
                if getattr(self, "modo", "janela") == "janela":
                    img = self._ler(self.hwnd, 0, qual)
                    if img is not None and self._preta(img) and self.raiz:
                        self.modo = "area"         # DirectX: a janela vem preta
                        img = None
                if img is None and self.modo == "area" and self.raiz:
                    img = self._ler(self.raiz, 2, qual)
                self.lento = self.modo == "area"
                if img is not None:
                    return img, "Wallpaper Engine" + (" (cena)" if self.lento else "")
                self.hwnd = None                     # falhou: procura de novo
            self.lento = False
            img = self._windows()
            if img is not None:
                return img, "Windows"
            return None, "papel de parede não encontrado"
        finally:
            if antigo:
                u32.SetThreadDpiAwarenessContext(antigo)


# ------------------------------------------------------------- escolha da cor
def cor_para_leds(img):
    """Escolhe a cor 'que representa' a imagem, pensando em LED:

    - agrupa a imagem em 8 cores;
    - dá nota = área × saturação² (cores vivas valem mais que cinza/preto);
    - descarta o que é quase preto;
    - no fim deixa a cor no brilho máximo (o brilho é controlado no app) e um pouco
      mais saturada, porque LED com cor 'lavada' parece branco.
    Se a imagem for toda cinza/preto-e-branco, devolve um branco quente.
    """
    peq = img.convert("RGB").resize((192, 54), Image.Resampling.BILINEAR)
    q = peq.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    paleta = q.getpalette()
    melhor, nota_melhor = None, 0.0
    total = peq.width * peq.height
    for qtd, idx in q.getcolors():
        r, g, b = paleta[idx * 3: idx * 3 + 3]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if v < 0.12:
            continue
        nota = (qtd / total) * (s ** 2) * (0.4 + v)
        if nota > nota_melhor:
            melhor, nota_melhor = (h, s, v), nota
    if not melhor or melhor[1] < 0.15:
        return (255, 214, 170)           # imagem sem cor: branco quente
    h, s, _ = melhor
    s = min(1.0, s * 1.35 + 0.1)
    r, g, b = colorsys.hsv_to_rgb(h, s, 1.0)
    return round(r * 255), round(g * 255), round(b * 255)


# ------------------------------------------------------------- cor por LED
def reduzir(img, largura=384):
    """Imagem pequena (rápida de processar) mantendo a proporção."""
    fator = max(1, img.width // largura)
    return img.reduce(fator) if fator > 1 else img


def preparar_layout(posicoes):
    """posicoes: [(led_id, cx, cy)] do iCUE (em mm, layout físico do dispositivo).

    Transforma em uma grade: cada x distinto vira uma coluna e cada y distinto uma
    linha. Ex.: RAM = 2 colunas (pentes) × 10 linhas; hub LINK = 210 colunas × 1 linha.
    Depois cada LED pega a MÉDIA da região correspondente do papel de parede.
    """
    xs = sorted({round(cx, 1) for _, cx, _ in posicoes})
    ys = sorted({round(cy, 1) for _, _, cy in posicoes})
    col = {x: i for i, x in enumerate(xs)}
    lin = {y: i for i, y in enumerate(ys)}
    leds = [(i, col[round(cx, 1)], lin[round(cy, 1)]) for i, cx, cy in posicoes]
    return len(xs), len(ys), leds


def realcar(rgb):
    """Papel de parede na tela fica 'apagado' em LED: puxa saturação e brilho,
    mas mantém o escuro escuro (céu noturno não vira cinza)."""
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    s = min(1.0, s * 1.6)
    v = v ** 0.6 if v > 0.03 else v
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, s, v))


def cores_por_led(img_pequena, layout):
    """Devolve [(led_id, (r, g, b))] para um dispositivo."""
    ncol, nlin, leds = layout
    grade = img_pequena.resize((ncol, nlin), Image.Resampling.BOX)
    px = grade.load()
    return [(i, realcar(px[c, l])) for i, c, l in leds]


def paleta_debug(img, n=8):
    peq = img.convert("RGB").resize((192, 54))
    q = peq.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    return sorted(((c, tuple(pal[i * 3:i * 3 + 3])) for c, i in q.getcolors()), reverse=True)


if __name__ == "__main__":
    import sys
    for qual in ("ambos", "principal", "secundario"):
        img, fonte = capturar(qual)
        if img is None:
            print(qual, "->", fonte)
            continue
        cor = cor_para_leds(img)
        print(f"{qual:<10} fonte={fonte} tamanho={img.size} cor=#{cor[0]:02x}{cor[1]:02x}{cor[2]:02x}")
        if qual == "ambos":
            print("   paleta:", [f"{n}x#{c[0]:02x}{c[1]:02x}{c[2]:02x}" for n, c in paleta_debug(img)])
        if len(sys.argv) > 1:
            base, ext = os.path.splitext(sys.argv[1])
            img.resize((img.width // 4, img.height // 4)).save(f"{base}_{qual}{ext}")
