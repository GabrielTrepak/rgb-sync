"""
Luzes da casa (Tuya / Smart Life / Ekaza), controladas DIRETO pela rede local.

- As chaves locais vêm do devices.json gerado pelo `tinytuya wizard` e são copiadas pra
  %APPDATA%\\RGB Sync\\luzes.json (fora do projeto e do GitHub).
- Cada luz tem uma thread própria: os comandos são "o último vale" (arrastar um slider
  não enfileira 50 comandos) e saem no máximo ~4 por segundo — lâmpadas Tuya não gostam
  de mais que isso.
- A cada 15 s (com a aba aberta) lê o estado real, pra refletir mudanças feitas pelo celular.
- Se a luz mudar de IP (roteador), procura de novo pelo ID na rede.

DPs (padrão Tuya "v2" para luzes): 20 liga/desliga · 21 modo (white/colour/scene/music)
· 22 brilho 10..1000 · 23 temperatura 0 (quente)..1000 (fria) · 24 cor HHHHSSSSVVVV.
"""

import colorsys
import json
import os
import threading
import time

from rgb_core import DADOS, log

ARQUIVO = os.path.join(DADOS, "luzes.json")
CATEGORIAS_LUZ = {"dj", "dd", "xdd", "fwd", "dc", "fsd", "tyndj", "gyd", "mbd"}


# ============================================================= importar do tinytuya wizard
def lugares_devices_json():
    casa = os.path.expanduser("~")
    return [os.path.join(os.getcwd(), "devices.json"),
            os.path.join(casa, "Documents", "RGB Sync", "devices.json"),
            os.path.join(DADOS, "devices.json")]


def importar(caminho):
    """Lê o devices.json (e o snapshot.json ao lado, que tem o IP) e guarda só as luzes
    em luzes.json. Devolve a quantidade importada."""
    devs = json.load(open(caminho, encoding="utf-8"))
    snap = {}
    sp = os.path.join(os.path.dirname(caminho), "snapshot.json")
    if os.path.exists(sp):
        try:
            snap = {d.get("id"): d for d in json.load(open(sp, encoding="utf-8")).get("devices", [])}
        except Exception:
            pass
    atuais = {l["id"]: l for l in ler()}
    for d in devs:
        codigos = {v.get("code") for v in (d.get("mapping") or {}).values()}
        if d.get("category") not in CATEGORIAS_LUZ and "switch_led" not in codigos:
            continue
        s = snap.get(d["id"], {})
        atuais[d["id"]] = {
            "id": d["id"], "nome": d.get("name") or d.get("product_name") or "Luz",
            "produto": d.get("product_name", ""), "chave": d.get("key", ""),
            "ip": s.get("ip") or d.get("ip") or atuais.get(d["id"], {}).get("ip", ""),
            "versao": float(s.get("ver") or d.get("version") or 3.3),
            "cor": "colour_data_v2" in codigos or "colour_data" in codigos,
            "v2": "bright_value_v2" in codigos or "colour_data_v2" in codigos,
        }
    salvar(list(atuais.values()))
    log.info("luzes importadas de %s: %s", caminho, [l["nome"] for l in atuais.values()])
    return len(atuais)


def ler():
    try:
        return json.load(open(ARQUIVO, encoding="utf-8"))
    except Exception:
        return []


def salvar(luzes):
    with open(ARQUIVO, "w", encoding="utf-8") as f:
        json.dump(luzes, f, ensure_ascii=False, indent=2)


def importar_automatico():
    """Na primeira vez, se achar um devices.json conhecido, importa sozinho."""
    if ler():
        return 0
    for c in lugares_devices_json():
        if os.path.exists(c):
            try:
                return importar(c)
            except Exception:
                log.exception("importar luzes de %s", c)
    return 0


# ============================================================= conversões
def dps_cor(rgb, brilho_pct, v2=True):
    """(r, g, b) + brilho 0..100 → DPs de cor."""
    h, s, _v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    v = max(10, round(brilho_pct * 10))
    if v2:
        cor = "%04x%04x%04x" % (round(h * 360), round(s * 1000), v)
    else:
        cor = "%04x%02x%02x" % (round(h * 360), round(s * 255), max(25, round(brilho_pct * 2.55)))
    return {"20": True, "21": "colour", "24": cor}


def dps_branca(brilho_pct, temp_pct, v2=True):
    """brilho 0..100, temperatura 0 (quente)..100 (fria) → DPs de branco."""
    if v2:
        return {"20": True, "21": "white", "22": max(10, round(brilho_pct * 10)),
                "23": round(temp_pct * 10)}
    return {"20": True, "21": "white", "22": max(25, round(brilho_pct * 2.55)),
            "23": round(temp_pct * 2.55)}


def ler_estado(dps, v2=True):
    """DPs → {"ligada", "modo", "brilho", "temp", "rgb"} pra interface."""
    esc = 1000 if v2 else 255
    est = {"ligada": bool(dps.get("20", False)), "modo": dps.get("21", "white"),
           "brilho": round(int(dps.get("22", esc)) / esc * 100),
           "temp": round(int(dps.get("23", 0)) / esc * 100), "rgb": None}
    c = dps.get("24")
    if isinstance(c, str) and len(c) == 12 and v2:
        h, s, v = int(c[0:4], 16), int(c[4:8], 16), int(c[8:12], 16)
        r, g, b = colorsys.hsv_to_rgb(h / 360, s / 1000, 1.0)
        est["rgb"] = (round(r * 255), round(g * 255), round(b * 255))
        if est["modo"] == "colour":
            est["brilho"] = round(v / 10)
    return est


