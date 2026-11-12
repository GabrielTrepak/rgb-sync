"""
RGB Sync — v2 (cor fixa sincronizada + bandeja + iniciar com o Windows).

- Fechar a janela só esconde: o app continua na bandeja (perto do relógio).
- Para sair de verdade: botão direito no ícone da bandeja → Sair.
- `--bandeja` inicia já escondido (usado na inicialização do Windows).
- Só roda uma cópia: abrir de novo apenas mostra a janela da que já está rodando.
"""

import json
import os
import queue
import socket
import sys
import threading
import tkinter as tk
from tkinter import colorchooser

import pystray
from PIL import Image, ImageDraw

from rgb_core import PASTA, Controlador, log

CONFIG = os.path.join(PASTA, "config.json")
PORTA_UNICA = 47652          # só para a 2ª cópia avisar a 1ª: "mostre a janela"
RETENTATIVAS = 18            # 18 x 10 s = 3 min tentando conectar no boot

PRESETS = [
    ("Branco", "#ffffff"), ("Vermelho", "#ff0000"), ("Laranja", "#ff5a00"),
    ("Amarelo", "#ffc800"), ("Verde", "#00ff40"), ("Ciano", "#00e5ff"),
    ("Azul", "#0050ff"), ("Roxo", "#8000ff"), ("Rosa", "#ff00a0"),
]

BG, PAINEL, TEXTO, SUAVE = "#141418", "#1e1e24", "#e8e8ec", "#8a8a96"


def ler_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"cor": "#0050ff", "brilho": 100}


def salvar_config(cfg):
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        log.exception("falha ao salvar config")


def icone_bandeja(hexa):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    h = hexa.lstrip("#")
    rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    if sum(rgb) < 60:                      # "apagado": mostra um anel cinza
        d.ellipse((6, 6, 58, 58), outline=(140, 140, 150, 255), width=6)
    else:
        d.ellipse((4, 4, 60, 60), fill=rgb + (255,), outline=(20, 20, 24, 255), width=3)
    return img


# ------------------------------------------------------------- instância única
def ja_esta_rodando():
    """Se já existe uma cópia, pede pra ela mostrar a janela e devolve True."""
    try:
        with socket.create_connection(("127.0.0.1", PORTA_UNICA), timeout=1) as s:
            s.sendall(b"mostrar")
        return True
    except OSError:
        return False


def ouvir_outras_copias(ao_mostrar):
    srv = socket.socket()
    srv.bind(("127.0.0.1", PORTA_UNICA))
    srv.listen(1)

    def loop():
        while True:
            conn, _ = srv.accept()
            with conn:
                if conn.recv(16) == b"mostrar":
                    ao_mostrar()

    threading.Thread(target=loop, daemon=True).start()


# ------------------------------------------------------------- SDKs (thread única)
class Trabalhador(threading.Thread):
    def __init__(self, ao_status):
        super().__init__(daemon=True)
        self.fila = queue.Queue()
        self.ao_status = ao_status
        self.ctrl = Controlador()

    def run(self):
        status = self.ctrl.conectar()
        self.ao_status("conexao", status)
        tentativas = 0
        while True:
            try:
                cmd, arg = self.fila.get(timeout=10)
            except queue.Empty:
                # No boot o iCUE pode subir depois do app: tenta de novo.
                if any(v != "ok" for v in status.values()) and tentativas < RETENTATIVAS:
                    tentativas += 1
                    status = self.ctrl.conectar()
                    log.info("reconexão %d: %s", tentativas, status)
                    self.ao_status("conexao", status)
                continue
            if cmd == "sair":
                self.ctrl.desconectar()
                return
            # Se chegaram vários pedidos de cor seguidos (arrastando o brilho), só o último vale.
            while cmd == "cor" and not self.fila.empty() and self.fila.queue[0][0] == "cor":
                cmd, arg = self.fila.get()
            if cmd == "cor":
                self.ao_status("resultado", self.ctrl.aplicar(*arg))
            elif cmd == "restaurar":
                self.ao_status("restaurar", self.ctrl.restaurar_msi())


