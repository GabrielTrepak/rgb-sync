"""
Núcleo do controle de RGB.

Regras do projeto:
  - Só mexe em ILUMINAÇÃO. Nada de ventilação, bomba, firmware ou SMBus direto.
  - Corsair: iCUE SDK oficial. Ao fechar o app, o iCUE volta sozinho pra iluminação dele.
  - MSI: Mystic Light SDK oficial (precisa de administrador). A MSI GUARDA a cor no
    dispositivo, então na primeira execução fazemos backup do estado original
    (msi_backup.json) para poder restaurar.

Teste por linha de comando (como administrador):
  python rgb_core.py --cor 0080ff --segundos 20
  python rgb_core.py --restaurar-msi
"""

import ctypes
import json
import logging
import os
import threading
from ctypes import POINTER, byref, c_long, c_ulong, c_void_p, c_wchar_p

PASTA = os.path.dirname(os.path.abspath(__file__))
BACKUP_MSI = os.path.join(PASTA, "msi_backup.json")
LOG = os.path.join(PASTA, "rgb.log")

from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[RotatingFileHandler(LOG, maxBytes=1_000_000, backupCount=1, encoding="utf-8")],
)
log = logging.getLogger("rgb")


def hex_para_rgb(h):
    h = h.strip().lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# =========================================================== Corsair (iCUE SDK)
class Corsair:
    nome = "Corsair (iCUE)"

    def __init__(self):
        self.sdk = None
        self.dispositivos = []   # [(device_id, modelo, [led_ids])]
        self.posicoes = {}
        self.erro = None

    def conectar(self, timeout=10):
        from cuesdk import (CueSdk, CorsairAccessLevel, CorsairDeviceFilter,
                            CorsairDeviceType, CorsairSessionState)
        self.dispositivos = []
        self.posicoes = {}       # device_id -> (modelo, [(led_id, cx, cy)])
        self.sdk = CueSdk()
        ok = threading.Event()

        def on_state(evt):
            if evt.state == CorsairSessionState.CSS_Connected:
                ok.set()

        self.sdk.connect(on_state)
        if not ok.wait(timeout):
            self.erro = "iCUE ainda não respondeu (tentando de novo)"
            log.error("Corsair: %s", self.erro)
            self.desconectar()
            return False
        self.erro = None

        devs, _ = self.sdk.get_devices(
            CorsairDeviceFilter(device_type_mask=CorsairDeviceType.CDT_All))
        for d in devs or []:
            leds, _ = self.sdk.get_led_positions(d.device_id)
            ids = [l.id for l in (leds or [])]
            posicoes = [(l.id, l.cx, l.cy) for l in (leds or [])]
            # Controle exclusivo SÓ de iluminação: os efeitos do iCUE param enquanto o
            # app estiver aberto. Ventilação e bomba continuam com o iCUE.
            err = self.sdk.request_control(
                d.device_id, CorsairAccessLevel.CAL_ExclusiveLightingControl)
            log.info("Corsair: %s, %d LEDs, request_control=%s", d.model, len(ids), err)
            self.dispositivos.append((d.device_id, d.model, ids))
            self.posicoes[d.device_id] = (d.model, posicoes)
        return True

    def aplicar_por_led(self, mapa):
        """mapa: {device_id: [(led_id, (r, g, b)), ...]} — cada LED com sua cor."""
        from cuesdk import CorsairLedColor
        for dev_id, leds in mapa.items():
            self.sdk.set_led_colors(dev_id, [CorsairLedColor(id=i, r=c[0], g=c[1], b=c[2], a=255)
                                             for i, c in leds])

    def aplicar(self, r, g, b):
        from cuesdk import CorsairLedColor
        res = {}
        for dev_id, modelo, ids in self.dispositivos:
            cores = [CorsairLedColor(id=i, r=r, g=g, b=b, a=255) for i in ids]
            err = self.sdk.set_led_colors(dev_id, cores)
            res[modelo] = str(err).split(".")[-1]
        log.info("Corsair aplicar #%02x%02x%02x -> %s", r, g, b, res)
        return res

    def desconectar(self):
        if not self.sdk:
            return
        for dev_id, _, _ in self.dispositivos:
            self.sdk.release_control(dev_id)
        # Workaround do bug do cuesdk 4.0.84 (crash no disconnect): segura o callback.
        handler = getattr(self.sdk, "session_state_changed_event_handler", None)
        self.sdk.disconnect()
        del handler
        self.sdk = None


# =========================================================== MSI (Mystic Light SDK)
MLAPI_DLL = r"C:\Program Files\Corsair\Corsair iCUE5 Software\plugins\MSI\MysticLight_SDK_x64.dll"
MLAPI_ERROS = {0: "OK", -1: "ERRO", -2: "TIMEOUT", -3: "NAO_IMPLEMENTADO",
               -4: "NAO_INICIALIZADO", -101: "ARG_INVALIDO",
               -102: "DISP_NAO_ENCONTRADO", -103: "NAO_SUPORTADO"}
