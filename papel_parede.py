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
def _janela_wallpaper_engine():
    achadas = []

    def cb(h, _):
        cls = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(h, cls, 64)
        if cls.value.startswith("WPE") and cls.value.endswith("Wallpaper") \
                and u32.IsWindowVisible(h):
            achadas.append(h)
        return True

    for raiz in ("Progman",):
        p = u32.FindWindowW(raiz, None)
        if p:
            u32.EnumChildWindows(p, EnumProc(cb), 0)
    # Em algumas versões do Windows ele fica dentro de um WorkerW de topo
    if not achadas:
        def topo(h, _):
            cls = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(h, cls, 64)
            if cls.value == "WorkerW":
                u32.EnumChildWindows(h, EnumProc(cb), 0)
            return True
        u32.EnumWindows(EnumProc(topo), 0)
    return achadas[0] if achadas else None


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
