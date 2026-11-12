"""
Motor do RGB Sync (sem interface):

- configuração do usuário (%APPDATA%\\RGB Sync\\config.json);
- instância única (a 2ª cópia só pede pra 1ª mostrar a janela);
- inicialização com o Windows (tarefa agendada elevada);
- Trabalhador: a thread que fala com os SDKs e roda o modo papel de parede ao vivo.
"""

import ctypes
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time

from PIL import ImageChops, ImageStat

import efeitos
from papel_parede import Capturador, cor_para_leds, cores_por_led, preparar_layout
from rgb_core import DADOS, Controlador, _pasta_appdata, log

CONFIG = os.path.join(DADOS, "config.json")
PORTA_UNICA = 47652          # só para a 2ª cópia avisar a 1ª: "mostre a janela"
RETENTATIVAS = 18            # 18 x 10 s = 3 min tentando conectar no boot
TAREFA = "RGB Sync"
SEM_JANELA = subprocess.CREATE_NO_WINDOW

PADRAO = {"modo": "papel_parede", "monitor": "principal", "cor": "#0050ff", "brilho": 100,
          "efeito": "respiracao", "velocidade": "media", "fonte_temp": "gpu"}


# ============================================================= configuração
def ler_config():
    cfg = dict(PADRAO)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def salvar_config(cfg):
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        log.exception("falha ao salvar config")


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


# ============================================================= instância única
def ja_esta_rodando():
    """Se já existe uma cópia, pede pra ela mostrar a janela e devolve True."""
    try:
        with socket.create_connection(("127.0.0.1", PORTA_UNICA), timeout=1) as s:
            s.sendall(b"mostrar")
        return True
    except OSError:
        return False


def pedir_para_sair():
    """Fecha a cópia que está rodando (usado ao instalar uma versão nova)."""
    try:
        with socket.create_connection(("127.0.0.1", PORTA_UNICA), timeout=1) as s:
            s.sendall(b"sair")
        return True
    except OSError:
        return False


def ouvir_outras_copias(ao_mostrar, ao_sair=None, ao_comando=None):
    srv = socket.socket()
    srv.bind(("127.0.0.1", PORTA_UNICA))
    srv.listen(1)

    def loop():
        while True:
            conn, _ = srv.accept()
            with conn:
                msg = conn.recv(256)
                if msg == b"mostrar":
                    ao_mostrar()
                elif msg == b"sair" and ao_sair:
                    ao_sair()
                elif msg.startswith(b"aba:") and ao_mostrar:   # abre numa aba (atalhos/testes)
                    ao_mostrar(msg[4:].decode("utf-8", "replace"))
                elif msg.startswith(b"cmd:") and ao_comando:   # controle externo
                    ao_comando(msg[4:].decode("utf-8", "replace"))
                elif msg == b"diag":                     # diagnóstico local
                    import logging
                    info = {"pid": os.getpid(), "exe": sys.executable, "dados": CONFIG,
                            "admin": e_admin(), "APPDATA": os.environ.get("APPDATA"),
                            "cwd": os.getcwd(),
                            "handlers": [repr(h) for h in logging.getLogger().handlers],
                            "nivel": log.getEffectiveLevel(),
                            "desligado": logging.root.manager.disable}
                    try:
                        info["arquivos"] = sorted(os.listdir(DADOS))
                        info["atalho"] = os.path.exists(caminho_atalho())
                        with open(os.path.join(DADOS, "rgb.log"), encoding="utf-8",
                                  errors="replace") as f:
                            info["log"] = [l.rstrip() for l in f.readlines()[-25:]
                                           if "estilos=" not in l]
                        info["config"] = ler_config()
                    except Exception as e:
                        info["erro_info"] = repr(e)
                    try:
                        h = logging.getLogger().handlers[0]
                        info["stream"] = repr(h.stream)
                        info["pos"] = h.stream.tell() if h.stream else None
                        info["ino_aberto"] = os.fstat(h.stream.fileno()).st_ino
                        info["ino_caminho"] = os.stat(h.baseFilename).st_ino
                        info["tam_caminho"] = os.path.getsize(h.baseFilename)
                    except Exception as e:
                        info["erro_stream"] = repr(e)
                    conn.sendall(json.dumps(info, ensure_ascii=False).encode("utf-8"))

    threading.Thread(target=loop, daemon=True).start()


