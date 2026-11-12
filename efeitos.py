"""
Efeitos do RGB Sync: respiração, onda, ciclo de cores e temperatura.

- cor_led(...) calcula a cor de um LED num instante t (Corsair e teclado são
  animados quadro a quadro pelo app).
- A MSI (lenta: ~0,6 s por mudança) usa os efeitos NATIVOS dela, com a mesma cor e
  velocidade — ver ESTILOS_MSI.
- Sensores: temperatura da GPU (NVML, direto do driver NVIDIA) e uso da CPU
  (GetSystemTimes do Windows). Nenhum driver extra é instalado.
"""

import colorsys
import ctypes
import math
import time
from ctypes import wintypes as W

from rgb_core import log

TIPOS = {"Respiração": "respiracao", "Onda": "onda", "Ciclo": "ciclo",
         "Temperatura": "temperatura"}
VELOCIDADES = {"Lenta": "lenta", "Média": "media", "Rápida": "rapida"}
FONTES = {"Temperatura da GPU": "gpu", "Uso da CPU": "cpu"}

# período (s) de cada efeito por velocidade
PERIODO = {
    "respiracao": {"lenta": 6.0, "media": 3.5, "rapida": 1.8},
    "onda": {"lenta": 8.0, "media": 4.0, "rapida": 2.0},
    "ciclo": {"lenta": 20.0, "media": 10.0, "rapida": 4.0},
}
NIVEL_VEL = {"lenta": 0.0, "media": 0.5, "rapida": 1.0}     # pra MSI (0..max)

# Efeito nativo da MSI pra cada efeito nosso: (estilo na placa-mãe, estilo na GPU)
ESTILOS_MSI = {
    "respiracao": (["Breathing"], ["Breath"]),
    "onda": (["Rainbow", "ColorRing"], ["Wave", "Flowing", "ColorCycle"]),
    "ciclo": (["Rainbow", "ColorRing"], ["ColorCycle", "Wave"]),
}


def _hsv(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (r * 255, g * 255, b * 255)


def cor_temperatura(n):
    """n de 0 (frio) a 1 (quente): azul → ciano → verde → amarelo → laranja → vermelho."""
    n = min(1.0, max(0.0, n))
    return _hsv(0.62 * (1 - n))


def normalizar(fonte, valor):
    if valor is None:
        return 0.0
    if fonte == "gpu":                        # 35 °C = frio, 85 °C = quente
        return (valor - 35) / 50
    return valor / 100                        # uso da CPU em %


def cor_led(tipo, t, x, cor_base, velocidade, valor_norm=0.0):
    """Cor (float 0..255) de um LED na posição x (0..1, esquerda→direita) no tempo t."""
    if tipo == "respiracao":
        p = PERIODO["respiracao"][velocidade]
        f = 0.06 + 0.94 * (0.5 - 0.5 * math.cos(2 * math.pi * t / p)) ** 1.6
        return tuple(c * f for c in cor_base)
    if tipo == "ciclo":
        return _hsv(t / PERIODO["ciclo"][velocidade])
    if tipo == "onda":
        return _hsv(x * 0.9 - t / PERIODO["onda"][velocidade])
    if tipo == "temperatura":
        return cor_temperatura(valor_norm)
    return cor_base


# ============================================================= sensores
class _FT(ctypes.Structure):
    _fields_ = [("baixo", W.DWORD), ("alto", W.DWORD)]

    def valor(self):
        return (self.alto << 32) | self.baixo


class Sensores:
    """Lê no máximo 1x por segundo (o que for pedido) e guarda o último valor."""

    def __init__(self):
        self._nvml = None
        self._gpu = None
        self._cpu_ant = None
        self._cache = {}
        self.nome_gpu = None
        try:
            nv = ctypes.WinDLL("nvml.dll")
            if nv.nvmlInit_v2() == 0:
                h = ctypes.c_void_p()
                if nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(h)) == 0:
                    self._nvml, self._gpu = nv, h
                    nome = ctypes.create_string_buffer(96)
                    nv.nvmlDeviceGetName(h, nome, 96)
                    self.nome_gpu = nome.value.decode(errors="replace")
        except Exception as e:
            log.info("NVML indisponível (%s)", e)

    def disponiveis(self):
        return {"gpu": self._nvml is not None, "cpu": True}

    def _ler_gpu(self):
        if not self._nvml:
            return None
        t = ctypes.c_uint()
        if self._nvml.nvmlDeviceGetTemperature(self._gpu, 0, ctypes.byref(t)) == 0:
            return float(t.value)
        return None

    def _ler_cpu(self):
        ocioso, kernel, usuario = _FT(), _FT(), _FT()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(ocioso), ctypes.byref(kernel),
                                              ctypes.byref(usuario))
        agora = (ocioso.valor(), kernel.valor() + usuario.valor())
        ant, self._cpu_ant = self._cpu_ant, agora
        if not ant or agora[1] == ant[1]:
            return self._cache.get("cpu", (0, None))[1]
        return max(0.0, min(100.0, 100.0 * (1 - (agora[0] - ant[0]) / (agora[1] - ant[1]))))

    def ler(self, fonte):
        t, v = self._cache.get(fonte, (0, None))
        if time.monotonic() - t >= 1.0:
            v = self._ler_gpu() if fonte == "gpu" else self._ler_cpu()
            self._cache[fonte] = (time.monotonic(), v)
        return v

    def texto(self, fonte):
        v = self._cache.get(fonte, (0, None))[1]
        if v is None:
            return "—"
        return f"{v:.0f} °C" if fonte == "gpu" else f"{v:.0f}%"
