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
import shutil
import sys
import threading
from ctypes import POINTER, byref, c_long, c_ulong, c_void_p, c_wchar_p
from logging.handlers import RotatingFileHandler

# Código/recursos: pasta do script, ou a pasta interna do executável (PyInstaller).
PASTA = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
# Dados do usuário (config, backup da MSI, log): sempre em %APPDATA%\RGB Sync,
# assim o executável pode ficar em qualquer lugar e atualizar sem perder nada.
def _pasta_appdata():
    """%APPDATA% pela API do Windows (não depende de variável de ambiente, que pode
    faltar quando o app é aberto pela tarefa agendada)."""
    try:
        import uuid
        guid = uuid.UUID("{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}")   # FOLDERID_RoamingAppData
        buf = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref((ctypes.c_byte * 16).from_buffer_copy(guid.bytes_le)), 0, None,
                ctypes.byref(buf)) == 0:
            caminho = buf.value
            ctypes.windll.ole32.CoTaskMemFree(buf)
            return caminho
    except Exception:
        pass
    return os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")


DADOS = os.path.join(_pasta_appdata(), "RGB Sync")
os.makedirs(DADOS, exist_ok=True)
# Migração única dos arquivos que antes ficavam junto do código.
_ANTIGA = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False)
                                          else __file__))
for _nome in ("config.json", "msi_backup.json"):
    _de, _para = os.path.join(_ANTIGA, _nome), os.path.join(DADOS, _nome)
    if os.path.exists(_de) and not os.path.exists(_para):
        shutil.copy2(_de, _para)

BACKUP_MSI = os.path.join(DADOS, "msi_backup.json")
LOG = os.path.join(DADOS, "rgb.log")

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
        self.chaves = {}         # device_id -> "corsair:<modelo>"
        self.desligados = set()  # chaves que o usuário tirou da sincronização
        self.erro = None

    def conectar(self, timeout=10):
        from cuesdk import (CueSdk, CorsairAccessLevel, CorsairDeviceFilter,
                            CorsairDeviceType, CorsairSessionState)
        self.dispositivos = []
        self.posicoes = {}       # device_id -> (modelo, [(led_id, cx, cy)])
        self.chaves = {}
        self._controlados = set()
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
            chave = f"corsair:{d.model}"
            n = 2
            while chave in self.chaves.values():          # dois aparelhos iguais
                chave, n = f"corsair:{d.model} #{n}", n + 1
            self.chaves[d.device_id] = chave
            self.dispositivos.append((d.device_id, d.model, ids))
            self.posicoes[d.device_id] = (d.model, posicoes)
            log.info("Corsair: %s, %d LEDs", d.model, len(ids))
        self._aplicar_controle()
        return True

    def _aplicar_controle(self):
        """Controle exclusivo SÓ de iluminação nos aparelhos ligados: os efeitos do
        iCUE param neles. Nos desligados, o controle volta pro iCUE (efeitos dele).
        Ventilação e bomba continuam sempre com o iCUE."""
        from cuesdk import CorsairAccessLevel
        if not hasattr(self, "_controlados"):
            self._controlados = set()
        for dev_id, modelo, _ in self.dispositivos:
            quer = self.chaves[dev_id] not in self.desligados
            if quer == (dev_id in self._controlados):
                continue                                   # nada mudou nesse aparelho
            if quer:
                err = self.sdk.request_control(
                    dev_id, CorsairAccessLevel.CAL_ExclusiveLightingControl)
                self._controlados.add(dev_id)
                log.info("Corsair: %s sincronizando (request_control=%s)", modelo, err)
            else:
                err = self.sdk.release_control(dev_id)
                self._controlados.discard(dev_id)
                log.info("Corsair: %s desligado da sincronização (%s)", modelo, err)

    def definir_desligados(self, chaves):
        self.desligados = {c for c in chaves if c.startswith("corsair:")}
        if self.sdk:
            self._aplicar_controle()

    def ativo(self, dev_id):
        return self.chaves.get(dev_id) not in self.desligados

    def listar(self):
        return [{"chave": self.chaves[d], "nome": m, "marca": "Corsair", "leds": len(ids),
                 "ativo": self.ativo(d)} for d, m, ids in self.dispositivos]

    def aplicar_por_led(self, mapa):
        """mapa: {device_id: [(led_id, (r, g, b)), ...]} — cada LED com sua cor."""
        from cuesdk import CorsairLedColor
        for dev_id, leds in mapa.items():
            if not self.ativo(dev_id):
                continue
            self.sdk.set_led_colors(dev_id, [CorsairLedColor(id=i, r=c[0], g=c[1], b=c[2], a=255)
                                             for i, c in leds])

    def aplicar(self, r, g, b):
        from cuesdk import CorsairLedColor
        res = {}
        for dev_id, modelo, ids in self.dispositivos:
            if not self.ativo(dev_id):
                continue
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
        self.nomes_led = {}      # tipo -> [nome de cada zona] (ex.: JRGB1, nome da GPU)
        self.desligados = set()
        self.erro = None

    def definir_desligados(self, chaves):
        self.desligados = {c for c in chaves if c.startswith("msi:")}

    def listar(self):
        out = []
        for tipo, n, _ in self.dispositivos:
            nomes = self.nomes_led.get(tipo, [])
            nome = NOMES_MSI.get(tipo, tipo)
            if tipo == "MSI_VGA" and nomes and nomes[0]:
                nome = f"{nome} ({nomes[0]})"
            elif tipo == "MSI_MB" and nomes:
                nome = f"{nome} ({', '.join(nomes)})"
            out.append({"chave": f"msi:{tipo}", "nome": nome, "marca": "MSI", "leds": n,
                        "ativo": f"msi:{tipo}" not in self.desligados})
        return out

    def conectar(self):
        if not ctypes.windll.shell32.IsUserAnAdmin():
            self.erro = "precisa rodar como administrador"
            log.error("MSI: %s", self.erro)
            return False
        self.dispositivos = []
        self.nomes_led = {}
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
                self.nomes_led.setdefault(tipo, []).append(nome_led)
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
            if f"msi:{tipo}" in self.desligados:
                continue
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
        self.desligados = set()      # chaves "corsair:..."/"msi:..." fora da sincronização

    def definir_desligados(self, chaves):
        self.desligados = set(chaves)
        for b in self.backends:
            try:
                b.definir_desligados(self.desligados)
            except Exception:
                log.exception("falha ao (des)ligar dispositivos em %s", b.nome)

    def listar(self):
        """Todos os dispositivos que o app controla (ligados ou não)."""
        out = []
        for b in self.ativos:
            out.extend(b.listar())
        return out

    def recarregar(self):
        """Desconecta tudo e conecta do zero (acha aparelhos novos, conserta estado
        estranho). Devolve o status da conexão."""
        log.info("recarregando tudo")
        self.desconectar()
        self.backends = [Corsair(), MSI()]
        return self.conectar()

    def conectar(self):
        """Conecta as marcas que ainda não estão ativas (pode ser chamado de novo
        para tentar outra vez — útil no boot, quando o iCUE demora a subir)."""
        status = {}
        for b in self.backends:
            if b in self.ativos:
                status[b.nome] = "ok"
                continue
            try:
                b.definir_desligados(self.desligados)
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