# ------------------------------------------------------------- janela + bandeja
class App:
    def __init__(self, root, iniciar_escondido):
        self.root = root
        self.cfg = ler_config()
        self.conexao = {}
        self.pronto = False
        self.avisou_bandeja = iniciar_escondido
        root.title("RGB Sync")
        root.configure(bg=BG)
        root.resizable(False, False)
        self._montar_janela()

        self.icon = pystray.Icon("RGBSync", icone_bandeja(self.cfg["cor"]), "RGB Sync",
                                 self._menu_bandeja())
        self.icon.run_detached()

        ouvir_outras_copias(lambda: root.after(0, self.mostrar))
        root.protocol("WM_DELETE_WINDOW", self.esconder)
        if iniciar_escondido:
            root.withdraw()

        self.trab = Trabalhador(lambda t, d: root.after(0, self.ao_status, t, d))
        self.trab.start()

    # ---- montagem
    def _botao(self, pai, texto, cmd, **kw):
        return tk.Button(pai, text=texto, command=cmd, bg=PAINEL, fg=TEXTO,
                         activebackground="#2a2a33", activeforeground=TEXTO,
                         relief="flat", padx=10, pady=3, cursor="hand2", **kw)

    def _montar_janela(self):
        root = self.root
        tk.Label(root, text="RGB Sync", bg=BG, fg=TEXTO,
                 font=("Segoe UI Semibold", 16)).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(root, text="Uma cor para o PC inteiro", bg=BG, fg=SUAVE,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18)

        topo = tk.Frame(root, bg=BG)
        topo.pack(fill="x", padx=18, pady=14)
        self.amostra = tk.Label(topo, width=6, height=3, bg=self.cfg["cor"])
        self.amostra.pack(side="left")
        lado = tk.Frame(topo, bg=BG)
        lado.pack(side="left", padx=12)
        self.lbl_hex = tk.Label(lado, text=self.cfg["cor"].upper(), bg=BG, fg=TEXTO,
                                font=("Consolas", 13))
        self.lbl_hex.pack(anchor="w")
        self._botao(lado, "Escolher cor…", self.escolher).pack(anchor="w", pady=(4, 0))

        grade = tk.Frame(root, bg=BG)
        grade.pack(padx=18)
        for i, (_, cor) in enumerate(PRESETS):
            tk.Button(grade, bg=cor, activebackground=cor, width=4, relief="flat",
                      cursor="hand2", command=lambda c=cor: self.definir(c)).grid(
                row=0, column=i, padx=2)
        self._botao(root, "Apagar tudo", lambda: self.definir("#000000")).pack(
            anchor="w", padx=18, pady=(8, 0))

        tk.Label(root, text="Brilho", bg=BG, fg=SUAVE, font=("Segoe UI", 9)).pack(
            anchor="w", padx=18, pady=(12, 0))
        self.brilho = tk.Scale(root, from_=0, to=100, orient="horizontal", length=330,
                               bg=BG, fg=TEXTO, troughcolor=PAINEL, highlightthickness=0,
                               command=lambda _v: self.enviar())
        self.brilho.set(self.cfg.get("brilho", 100))
        self.brilho.pack(padx=18)

        tk.Label(root, text="Dispositivos", bg=BG, fg=SUAVE, font=("Segoe UI", 9)).pack(
            anchor="w", padx=18, pady=(10, 2))
        self.status = tk.Label(root, text="Conectando…", bg=PAINEL, fg=TEXTO, justify="left",
                               anchor="w", font=("Consolas", 9), padx=10, pady=8, width=48)
        self.status.pack(padx=18)

        rodape = tk.Frame(root, bg=BG)
        rodape.pack(fill="x", padx=14, pady=(4, 12))
        tk.Label(rodape, text="Fechar = continua na bandeja", bg=BG, fg=SUAVE,
                 font=("Segoe UI", 8)).pack(side="left", padx=4)
        tk.Button(rodape, text="Restaurar MSI original", command=self.restaurar,
                  bg=BG, fg=SUAVE, activebackground=BG, activeforeground=TEXTO,
                  relief="flat", cursor="hand2", font=("Segoe UI", 8)).pack(side="right")

    def _menu_bandeja(self):
        def na_ui(func, *args):
            return lambda icon, item: self.root.after(0, func, *args)

        cores = pystray.Menu(*[pystray.MenuItem(nome, na_ui(self.definir, cor))
                               for nome, cor in PRESETS])
        return pystray.Menu(
            pystray.MenuItem("Abrir RGB Sync", na_ui(self.mostrar), default=True),
            pystray.MenuItem("Cores", cores),
            pystray.MenuItem("Apagar tudo", na_ui(self.definir, "#000000")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", na_ui(self.sair)),
        )

    # ---- ações
    def escolher(self):
        _, hexa = colorchooser.askcolor(color=self.cfg["cor"], title="Escolha a cor")
        if hexa:
            self.definir(hexa)

    def definir(self, hexa):
        self.cfg["cor"] = hexa
        self.amostra.configure(bg=hexa)
        self.lbl_hex.configure(text=hexa.upper())
        self.icon.icon = icone_bandeja(hexa)
        self.enviar()

    def enviar(self):
        if not self.pronto:
            return
        h = self.cfg["cor"].lstrip("#")
        k = self.brilho.get() / 100
        rgb = tuple(round(int(h[i:i + 2], 16) * k) for i in (0, 2, 4))
        self.cfg["brilho"] = self.brilho.get()
        salvar_config(self.cfg)
        self.trab.fila.put(("cor", rgb))

    def restaurar(self):
        self.trab.fila.put(("restaurar", None))

    def mostrar(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def esconder(self):
        self.root.withdraw()
        if not self.avisou_bandeja:
            self.avisou_bandeja = True
            try:
                self.icon.notify("Continua rodando aqui na bandeja. "
                                 "Botão direito → Sair para fechar de vez.", "RGB Sync")
            except Exception:
                pass

    def sair(self):
        self.trab.fila.put(("sair", None))
        self.trab.join(timeout=5)
        self.icon.stop()
        self.root.destroy()

    # ---- status
    def ao_status(self, tipo, dados):
        if tipo == "conexao":
            self.conexao = dados
            self.pronto = True
            self.enviar()   # (re)aplica a última cor salva
        elif tipo == "resultado":
            linhas = [f"… {m}: {s}" for m, s in self.conexao.items() if s != "ok"]
            for disp, st in dados.items():
                ok = st in ("CE_Success", "OK")
                linhas.append(f"{'✓' if ok else '✗'} {disp}" + ("" if ok else f"  ({st})"))
            linhas.append("– HyperX: ainda não suportado")
            self.status.configure(text="\n".join(linhas))
        elif tipo == "restaurar":
            self.status.configure(text=f"MSI: {dados}\n(Corsair segue a cor do app)")


TAREFA = "RGB Sync"


def abrir_pelo_atalho():
    """Usado pelo 'Abrir RGB.bat' (roda SEM admin).

    - Se o app já está rodando: só mostra a janela.
    - Se a inicialização com o Windows está instalada: dispara a tarefa agendada
      (já tem admin, então NÃO aparece o aviso do Windows) e mostra a janela.
    - Senão: abre pedindo administrador.
    """
    import ctypes
    import subprocess
    import time
    if ja_esta_rodando():
        return
    sem_janela = subprocess.CREATE_NO_WINDOW
    tem_tarefa = subprocess.run(["schtasks", "/query", "/tn", TAREFA],
                                capture_output=True, creationflags=sem_janela).returncode == 0
    if tem_tarefa:
        subprocess.run(["schtasks", "/run", "/tn", TAREFA],
                       capture_output=True, creationflags=sem_janela)
        for _ in range(40):            # até 20 s esperando ela subir
            time.sleep(0.5)
            if ja_esta_rodando():
                return
    else:
        pythonw = os.path.join(PASTA, ".venv", "Scripts", "pythonw.exe")
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", pythonw, f'"{os.path.join(PASTA, "app.py")}"', PASTA, 1)


if __name__ == "__main__":
    if "--abrir" in sys.argv:
        abrir_pelo_atalho()
        sys.exit(0)
    if ja_esta_rodando():
        sys.exit(0)
    log.info("=== app iniciado %s", sys.argv[1:])
    root = tk.Tk()
    App(root, iniciar_escondido="--bandeja" in sys.argv)
    root.mainloop()