# GPU usa "Steady"; os headers da placa-mãe chamam a cor fixa de "NoAnimation".
ESTILOS_FIXOS = ["Steady", "NoAnimation", "Static", "Always On", "AlwaysOn"]
NOMES_MSI = {"MSI_MB": "Placa-mãe", "MSI_VGA": "Placa de vídeo"}

_oa = ctypes.windll.oleaut32
_oa.SysAllocString.restype = c_void_p
_oa.SysAllocString.argtypes = [c_wchar_p]
_oa.SysFreeString.argtypes = [c_void_p]
_oa.SafeArrayGetLBound.argtypes = [c_void_p, ctypes.c_uint, POINTER(c_long)]
_oa.SafeArrayGetUBound.argtypes = [c_void_p, ctypes.c_uint, POINTER(c_long)]
_oa.SafeArrayGetElement.argtypes = [c_void_p, POINTER(c_long), c_void_p]
_oa.SafeArrayDestroy.argtypes = [c_void_p]


def _bstr(s):
    return c_void_p(_oa.SysAllocString(s))


def _ler_bstr(p):
    if not p.value:
        return ""
    s = ctypes.wstring_at(p.value)
    _oa.SysFreeString(p)
    return s


def _ler_safearray(psa):
    if not psa.value:
        return []
    lb, ub = c_long(), c_long()
    _oa.SafeArrayGetLBound(psa, 1, byref(lb))
    _oa.SafeArrayGetUBound(psa, 1, byref(ub))
    vals = []
    for i in range(lb.value, ub.value + 1):
        idx = c_long(i)
        b = c_void_p()
        _oa.SafeArrayGetElement(psa, byref(idx), byref(b))
        vals.append(_ler_bstr(b))
    _oa.SafeArrayDestroy(psa)
    return vals


class MSI:
    nome = "MSI (Mystic Light)"

    def __init__(self):
        self.dll = None
        self.dispositivos = []   # [(tipo, n_leds, {idx: estilo_fixo})]
        self.erro = None

    def conectar(self):
        if not ctypes.windll.shell32.IsUserAnAdmin():
            self.erro = "precisa rodar como administrador"
            log.error("MSI: %s", self.erro)
            return False
        self.dispositivos = []
        if self.dll is None:
            os.add_dll_directory(os.path.dirname(MLAPI_DLL))
        d = ctypes.WinDLL(MLAPI_DLL)
        P = POINTER(c_void_p)
        d.MLAPI_GetDeviceInfo.argtypes = [P, P]
        d.MLAPI_GetLedInfo.argtypes = [c_void_p, c_ulong, P, P]
        d.MLAPI_GetLedColor.argtypes = [c_void_p, c_ulong, POINTER(c_ulong),
                                        POINTER(c_ulong), POINTER(c_ulong)]
        d.MLAPI_GetLedStyle.argtypes = [c_void_p, c_ulong, P]
        d.MLAPI_SetLedColor.argtypes = [c_void_p, c_ulong, c_ulong, c_ulong, c_ulong]
        d.MLAPI_SetLedStyle.argtypes = [c_void_p, c_ulong, c_void_p]
        self.dll = d

        r = d.MLAPI_Initialize()
        if r != 0:
            self.erro = f"MLAPI_Initialize: {MLAPI_ERROS.get(r, r)}"
            log.error("MSI: %s", self.erro)
            return False
        tipos, contagens = c_void_p(), c_void_p()
        r = d.MLAPI_GetDeviceInfo(byref(tipos), byref(contagens))
        if r != 0:
            self.erro = f"MLAPI_GetDeviceInfo: {MLAPI_ERROS.get(r, r)}"
            log.error("MSI: %s", self.erro)
            return False
        for tipo, n in zip(_ler_safearray(tipos), _ler_safearray(contagens)):
            n = int(n)
            estilos = {}
            for i in range(n):
                nome, lista = c_void_p(), c_void_p()
                bt = _bstr(tipo)
                d.MLAPI_GetLedInfo(bt, i, byref(nome), byref(lista))
                _oa.SysFreeString(bt)
                nome_led = _ler_bstr(nome)
                disponiveis = _ler_safearray(lista)
                fixo = next((e for e in ESTILOS_FIXOS if e in disponiveis), None)
                estilos[i] = fixo
                log.info("MSI: %s[%d] '%s' estilos=%s -> fixo=%s",
                         tipo, i, nome_led, disponiveis, fixo)
            self.dispositivos.append((tipo, n, estilos))
        self._backup_se_preciso()
        return True

    def _ler_estado(self, tipo, i):
        bt = _bstr(tipo)
        est = c_void_p()
        self.dll.MLAPI_GetLedStyle(bt, i, byref(est))
        r, g, b = c_ulong(), c_ulong(), c_ulong()
        self.dll.MLAPI_GetLedColor(bt, i, byref(r), byref(g), byref(b))
        _oa.SysFreeString(bt)
        return {"estilo": _ler_bstr(est), "cor": [r.value, g.value, b.value]}

    def _backup_se_preciso(self):
        if os.path.exists(BACKUP_MSI):
            return
        estado = {tipo: {str(i): self._ler_estado(tipo, i) for i in range(n)}
                  for tipo, n, _ in self.dispositivos}
        with open(BACKUP_MSI, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False, indent=2)
        log.info("MSI: backup do estado original salvo: %s", estado)

    def _set(self, tipo, i, estilo, r, g, b):
        bt = _bstr(tipo)
        re = 0
        if estilo:
            bs = _bstr(estilo)
            re = self.dll.MLAPI_SetLedStyle(bt, i, bs)
            _oa.SysFreeString(bs)
        rc = self.dll.MLAPI_SetLedColor(bt, i, r, g, b)
        _oa.SysFreeString(bt)
        return re, rc

    def aplicar(self, r, g, b):
        res = {}
        for tipo, n, estilos in self.dispositivos:
            codigos = [self._set(tipo, i, estilos[i], r, g, b) for i in range(n)]
            pior = min(min(c) for c in codigos) if codigos else 0
            res[NOMES_MSI.get(tipo, tipo)] = MLAPI_ERROS.get(pior, pior)
            log.info("MSI aplicar %s #%02x%02x%02x -> %s", tipo, r, g, b, codigos)
        return res

    def restaurar(self):
        if not os.path.exists(BACKUP_MSI):
            return "sem backup"
        with open(BACKUP_MSI, encoding="utf-8") as f:
            estado = json.load(f)
        for tipo, leds in estado.items():
            for i, e in leds.items():
                codes = self._set(tipo, int(i), e["estilo"] or None, *e["cor"])
                log.info("MSI restaurar %s[%s] %s -> %s", tipo, i, e, codes)
        return "restaurado"

    def desconectar(self):
        if self.dll and hasattr(self.dll, "MLAPI_Release"):
            self.dll.MLAPI_Release()
        self.dll = None