def e_admin():
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


# ============================================================= como se iniciar
def comando_do_app():
    """(executável, argumentos, pasta) para abrir ESTA instalação do app."""
    if getattr(sys, "frozen", False):
        return sys.executable, "", os.path.dirname(sys.executable)
    script = os.path.abspath(sys.argv[0])
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-len("python.exe")] + "pythonw.exe"
    return exe, f'"{script}"', os.path.dirname(script)


def abrir_elevado(args_extra=""):
    exe, args, pasta = comando_do_app()
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, f"{args} {args_extra}".strip(),
                                        pasta, 1)


def caminho_atalho():
    return os.path.join(_pasta_appdata(), r"Microsoft\Windows\Start Menu\Programs\RGB Sync.lnk")


def garantir_atalho_menu_iniciar():
    """Cria/atualiza o atalho do Menu Iniciar apontando para este .exe (só na versão
    executável). Feito pelo próprio app para cair no Menu Iniciar real do usuário."""
    if not getattr(sys, "frozen", False):
        return
    exe = sys.executable
    lnk = caminho_atalho()
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
          f"if ($s.TargetPath -ne '{exe}') {{ $s.TargetPath='{exe}';"
          f"$s.WorkingDirectory='{os.path.dirname(exe)}'; $s.IconLocation='{exe},0';"
          f"$s.Description='RGB Sync'; $s.Save(); 'criado' }}")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                       text=True, creationflags=SEM_JANELA)
    if r.stdout.strip():
        log.info("atalho do Menu Iniciar: %s", r.stdout.strip())


# ============================================================= iniciar com o Windows
def _schtasks(*args):
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          creationflags=SEM_JANELA)


def inicializacao_ativa():
    return _schtasks("/query", "/tn", TAREFA).returncode == 0


def comando_da_tarefa():
    """Caminho do executável que a tarefa agendada abre (ou None)."""
    r = _schtasks("/query", "/tn", TAREFA, "/xml")
    if r.returncode != 0:
        return None
    m = re.search(r"<Command>(.*?)</Command>", r.stdout)
    return m.group(1).strip().strip('"') if m else None


def ativar_inicializacao():
    """Cria/atualiza a tarefa "RGB Sync": roda no login, elevada, escondida na
    bandeja, 20 s depois do login (dá tempo do iCUE e do MSI Center subirem).
    Precisa de administrador (o app já roda assim)."""
    exe, args, pasta = comando_do_app()
    args = f"{args} --bandeja".strip().replace("'", "''")
    usuario = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"
    ps = f"""
$a = New-ScheduledTaskAction -Execute '{exe}' -Argument '{args}' -WorkingDirectory '{pasta}'
$t = New-ScheduledTaskTrigger -AtLogOn -User '{usuario}'
$t.Delay = 'PT20S'
$p = New-ScheduledTaskPrincipal -UserId '{usuario}' -LogonType Interactive -RunLevel Highest
$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName '{TAREFA}' -Action $a -Trigger $t -Principal $p -Settings $s -Description 'RGB Sync: Corsair + MSI sincronizados' -Force | Out-Null
"""
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True, creationflags=SEM_JANELA)
    ok = r.returncode == 0 and inicializacao_ativa()
    log.info("ativar inicialização (%s %s): %s %s", exe, args, ok, r.stderr.strip()[:300])
    return ok


def desativar_inicializacao():
    ok = _schtasks("/delete", "/tn", TAREFA, "/f").returncode == 0
    log.info("desativar inicialização: %s", ok)
    return ok


