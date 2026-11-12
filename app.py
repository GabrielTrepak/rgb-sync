"""
RGB Sync — interface (janela + bandeja).

- Fechar a janela só esconde: o app continua na bandeja (perto do relógio).
- Para sair de verdade: botão direito no ícone da bandeja → Sair.
- `--bandeja` inicia escondido (usado na inicialização do Windows).
- Só roda uma cópia; abrir de novo só mostra a janela.
- Sem administrador: se a inicialização com o Windows está ligada, abre pela tarefa
  agendada (sem aviso do Windows); senão pede administrador (o SDK da MSI exige).
"""

import ctypes
import os
import sys
import threading
import tkinter as tk
from tkinter import colorchooser

import customtkinter as ctk
import pystray
from PIL import Image

import motor
from icone import icone
from motor import hex_rgb, ler_config, rgb_hex, salvar_config
from rgb_core import PASTA, log

VERSAO = "3.0"
ICO = os.path.join(PASTA, "assets", "rgbsync.ico")
PNG = os.path.join(PASTA, "assets", "rgbsync.png")

PRESETS = [
    ("Branco", "#ffffff"), ("Vermelho", "#ff0000"), ("Laranja", "#ff5a00"),
    ("Amarelo", "#ffc800"), ("Verde", "#00ff40"), ("Ciano", "#00e5ff"),
    ("Azul", "#0050ff"), ("Roxo", "#8000ff"), ("Rosa", "#ff00a0"),
]

# paleta da interface
FUNDO = "#101015"
CARTAO = "#1a1a21"
BORDA = "#272731"
TEXTO = "#ececf1"
SUAVE = "#8c8c9a"
DESTAQUE = "#7c5cff"
OK, ALERTA = "#3ddc84", "#ffb74d"

MODOS = {"Papel de parede": "papel_parede", "Cor fixa": "fixo"}
MONITORES = {"Principal": "principal", "Secundário": "secundario", "Os dois": "ambos"}
LARGURA = 452


def _nome(dic, valor):
    return next(k for k, v in dic.items() if v == valor)