# =========================================================== controlador
class Controlador:
    def __init__(self):
        self.backends = [Corsair(), MSI()]
        self.ativos = []

    def conectar(self):
        """Conecta as marcas que ainda não estão ativas (pode ser chamado de novo
        para tentar outra vez — útil no boot, quando o iCUE demora a subir)."""
        status = {}
        for b in self.backends:
            if b in self.ativos:
                status[b.nome] = "ok"
                continue
            try:
                ok = b.conectar()
            except Exception as e:  # nunca derrubar o app por causa de uma marca
                log.exception("falha ao conectar %s", b.nome)
                b.erro, ok = str(e), False
            if ok:
                self.ativos.append(b)
            status[b.nome] = "ok" if ok else b.erro
        return status

    def corsair(self):
        return next((b for b in self.ativos if isinstance(b, Corsair)), None)

    def aplicar(self, r, g, b, so_corsair=False, so_msi=False):
        """so_corsair: passos intermediários de transição (a MSI leva ~0,6 s por
        mudança, então ela só recebe a cor final). so_msi: modo papel de parede,
        em que a Corsair é pintada LED a LED e a MSI recebe a cor geral."""
        res = {}
        for be in self.ativos:
            if so_corsair and not isinstance(be, Corsair):
                continue
            if so_msi and not isinstance(be, MSI):
                continue
            try:
                res.update(be.aplicar(r, g, b))
            except Exception as e:
                log.exception("falha ao aplicar em %s", be.nome)
                res[be.nome] = f"erro: {e}"
        return res

    def restaurar_msi(self):
        for be in self.ativos:
            if isinstance(be, MSI):
                return be.restaurar()
        return "MSI não conectada"

    def desconectar(self):
        for be in self.ativos:
            try:
                be.desconectar()
            except Exception:
                log.exception("falha ao desconectar %s", be.nome)
        self.ativos = []


if __name__ == "__main__":
    import argparse
    import time
    ap = argparse.ArgumentParser()
    ap.add_argument("--cor", help="ex.: 0080ff")
    ap.add_argument("--segundos", type=int, default=15)
    ap.add_argument("--restaurar-msi", action="store_true")
    a = ap.parse_args()
    c = Controlador()
    log.info("=== CLI: %s", vars(a))
    log.info("conectar: %s", c.conectar())
    try:
        if a.restaurar_msi:
            log.info("restaurar: %s", c.restaurar_msi())
        if a.cor:
            log.info("resultado: %s", c.aplicar(*hex_para_rgb(a.cor)))
            time.sleep(a.segundos)
    finally:
        c.desconectar()
        log.info("=== CLI fim")