def corrigir_tarefa_se_preciso():
    """Se a inicialização está ligada mas aponta para outra cópia do app (ex.: a
    versão antiga em Python), aponta para esta."""
    if not (e_admin() and inicializacao_ativa()):
        return
    atual = comando_da_tarefa()
    exe = comando_do_app()[0]
    if atual and os.path.normcase(atual) != os.path.normcase(exe):
        log.info("tarefa apontava para %s; atualizando para %s", atual, exe)
        ativar_inicializacao()


def abrir_pela_tarefa(espera=20):
    """Sem admin: dispara a tarefa (já elevada, sem aviso do Windows) e espera subir."""
    if _schtasks("/run", "/tn", TAREFA).returncode != 0:
        return False
    for _ in range(int(espera * 2)):
        time.sleep(0.5)
        if ja_esta_rodando():
            return True
    return False


# ============================================================= Trabalhador
class Trabalhador(threading.Thread):
    """Todas as chamadas aos SDKs acontecem aqui, numa thread só.

    Modo papel de parede (self.papel != None), até 12 vezes por segundo:
      - captura o papel de parede (já reduzido, ~5 ms);
      - Corsair: cada LED recebe a cor da região do papel de parede que corresponde
        à posição física dele (RAM em coluna, fans em sequência...);
      - MSI (1 cor por zona, lenta): cor geral a cada 2 s, só quando muda de verdade;
      - imagem parada (papel estático, jogo em tela cheia): confere só 4x/s e não
        reenvia nada.
    Mensagens para a interface (ao_status): conexao, resultado, restaurar, layouts,
    preview, papel_cor, papel_info.
    """

    FPS = 12
    FPS_PARADO = 4
    FPS_CENA = 6              # papéis de parede tipo "cena" (captura mais cara)
    FPS_CENA_PARADO = 2
    LIMIAR_IMAGEM = 0.6       # diferença média mínima (0..255) para considerar que mudou
    SUAVIDADE = 0.35          # 0..1: quanto cada quadro novo pesa (menos = mais suave)
    GERAL_A_CADA = 2.0        # s, cor geral (MSI + janela)
    LIMIAR_GERAL = 20
    PREVIEW_A_CADA = 0.2      # s, prévia dos LEDs na janela (só com a janela aberta)
    FPS_EFEITO = 20           # respiração / onda / ciclo
    FPS_TEMPERATURA = 4       # a cor da temperatura muda devagar

    def __init__(self, ao_status, desligados=()):
        super().__init__(daemon=True)
        self.fila = queue.Queue()
        self.ao_status = ao_status
        self.ctrl = Controlador()
        self.ctrl.definir_desligados(desligados)
        self._ultima_cor = None       # última cor fixa enviada (para reenviar)
        self.papel = None             # {"monitor": ..., "brilho": 0..100} ou None
        self.preview_ligado = False   # a interface liga quando a janela está visível
        self._layouts = {}
        self._layouts_de = None
        self._suave = {}
        self._geral_t = 0.0
        self._geral_enviada = None
        self._erro_t = 0.0
        self._cap = None
        self._img_anterior = None
        self._estavel = False
        self._enviado = {}
        self._parado = 0
        self._primeiro = False
        self._forcar_envio = True
        self._preview_t = 0.0
        self.efeito = None            # {"tipo", "cor", "velocidade", "brilho", "fonte"} ou None
        self._efeito_msi = None       # parâmetros do efeito nativo já enviado à MSI
        self._efeito_t0 = time.monotonic()
        self._sensores = None
        self._temp_suave = None
        self._temp_msi = None
        self._temp_msi_t = 0.0

    # ---- comandos vindos da interface (thread da interface)
    def ativar_efeito(self, params):
        """params: {"tipo", "cor": (r, g, b), "velocidade", "brilho", "fonte"}."""
        self.papel = None
        self.efeito = dict(params)
        self.fila.put(("acordar", None))

    def ativar_papel(self, monitor, brilho):
        self.efeito = None
        self.papel = {"monitor": monitor, "brilho": brilho}
        self._geral_t = 0.0
        self._geral_enviada = None
        self._primeiro = True
        self._forcar_envio = True
        self._parado = 0
        self.fila.put(("acordar", None))  # sai da espera longa e começa já

    def ajustar_brilho(self, brilho):
        if self.papel:
            self.papel = {**self.papel, "brilho": brilho}
            self._geral_enviada = None
            self._forcar_envio = True
            self._parado = 0

    def ligar_preview(self, ligado):
        self.preview_ligado = ligado
        if ligado:                         # manda um quadro completo pra janela já
            self._forcar_envio = True
            self._parado = 0

    def cor_fixa(self, rgb):
        self.papel = None
        self.efeito = None
        self.fila.put(("cor", rgb))

    def desligar_dispositivos(self, chaves):
        self.fila.put(("desligados", set(chaves)))

    def recarregar(self):
        self.fila.put(("recarregar", None))

    def _reenviar(self):
        """Manda tudo de novo (depois de recarregar ou (des)ligar aparelhos)."""
        self._layouts_de = None
        self._img_anterior = None
        self._efeito_msi = None
        self._temp_msi = None
        if self.papel:
            self._forcar_envio = True
            self._parado = 0
            self._geral_enviada = None
            self._geral_t = 0.0
        elif self._ultima_cor is not None:
            self.ao_status("resultado", self.ctrl.aplicar(*self._ultima_cor))

    # ---- laço principal
    def run(self):
        status = self.ctrl.conectar()
        self._anunciar_layouts()
        self.ao_status("conexao", status)
        self.ao_status("dispositivos", self.ctrl.listar())
        tentativas, ultima_tentativa = 0, time.monotonic()
        while True:
            # papel de parede "cena" (DirectX) custa ~20 ms por captura: ritmo menor
            lento = bool(self._cap and self._cap.lento)
            fps = self.FPS_CENA if lento else self.FPS
            fps_parado = self.FPS_CENA_PARADO if lento else self.FPS_PARADO
            if self.efeito:
                espera = 1 / (self.FPS_TEMPERATURA if self.efeito["tipo"] == "temperatura"
                              else self.FPS_EFEITO)
            elif not self.papel:
                espera = 10
            elif self._parado >= fps:
                espera = 1 / fps_parado
            else:
                espera = 1 / fps
            try:
                cmd, arg = self.fila.get(timeout=espera)
            except queue.Empty:
                if self.efeito:
                    self._quadro_efeito()
                elif self.papel:
                    self._parado = self._parado + 1 if self._quadro() else 0
                # No boot o iCUE pode subir depois do app: tenta de novo a cada 10 s.
                if (any(v != "ok" for v in status.values()) and tentativas < RETENTATIVAS
                        and time.monotonic() - ultima_tentativa > 10):
                    tentativas += 1
                    ultima_tentativa = time.monotonic()
                    status = self.ctrl.conectar()
                    log.info("reconexão %d: %s", tentativas, status)
                    self._anunciar_layouts()
                    self.ao_status("conexao", status)
                    self.ao_status("dispositivos", self.ctrl.listar())
                continue
            if cmd == "sair":
                self.ctrl.desconectar()
                return
            # Vários pedidos de cor seguidos (arrastando o brilho): só o último vale.
            while cmd == "cor" and not self.fila.empty() and self.fila.queue[0][0] == "cor":
                cmd, arg = self.fila.get()
            if cmd == "cor":
                self._ultima_cor = arg
                self.ao_status("resultado", self.ctrl.aplicar(*arg))
            elif cmd == "restaurar":
                self.ao_status("restaurar", self.ctrl.restaurar_msi())
            elif cmd == "desligados":
                self.ctrl.definir_desligados(arg)
                self.ao_status("dispositivos", self.ctrl.listar())
                self._anunciar_layouts()
                self._reenviar()
            elif cmd == "recarregar":
                status = self.ctrl.recarregar()
                tentativas = 0
                self._anunciar_layouts()
                self.ao_status("conexao", status)
                self.ao_status("dispositivos", self.ctrl.listar())
                self._reenviar()
                self.ao_status("recarregado", status)

    def _anunciar_layouts(self):
        """Manda pra interface o desenho de cada dispositivo (para a prévia)."""
        lista, teclado = [], None
        for be in self.ctrl.por_led():
            for dev_id, (modelo, pos) in be.posicoes.items():
                if not pos:
                    continue
                if getattr(be, "desenho", None):          # teclado: desenho próprio
                    teclado = {"dev_id": dev_id, "chave": be.chaves[dev_id],
                               "ativo": be.ativo(dev_id), "teclas": be.desenho}
                    continue
                ncol, nlin, leds = preparar_layout(pos)
                lista.append((dev_id, modelo, ncol, nlin, leds, be.chaves[dev_id],
                              be.ativo(dev_id)))
        msi = [(d["nome"].split(" (")[0], d["chave"], d["ativo"])
               for d in self.ctrl.listar() if d["marca"] == "MSI"]
        self.ao_status("layouts", {"corsair": lista, "msi": msi, "teclado": teclado})

    # ---- efeitos
    def _garantir_layouts(self, backends):
        assinatura = tuple(id(be.posicoes) for be in backends)
        if self._layouts_de != assinatura:
            self._layouts = {d: (be, preparar_layout(pos)) for be in backends
                             for d, (_, pos) in be.posicoes.items() if pos}
            self._layouts_de = assinatura
            self._suave, self._enviado = {}, {}

    def _quadro_efeito(self):
        ef = self.efeito
        if not ef:
            return
        try:
            tipo, vel = ef["tipo"], ef["velocidade"]
            k = ef["brilho"] / 100
            t = time.monotonic() - self._efeito_t0
            valor_n, texto = 0.0, None
            if tipo == "temperatura":
                if self._sensores is None:
                    self._sensores = efeitos.Sensores()
                v = self._sensores.ler(ef["fonte"])
                alvo = efeitos.normalizar(ef["fonte"], v)
                self._temp_suave = alvo if self._temp_suave is None else \
                    self._temp_suave + (alvo - self._temp_suave) * 0.15
                valor_n, texto = self._temp_suave, self._sensores.texto(ef["fonte"])

            # Corsair + teclado: quadro a quadro, LED a LED
            backends = self.ctrl.por_led()
            self._garantir_layouts(backends)
            mapas = {}
            for dev_id, (be, (ncol, _nlin, leds)) in self._layouts.items():
                if not be.ativo(dev_id):
                    continue
                lista = []
                for led_id, c, _l in leds:
                    x = c / (ncol - 1) if ncol > 1 else 0.5
                    cor = efeitos.cor_led(tipo, t, x, ef["cor"], vel, valor_n)
                    final = tuple(round(min(255, c_) * k) for c_ in cor)
                    lista.append((led_id, final))
                    self._enviado[(dev_id, led_id)] = final
                mapas.setdefault(be, {})[dev_id] = lista
            for be, mapa in mapas.items():
                be.aplicar_por_led(mapa)

            # MSI: efeito nativo (uma vez) ou cor da temperatura (só quando muda)
            if tipo == "temperatura":
                cor = tuple(round(c * k) for c in efeitos.cor_temperatura(valor_n))
                agora = time.monotonic()
                if (self._temp_msi is None or (agora - self._temp_msi_t > 2 and
                        max(abs(a - b) for a, b in zip(cor, self._temp_msi)) > 12)):
                    self._temp_msi, self._temp_msi_t = cor, agora
                    self._efeito_msi = None
                    self.ctrl.aplicar(*cor, so_msi=True)
                    self.ao_status("efeito_msi", rgb_hex(cor))
            else:
                chave = (tipo, vel, ef["cor"], ef["brilho"])
                if self._efeito_msi != chave and self.ctrl.msi():
                    self._efeito_msi = chave
                    self._temp_msi = None
                    mb, vga = efeitos.ESTILOS_MSI[tipo]
                    cor = tuple(round(c * k) for c in ef["cor"])
                    self.ctrl.msi().aplicar_efeito({"MSI_MB": mb, "MSI_VGA": vga}, *cor,
                                                   efeitos.NIVEL_VEL[vel])
                    self.ao_status("efeito_msi", rgb_hex(cor) if tipo == "respiracao"
                                   else "arco-íris")

            agora = time.monotonic()
            if self.preview_ligado and agora - self._preview_t >= self.PREVIEW_A_CADA:
                self._preview_t = agora
                self.ao_status("preview", dict(self._enviado))
                if texto:
                    self.ao_status("sensor", texto)
        except Exception:
            if time.monotonic() - self._erro_t > 30:
                self._erro_t = time.monotonic()
                log.exception("falha no quadro do efeito")

    # ---- modo papel de parede
    def _quadro(self):
        """Um quadro do modo ao vivo. Devolve True se a imagem estava parada."""
        cfg = self.papel
        if not cfg:
            return True
        try:
            if self._cap is None:
                self._cap = Capturador()
            peq, fonte = self._cap.capturar(cfg["monitor"])
            if peq is None:
                if time.monotonic() - self._geral_t > self.GERAL_A_CADA:
                    self._geral_t = time.monotonic()
                    self.ao_status("papel_info", fonte)
                return True

            ant = self._img_anterior
            self._img_anterior = peq
            mudou = (ant is None or max(ImageStat.Stat(ImageChops.difference(ant, peq)).mean)
                     > self.LIMIAR_IMAGEM)
            if not mudou and self._estavel and not self._forcar_envio:
                return True

            k = cfg["brilho"] / 100
            backends = self.ctrl.por_led()           # Corsair e teclado
            if backends:
                assinatura = tuple(id(be.posicoes) for be in backends)
                if self._layouts_de != assinatura:
                    self._layouts = {d: (be, preparar_layout(pos)) for be in backends
                                     for d, (_, pos) in be.posicoes.items() if pos}
                    self._layouts_de = assinatura
                    self._suave, self._enviado = {}, {}
                a = self.SUAVIDADE
                estavel = True
                mapas = {}
                for dev_id, (be, lay) in self._layouts.items():
                    if not be.ativo(dev_id):
                        continue
                    leds, mudou_disp = [], False
                    for led_id, alvo in cores_por_led(peq, lay):
                        chave = (dev_id, led_id)
                        ant_c = self._suave.get(chave)
                        cor = alvo if ant_c is None else tuple(
                            p + (c - p) * a for p, c in zip(ant_c, alvo))
                        if max(abs(c - t) for c, t in zip(cor, alvo)) > 1:
                            estavel = False
                        self._suave[chave] = cor
                        final = tuple(round(c * k) for c in cor)
                        if self._enviado.get(chave) != final:
                            mudou_disp = True
                            self._enviado[chave] = final
                        leds.append((led_id, final))
                    if mudou_disp or self._forcar_envio:
                        mapas.setdefault(be, {})[dev_id] = leds
                for be, mapa in mapas.items():
                    be.aplicar_por_led(mapa)
                self._estavel = estavel
                if self._primeiro:
                    self._primeiro = False
                    log.info("papel de parede ao vivo: %s, %s", fonte,
                             {d: f"{l[1][0]}x{l[1][1]}" for d, l in self._layouts.items()})
                agora = time.monotonic()
                if self.preview_ligado and (mapas or self._forcar_envio)                         and agora - self._preview_t >= self.PREVIEW_A_CADA:
                    self._preview_t = agora
                    self.ao_status("preview", dict(self._enviado))
            self._forcar_envio = False

            agora = time.monotonic()
            if agora - self._geral_t >= self.GERAL_A_CADA:
                self._geral_t = agora
                geral = cor_para_leds(peq)
                env = self._geral_enviada
                if env is None or max(abs(x - y) for x, y in zip(geral, env)) > self.LIMIAR_GERAL:
                    self._geral_enviada = geral
                    self.ctrl.aplicar(*(round(c * k) for c in geral), so_msi=True)
                    self.ao_status("papel_cor", (geral, fonte))
            return not mudou
        except Exception:
            if time.monotonic() - self._erro_t > 30:     # não lotar o log
                self._erro_t = time.monotonic()
                log.exception("falha no quadro do papel de parede")
            return False