class Previa(tk.Canvas):
    """Desenho de 'como estão os LEDs agora': fita do hub, pentes de RAM, headset
    e as zonas da MSI. Atualiza só as cores (itemconfig), é leve."""

    def __init__(self, master):
        super().__init__(master, width=LARGURA - 40, height=60, bg=CARTAO,
                         highlightthickness=0, bd=0)
        self.itens = {}        # (dev_id, led_id) -> id
        self.msi = []          # ids das zonas MSI
        self.todos = []

    def montar(self, layouts):
        self.delete("all")
        self.itens, self.msi, self.todos = {}, [], []
        w = int(self["width"])
        y = 4
        fitas = [l for l in layouts["corsair"] if l[3] == 1 and l[2] > 4]
        blocos = [l for l in layouts["corsair"] if l not in fitas]
        for dev_id, modelo, ncol, nlin, leds in fitas:
            nome = "Cooler e fans" if "LINK" in modelo.upper() else modelo
            self.create_text(0, y, text=nome, anchor="nw", fill=SUAVE, font=("Segoe UI", 9))
            y += 18
            cw = w / ncol
            for led_id, c, _ in leds:
                i = self.create_rectangle(c * cw, y, (c + 1) * cw + 0.6, y + 22,
                                          outline="", fill="#333")
                self.itens.setdefault((dev_id, led_id), i)
                self.todos.append(i)
            y += 34
        # linha de "blocos": RAM, headset, MSI
        x, topo, alt = 0, y, 92
        for dev_id, modelo, ncol, nlin, leds in blocos:
            if ncol * nlin == 1:                          # headset etc.
                nome = "Headset" if "HS" in modelo.upper() else modelo
                i = self.create_oval(x + 8, topo + 22, x + 44, topo + 58, outline="", fill="#333")
                self.itens[(dev_id, leds[0][0])] = i
                self.todos.append(i)
                self.create_text(x + 26, topo + alt - 10, text=nome, fill=SUAVE,
                                 font=("Segoe UI", 9))
                x += 64
            else:                                         # RAM (colunas)
                nome = "Memória RAM" if "DDR" in modelo.upper() or "VENGEANCE" in modelo.upper() \
                    else modelo
                bw, gap, ch = 16, 8, (alt - 26) / nlin
                larg_barras = ncol * bw + (ncol - 1) * gap
                larg = max(larg_barras, 84)               # cabe o nome embaixo
                x_barras = x + (larg - larg_barras) / 2
                for led_id, c, l in leds:
                    x0 = x_barras + c * (bw + gap)
                    i = self.create_rectangle(x0, topo + l * ch, x0 + bw, topo + (l + 1) * ch - 1,
                                              outline="", fill="#333")
                    self.itens[(dev_id, led_id)] = i
                    self.todos.append(i)
                self.create_text(x + larg / 2, topo + alt - 10, text=nome, fill=SUAVE,
                                 font=("Segoe UI", 9))
                x += larg + 12
        for nome in layouts["msi"]:
            i = self.create_rectangle(x + 10, topo + 14, x + 62, topo + 62, outline="", fill="#333")
            self.msi.append(i)
            self.todos.append(i)
            self.create_text(x + 36, topo + alt - 10, text=nome, fill=SUAVE, font=("Segoe UI", 9))
            x += 86
        if layouts["corsair"] or layouts["msi"]:
            y = topo + alt
        else:
            self.create_text(w / 2, 30, text="Conectando aos dispositivos…", fill=SUAVE,
                             font=("Segoe UI", 10))
            y = 60
        self.configure(height=y)

    def tudo(self, hexa):
        for i in self.todos:
            self.itemconfig(i, fill=hexa)

    def leds(self, cores):
        for chave, rgb in cores.items():
            i = self.itens.get(chave)
            if i:
                self.itemconfig(i, fill=rgb_hex(rgb))

    def zonas_msi(self, hexa):
        for i in self.msi:
            self.itemconfig(i, fill=hexa)