# ============================================================= uma luz
class Luz(threading.Thread):
    INTERVALO = 0.25          # no máximo ~4 comandos por segundo
    LER_A_CADA = 15.0

    def __init__(self, info, ao_estado, ao_ip=None):
        super().__init__(daemon=True)
        self.info = info
        self.ao_estado = ao_estado       # (id, estado | None se offline)
        self.ao_ip = ao_ip
        self._pendente = {}
        self._trava = threading.Lock()
        self._acordar = threading.Event()
        self._parar = threading.Event()
        self._dev = None
        self.dps = {}                    # último estado conhecido
        self.online = None
        self.vigiar = False              # a interface liga quando a aba está aberta
        self._ultimo_envio = 0.0
        self._ultima_leitura = 0.0

    # ---- comandos (de qualquer thread)
    def enviar(self, dps):
        with self._trava:
            self._pendente.update(dps)
        self._acordar.set()

    def ligar(self, sim):
        self.enviar({"20": bool(sim)})

    def branca(self, brilho, temp):
        self.enviar(dps_branca(brilho, temp, self.info.get("v2", True)))

    def cor(self, rgb, brilho):
        if sum(rgb) < 8:
            self.enviar({"20": False})
        else:
            self.enviar(dps_cor(rgb, brilho, self.info.get("v2", True)))

    def foto(self):
        """Estado atual pra restaurar depois (liga/desliga, modo, brilho, temp, cor)."""
        return {k: v for k, v in self.dps.items() if k in ("20", "21", "22", "23", "24")}

    def restaurar(self, foto):
        if foto:
            liga = foto.get("20", True)
            resto = {k: v for k, v in foto.items() if k != "20"}
            self.enviar(dict(resto, **{"20": True}) if liga else {"20": False})

    def ler_agora(self):
        self._ultima_leitura = 0.0
        self._acordar.set()

    def parar(self):
        self._parar.set()
        self._acordar.set()

    # ---- thread
    def _conectar(self):
        import tinytuya
        d = tinytuya.BulbDevice(self.info["id"], self.info.get("ip") or "Auto",
                                self.info["chave"], version=self.info.get("versao", 3.3))
        d.set_socketPersistent(True)
        d.set_socketTimeout(3)
        d.set_socketRetryLimit(1)
        self._dev = d

    def _redescobrir(self):
        """IP mudou? Procura a luz pelo ID na rede (escutando os anúncios dela)."""
        try:
            import tinytuya
            achado = tinytuya.find_device(self.info["id"])
            ip = (achado or {}).get("ip")
            if ip and ip != self.info.get("ip"):
                log.info("luz %s: IP mudou %s → %s", self.info["nome"], self.info.get("ip"), ip)
                self.info["ip"] = ip
                if self.ao_ip:
                    self.ao_ip(self.info["id"], ip)
                self._dev = None
                return True
        except Exception:
            log.exception("redescobrir luz")
        return False

    def _marcar(self, online, dps=None, avisar=True):
        """avisar=False: comando que NÓS mandamos — só guarda o estado, sem pedir pra
        interface se redesenhar (ela já mostra o que o usuário escolheu)."""
        if dps:
            self.dps.update({str(k): v for k, v in dps.items()})
        if online != self.online or (dps and avisar):
            self.online = online
            self.ao_estado(self.info["id"],
                           ler_estado(self.dps, self.info.get("v2", True)) if online else None)

    def run(self):
        falhas = 0
        while not self._parar.is_set():
            self._acordar.wait(1.0)
            self._acordar.clear()
            if self._parar.is_set():
                break
            agora = time.monotonic()
            with self._trava:
                pend, self._pendente = self._pendente, {}
            ler = (self.vigiar or self.online is None) and \
                agora - self._ultima_leitura >= self.LER_A_CADA
            if not pend and not ler:
                continue
            try:
                if self._dev is None:
                    self._conectar()
                if pend:
                    espera = self.INTERVALO - (agora - self._ultimo_envio)
                    if espera > 0:
                        time.sleep(espera)
                        with self._trava:                # chegou mais coisa nesse meio-tempo
                            pend.update(self._pendente)
                            self._pendente = {}
                    r = self._dev.set_multiple_values(pend)
                    self._ultimo_envio = time.monotonic()
                    if isinstance(r, dict) and r.get("Error"):
                        raise IOError(r.get("Error"))
                    self._marcar(True, pend, avisar=False)
                if ler:
                    self._ultima_leitura = time.monotonic()
                    st = self._dev.status()
                    if isinstance(st, dict) and "dps" in st:
                        self._marcar(True, st["dps"])
                    elif isinstance(st, dict) and st.get("Error"):
                        raise IOError(st.get("Error"))
                falhas = 0
            except Exception as e:
                falhas += 1
                log.warning("luz %s: %s", self.info["nome"], e)
                self._dev = None
                if pend:                                  # tenta de novo daqui a pouco
                    with self._trava:
                        self._pendente = dict(pend, **self._pendente)
                if falhas == 2 and self._redescobrir():
                    self._acordar.set()
                    continue
                self._marcar(False)
                self._parar.wait(min(30, 2 * falhas))
                self._acordar.set()
        try:
            if self._dev:
                self._dev.close()
        except Exception:
            pass