class App:
    def __init__(self, root, iniciar_escondido):
        self.root = root
        self.cfg = ler_config()
        self.conexao = {}
        self.pronto = False
        self.cor_geral = self.cfg.get("cor_papel", self.cfg["cor"])
        self.avisou_bandeja = iniciar_escondido

        root.title("RGB Sync")
        root.configure(fg_color=FUNDO)
        root.resizable(False, False)
        try:
            root.iconbitmap(ICO)
            root.after(300, lambda: root.iconbitmap(ICO))   # o customtkinter troca o ícone
        except Exception:
            pass
        self._montar()
        root.after(50, self._barra_titulo_escura)

        self.icon = pystray.Icon("RGBSync", self._img_bandeja(), "RGB Sync", self._menu())
        self.icon.run_detached()

        motor.ouvir_outras_copias(lambda: root.after(0, self.mostrar),
                                  lambda: root.after(0, self.sair))
        root.protocol("WM_DELETE_WINDOW", self.esconder)
        root.bind("<Map>", lambda e: self._visivel(True))
        root.bind("<Unmap>", lambda e: self._visivel(False))

        self.trab = motor.Trabalhador(lambda t, d: root.after(0, self.ao_status, t, d))
        self.trab.start()
        self._atualizar_modo()
        if iniciar_escondido:
            root.withdraw()
        def manutencao():
            motor.corrigir_tarefa_se_preciso()
            motor.garantir_atalho_menu_iniciar()
        threading.Thread(target=manutencao, daemon=True).start()

    # ================================================================ montagem
    def _cartao(self, titulo=None):
        f = ctk.CTkFrame(self.root, fg_color=CARTAO, corner_radius=14, border_width=1,
                         border_color=BORDA)
        f.pack(fill="x", padx=16, pady=(0, 10))
        if titulo:
            ctk.CTkLabel(f, text=titulo, text_color=SUAVE, font=("Segoe UI", 12)).pack(
                anchor="w", padx=16, pady=(10, 0))
        return f

    def _montar(self):
        r = self.root
        # cabeçalho
        topo = ctk.CTkFrame(r, fg_color="transparent")
        topo.pack(fill="x", padx=18, pady=(16, 12))
        try:
            img = ctk.CTkImage(Image.open(PNG), size=(34, 34))
            ctk.CTkLabel(topo, image=img, text="").pack(side="left")
        except Exception:
            pass
        ctk.CTkLabel(topo, text="RGB Sync", text_color=TEXTO,
                     font=("Segoe UI Semibold", 20)).pack(side="left", padx=(10, 0))
        self.lbl_estado = ctk.CTkLabel(topo, text="●  Conectando…", text_color=ALERTA,
                                       font=("Segoe UI", 12))
        self.lbl_estado.pack(side="right")

        # modo
        self.seg_modo = ctk.CTkSegmentedButton(
            r, values=list(MODOS), command=self._mudar_modo, height=38,
            font=("Segoe UI Semibold", 13), fg_color=CARTAO, unselected_color=CARTAO,
            unselected_hover_color="#24242c", selected_color=DESTAQUE,
            selected_hover_color="#6a4cf0", text_color=TEXTO, corner_radius=12)
        self.seg_modo.set(_nome(MODOS, self.cfg["modo"]))
        self.seg_modo.pack(fill="x", padx=16, pady=(0, 10))

        # prévia
        cp = self._cartao("Seus LEDs agora")
        self.previa = Previa(cp)
        self.previa.pack(padx=20, pady=(6, 14))
        self.previa.montar({"corsair": [], "msi": []})

        # opções do modo papel de parede
        self.c_papel = self._cartao()
        linha = ctk.CTkFrame(self.c_papel, fg_color="transparent")
        linha.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(linha, text="Monitor", text_color=TEXTO, font=("Segoe UI", 13)).pack(
            side="left")
        self.seg_monitor = ctk.CTkSegmentedButton(
            linha, values=list(MONITORES), command=self._mudar_monitor, height=30,
            font=("Segoe UI", 12), fg_color=FUNDO, unselected_color=FUNDO,
            unselected_hover_color="#24242c", selected_color="#34343f",
            selected_hover_color="#3c3c48", text_color=TEXTO)
        self.seg_monitor.set(_nome(MONITORES, self.cfg["monitor"]))
        self.seg_monitor.pack(side="right")
        self.lbl_fonte = ctk.CTkLabel(self.c_papel, text="", text_color=SUAVE,
                                      font=("Segoe UI", 11), justify="left")
        self.lbl_fonte.pack(anchor="w", padx=16, pady=(0, 10))

        # opções do modo cor fixa
        self.c_fixo = self._cartao()
        grade = ctk.CTkFrame(self.c_fixo, fg_color="transparent")
        grade.pack(fill="x", padx=14, pady=(14, 8))
        for i, (nome, cor) in enumerate(PRESETS):
            b = ctk.CTkButton(grade, text="", width=34, height=34, corner_radius=17,
                              fg_color=cor, hover_color=cor, border_width=2,
                              border_color=CARTAO, command=lambda c=cor: self.definir(c))
            b.grid(row=0, column=i, padx=3)
        linha2 = ctk.CTkFrame(self.c_fixo, fg_color="transparent")
        linha2.pack(fill="x", padx=16, pady=(0, 14))
        self.amostra = ctk.CTkFrame(linha2, width=34, height=34, corner_radius=8,
                                    fg_color=self.cfg["cor"])
        self.amostra.pack(side="left")
        self.ent_hex = ctk.CTkEntry(linha2, width=96, height=32, fg_color=FUNDO,
                                    border_color=BORDA, text_color=TEXTO,
                                    font=("Consolas", 13))
        self.ent_hex.insert(0, self.cfg["cor"].upper())
        self.ent_hex.bind("<Return>", self._hex_digitado)
        self.ent_hex.bind("<FocusOut>", self._hex_digitado)
        self.ent_hex.pack(side="left", padx=10)
        ctk.CTkButton(linha2, text="Escolher cor…", width=120, height=32, fg_color="#2a2a33",
                      hover_color="#34343f", text_color=TEXTO, font=("Segoe UI", 12),
                      command=self.escolher).pack(side="right")
        ctk.CTkButton(linha2, text="Apagar", width=70, height=32, fg_color="transparent",
                      border_width=1, border_color=BORDA, hover_color="#24242c",
                      text_color=SUAVE, font=("Segoe UI", 12),
                      command=lambda: self.definir("#000000")).pack(side="right", padx=8)

        # brilho
        cb = self._cartao()
        lb = ctk.CTkFrame(cb, fg_color="transparent")
        lb.pack(fill="x", padx=16, pady=(12, 12))
        ctk.CTkLabel(lb, text="Brilho", text_color=TEXTO, font=("Segoe UI", 13)).pack(side="left")
        self.lbl_brilho = ctk.CTkLabel(lb, text="", width=44, text_color=SUAVE,
                                       font=("Segoe UI", 12))
        self.lbl_brilho.pack(side="right")
        self.sl_brilho = ctk.CTkSlider(lb, from_=0, to=100, number_of_steps=100,
                                       command=self._mudar_brilho, button_color=DESTAQUE,
                                       button_hover_color="#8f73ff", progress_color=DESTAQUE,
                                       fg_color="#2a2a33")
        self.sl_brilho.set(self.cfg["brilho"])
        self.sl_brilho.pack(side="right", fill="x", expand=True, padx=(16, 8))
        self.lbl_brilho.configure(text=f"{int(self.cfg['brilho'])}%")

        # ajustes
        ca = self._cartao()
        la = ctk.CTkFrame(ca, fg_color="transparent")
        la.pack(fill="x", padx=16, pady=(12, 6))
        self.var_inicio = ctk.BooleanVar(value=motor.inicializacao_ativa())
        ctk.CTkSwitch(la, text="Iniciar com o Windows", variable=self.var_inicio,
                      command=self._mudar_inicio, text_color=TEXTO, font=("Segoe UI", 13),
                      progress_color=DESTAQUE).pack(side="left")
        ld = ctk.CTkFrame(ca, fg_color="transparent")
        ld.pack(fill="x", padx=16, pady=(2, 10))
        self.lbl_disp = ctk.CTkLabel(ld, text="", text_color=SUAVE, font=("Segoe UI", 11),
                                     justify="left")
        self.lbl_disp.pack(side="left")
        ctk.CTkButton(ld, text="Restaurar MSI original", width=10, height=26,
                      fg_color="transparent", hover_color="#24242c", text_color=SUAVE,
                      font=("Segoe UI", 11), command=self.restaurar).pack(side="right")

        ctk.CTkLabel(r, text=f"Fechar a janela mantém o RGB Sync na bandeja  ·  v{VERSAO}",
                     text_color="#5c5c68", font=("Segoe UI", 10)).pack(pady=(0, 12))

    def _barra_titulo_escura(self):
        """Windows 11: barra de título escura e da mesma cor do fundo.
        Só funciona depois que a janela existe de verdade (foi mostrada ao menos uma
        vez), por isso é chamada também ao mostrar."""
        try:
            from ctypes import wintypes as W
            u, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
            u.GetParent.restype = W.HWND
            u.GetParent.argtypes = [W.HWND]
            dwm.DwmSetWindowAttribute.argtypes = [W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD]
            hwnd = u.GetParent(self.root.winfo_id())
            if not hwnd:
                return
            um = ctypes.c_int(1)
            r1 = dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(um), 4)  # modo escuro
            r, g, b = hex_rgb(FUNDO)
            cor = ctypes.c_int(r | (g << 8) | (b << 16))                     # COLORREF
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cor), 4)      # cor da barra
            # força o Windows a redesenhar a moldura já (senão só muda ao trocar o foco)
            u.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            u.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
            if r1 != 0:
                log.warning("barra de título escura falhou: hwnd=%s resultado=%s", hwnd, r1)
        except Exception:
            log.exception("barra de título")

    # ================================================================ bandeja
    def _img_bandeja(self):
        return icone(64, hex_rgb(self.cor_geral if self.cfg["modo"] == "papel_parede"
                                 else self.cfg["cor"]))

    def _menu(self):
        def ui(func, *args):
            return lambda icon, item: self.root.after(0, func, *args)

        cores = pystray.Menu(*[pystray.MenuItem(n, ui(self.definir, c)) for n, c in PRESETS])
        return pystray.Menu(
            pystray.MenuItem("Abrir RGB Sync", ui(self.mostrar), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Papel de parede", ui(self._mudar_modo, "Papel de parede"),
                             checked=lambda i: self.cfg["modo"] == "papel_parede", radio=True),
            pystray.MenuItem("Cor fixa", ui(self._mudar_modo, "Cor fixa"),
                             checked=lambda i: self.cfg["modo"] == "fixo", radio=True),
            pystray.MenuItem("Cores", cores),
            pystray.MenuItem("Apagar tudo", ui(self.definir, "#000000")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", ui(self.sair)),
        )

    # ================================================================ ações
    def _mudar_modo(self, nome):
        self.cfg["modo"] = MODOS[nome]
        self.seg_modo.set(nome)
        self._atualizar_modo()
        self.enviar()
        self.icon.update_menu()

    def _atualizar_modo(self):
        papel = self.cfg["modo"] == "papel_parede"
        self.c_papel.pack_forget()
        self.c_fixo.pack_forget()
        alvo = self.c_papel if papel else self.c_fixo
        alvo.pack(fill="x", padx=16, pady=(0, 10), after=self.previa.master)
        if papel:
            self.lbl_fonte.configure(text="Lendo o papel de parede…")
            self.previa.zonas_msi(self.cor_geral)
        else:
            self.previa.tudo(self._hex_com_brilho(self.cfg["cor"]))
        if hasattr(self, "icon"):
            self.icon.icon = self._img_bandeja()

    def _mudar_monitor(self, nome):
        self.cfg["monitor"] = MONITORES[nome]
        self.enviar()

    def _mudar_brilho(self, valor):
        self.cfg["brilho"] = int(valor)
        self.lbl_brilho.configure(text=f"{int(valor)}%")
        self.enviar()

    def _hex_com_brilho(self, hexa):
        k = self.cfg["brilho"] / 100
        return rgb_hex(round(c * k) for c in hex_rgb(hexa))

    def definir(self, hexa):
        """Cor escolhida à mão → modo cor fixa."""
        self.cfg["cor"] = hexa
        self.amostra.configure(fg_color=hexa)
        self.ent_hex.delete(0, "end")
        self.ent_hex.insert(0, hexa.upper())
        if self.cfg["modo"] != "fixo":
            self._mudar_modo("Cor fixa")
        else:
            self._atualizar_modo()
            self.enviar()

    def _hex_digitado(self, _e=None):
        t = self.ent_hex.get().strip().lstrip("#")
        if len(t) == 6 and all(c in "0123456789abcdefABCDEF" for c in t):
            if "#" + t.lower() != self.cfg["cor"].lower():
                self.definir("#" + t.lower())
        else:
            self.ent_hex.delete(0, "end")
            self.ent_hex.insert(0, self.cfg["cor"].upper())

    def escolher(self):
        _, hexa = colorchooser.askcolor(color=self.cfg["cor"], title="Escolha a cor")
        if hexa:
            self.definir(hexa)

    def enviar(self):
        salvar_config(self.cfg)
        if not self.pronto:
            return
        if self.cfg["modo"] == "papel_parede":
            p = self.trab.papel
            if p and p["monitor"] == self.cfg["monitor"]:
                self.trab.ajustar_brilho(self.cfg["brilho"])
            else:
                self.trab.ativar_papel(self.cfg["monitor"], self.cfg["brilho"])
            self.previa.zonas_msi(self._hex_com_brilho(self.cor_geral))
        else:
            self.trab.cor_fixa(hex_rgb(self._hex_com_brilho(self.cfg["cor"])))
            self.previa.tudo(self._hex_com_brilho(self.cfg["cor"]))

    def _mudar_inicio(self):
        querer = self.var_inicio.get()
        ok = motor.ativar_inicializacao() if querer else motor.desativar_inicializacao()
        if not ok:
            self.var_inicio.set(not querer)
        self.var_inicio.set(motor.inicializacao_ativa())

    def restaurar(self):
        self.trab.fila.put(("restaurar", None))

    # ================================================================ janela
    def _visivel(self, sim):
        if sim and not getattr(self, "_titulo_agendado", False):
            # o customtkinter mexe na moldura ao reexibir; aplica depois dele
            self._titulo_agendado = True

            def aplicar():
                self._titulo_agendado = False
                self._barra_titulo_escura()
            self.root.after(150, aplicar)
        if hasattr(self, "trab"):
            self.trab.ligar_preview(sim and self.root.state() != "withdrawn")

    def mostrar(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self._visivel(True)

    def esconder(self):
        self.root.withdraw()
        self._visivel(False)
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

    # ================================================================ mensagens do motor
    def ao_status(self, tipo, dados):
        if tipo == "conexao":
            self.conexao = dados
            self.pronto = True
            ok = [m for m, s in dados.items() if s == "ok"]
            if len(ok) == len(dados):
                self.lbl_estado.configure(text="●  Conectado", text_color=OK)
            else:
                self.lbl_estado.configure(text="●  Conectando…", text_color=ALERTA)
            linhas = []
            for marca, st in dados.items():
                linhas.append(f"{'✓' if st == 'ok' else '…'}  {marca.split(' (')[0]}"
                              + ("" if st == "ok" else f" — {st}"))
            linhas.append("–  Teclado HyperX (em breve)")
            self.lbl_disp.configure(text="\n".join(linhas))
            self.enviar()
        elif tipo == "layouts":
            self.previa.montar(dados)
            self._atualizar_modo()
            self._visivel(self.root.state() != "withdrawn")
        elif tipo == "preview":
            if self.cfg["modo"] == "papel_parede":
                self.previa.leds(dados)
        elif tipo == "papel_cor":
            geral, fonte = dados
            self.cor_geral = rgb_hex(geral)
            self.cfg["cor_papel"] = self.cor_geral
            salvar_config(self.cfg)
            if self.cfg["modo"] == "papel_parede":
                self.previa.zonas_msi(self._hex_com_brilho(self.cor_geral))
                self.lbl_fonte.configure(text=f"Ao vivo  ·  {fonte}")
                self.icon.icon = self._img_bandeja()
        elif tipo == "papel_info":
            self.lbl_fonte.configure(text=dados)
        elif tipo == "restaurar":
            self.lbl_fonte.configure(text=f"MSI: {dados}")
        elif tipo == "resultado":
            ruins = [d for d, s in dados.items() if s not in ("CE_Success", "OK")]
            if ruins:
                log.warning("falha ao aplicar em %s", ruins)


def main():
    if "--abrir" in sys.argv:          # compatibilidade com o atalho antigo
        sys.argv.remove("--abrir")
    if "--sair" in sys.argv:           # fecha a cópia que está rodando (instalador)
        motor.pedir_para_sair()
        return
    if motor.ja_esta_rodando():
        return
    if not motor.e_admin():
        # Não pede administrador se a inicialização com o Windows está ligada:
        # a tarefa agendada já tem a permissão.
        if motor.inicializacao_ativa() and motor.abrir_pela_tarefa():
            motor.ja_esta_rodando()        # pede pra mostrar a janela
            return
        motor.abrir_elevado()
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RGBSync.App")
    except Exception:
        pass
    from rgb_core import DADOS
    log.info("=== app iniciado v%s %s | dados=%s | APPDATA=%s | exe=%s", VERSAO, sys.argv[1:],
             DADOS, os.environ.get("APPDATA"), sys.executable)
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    App(root, iniciar_escondido="--bandeja" in sys.argv)
    root.mainloop()


if __name__ == "__main__":
    main()
