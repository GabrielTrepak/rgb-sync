"""
RGB Sync — interface (janela + bandeja).

- Abas: Iluminação (modo, prévia, cores, brilho) e Dispositivos (liga/desliga por
  aparelho, sincronizar de novo, procurar equipamentos, ajustes).
- Fechar a janela só esconde: o app continua na bandeja (perto do relógio).
- Para sair de verdade: botão direito no ícone da bandeja → Sair.
- `--bandeja` inicia escondido (usado na inicialização do Windows).
- Só roda uma cópia; abrir de novo só mostra a janela.
- Sem administrador: se a inicialização com o Windows está ligada, abre pela tarefa
  agendada (sem aviso do Windows); senão pede administrador (o SDK da MSI exige).
"""

import ctypes
import math
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import colorchooser, filedialog

import customtkinter as ctk
import pystray
from PIL import Image

import busca
import efeitos
import gabinete
import luzes
import motor
import perfis
from icone import icone
from motor import hex_rgb, ler_config, rgb_hex, salvar_config
from rgb_core import PASTA, log

VERSAO = "3.8"
ICO = os.path.join(PASTA, "assets", "rgbsync.ico")
PNG = os.path.join(PASTA, "assets", "rgbsync.png")

PRESETS = [
    ("Branco", "#ffffff"), ("Vermelho", "#ff0000"), ("Laranja", "#ff5a00"),
    ("Amarelo", "#ffc800"), ("Verde", "#00ff40"), ("Ciano", "#00e5ff"),
    ("Azul", "#0050ff"), ("Roxo", "#8000ff"), ("Rosa", "#ff00a0"),
]

# paleta da interface (tons de brasa, combinando com o ícone da fogueira)
FUNDO = "#100f13"
CARTAO = "#1a181d"
BORDA = "#2a262d"
TEXTO = "#efeae6"
SUAVE = "#958c88"
APAGADO = "#5f5856"
DESTAQUE = "#e8641c"
DESTAQUE_HOVER = "#f07a36"
OK, ALERTA = "#3ddc84", "#ffb74d"
CINZA_OFF = "#2b282e"

MODOS = {"Papel de parede": "papel_parede", "Cor fixa": "fixo", "Efeito": "efeito"}
MONITORES = {"Principal": "principal", "Secundário": "secundario", "Os dois": "ambos"}
ABAS = ("Iluminação", "Gabinete", "Luzes", "Perfis", "Dispositivos")
LARGURA = 452
COR_SITUACAO = {"compativel": OK, "planejado": ALERTA, "nao": SUAVE}


def _nome(dic, valor):
    return next(k for k, v in dic.items() if v == valor)


def _nome_amigavel(modelo):
    m = modelo.upper()
    if "LINK" in m:
        return "Cooler e fans"
    if "DDR" in m or "VENGEANCE" in m or "DOMINATOR" in m:
        return "Memória RAM"
    if m.startswith("HS") or "HEADSET" in m:
        return "Headset"
    return modelo


class Previa(tk.Canvas):
    """Desenho de 'como estão os LEDs agora': fita do hub, pentes de RAM, headset
    e as zonas da MSI. Aparelhos desligados aparecem apagados. Atualiza só as
    cores (itemconfig), é leve."""

    def __init__(self, master):
        super().__init__(master, width=LARGURA - 40, height=60, bg=CARTAO,
                         highlightthickness=0, bd=0)
        self.arcos = set()     # itens que são arcos (pintados pela borda)
        self.itens = {}        # (dev_id, led_id) -> id   (só aparelhos ligados)
        self.msi = []          # ids das zonas MSI ligadas
        self.todos = []        # todos os itens ligados

    def _rotulo(self, x, y, texto, ativo, **kw):
        self.create_text(x, y, text=texto if ativo else f"{texto} · off",
                         fill=SUAVE if ativo else APAGADO, font=("Segoe UI", 9), **kw)

    def _item(self, item, ativo, chave=None):
        if ativo:
            self.todos.append(item)
            if chave is not None:
                self.itens.setdefault(chave, []).append(item)
        return item

    def _pintar(self, it, cor):
        if it in self.arcos:
            self.itemconfig(it, outline=cor)
        else:
            self.itemconfig(it, fill=cor)

    def montar(self, layouts):
        self.delete("all")
        self.itens, self.msi, self.todos, self.arcos = {}, [], [], set()
        w = int(self["width"])
        y = 4
        gab = layouts.get("gabinete")
        if gab:
            y = self._montar_gabinete(gab, layouts, w, y)
        fitas = [l for l in layouts["corsair"] if l[3] == 1 and l[2] > 4]
        blocos = [l for l in layouts["corsair"] if l not in fitas]
        for dev_id, modelo, ncol, nlin, leds, _chave, ativo in fitas:
            self._rotulo(0, y, _nome_amigavel(modelo), ativo, anchor="nw")
            y += 18
            cw = w / ncol
            for led_id, c, _ in leds:
                i = self.create_rectangle(c * cw, y, (c + 1) * cw + 0.6, y + 22, outline="",
                                          fill="#333" if ativo else CINZA_OFF)
                self._item(i, ativo, (dev_id, led_id))
            y += 34
        tec = layouts.get("teclado")
        if tec:
            ativo = tec["ativo"]
            self._rotulo(0, y, "Teclado", ativo, anchor="nw")
            y += 18
            u = w / 18.3                                    # largura de 1 tecla
            ys = [0, 1.25, 2.25, 3.25, 4.25, 5.25]          # vão abaixo das F
            for idx, xc, f, larg in tec["teclas"]:
                x0 = (xc - larg / 2) * u + 1.5
                y0 = y + ys[f] * u
                i = self.create_rectangle(x0, y0, x0 + larg * u - 3, y0 + u - 3, outline="",
                                          fill="#333" if ativo else CINZA_OFF)
                self._item(i, ativo, (tec["dev_id"], idx))
            y += 6.25 * u + 14
        if gab:                     # RAM/headset/MSI já foram desenhados ao lado do gabinete
            self.configure(height=y)
            return
        x, topo, alt = 0, y, 92
        for dev_id, modelo, ncol, nlin, leds, _chave, ativo in blocos:
            nome = _nome_amigavel(modelo)
            vazio = "#333" if ativo else CINZA_OFF
            if ncol * nlin == 1:                          # headset etc.
                i = self.create_oval(x + 8, topo + 22, x + 44, topo + 58, outline="", fill=vazio)
                self._item(i, ativo, (dev_id, leds[0][0]))
                self._rotulo(x + 26, topo + alt - 10, nome, ativo)
                x += 70
            else:                                         # RAM (colunas)
                bw, gap, ch = 16, 8, (alt - 26) / nlin
                larg_barras = ncol * bw + (ncol - 1) * gap
                larg = max(larg_barras, 84)
                xb = x + (larg - larg_barras) / 2
                for led_id, c, l in leds:
                    x0 = xb + c * (bw + gap)
                    i = self.create_rectangle(x0, topo + l * ch, x0 + bw, topo + (l + 1) * ch - 1,
                                              outline="", fill=vazio)
                    self._item(i, ativo, (dev_id, led_id))
                self._rotulo(x + larg / 2, topo + alt - 10, nome, ativo)
                x += larg + 12
        for nome, _chave, ativo in layouts["msi"]:
            i = self.create_rectangle(x + 10, topo + 14, x + 62, topo + 62, outline="",
                                      fill="#333" if ativo else CINZA_OFF)
            if ativo:
                self.msi.append(i)
                self.todos.append(i)
            self._rotulo(x + 36, topo + alt - 10, nome, ativo)
            x += 86
        if layouts["corsair"] or layouts["msi"] or layouts.get("teclado"):
            y = topo + alt
        else:
            self.create_text(w / 2, 30, text="Conectando aos dispositivos…", fill=SUAVE,
                             font=("Segoe UI", 10))
            y = 60
        self.configure(height=y)

    def _montar_gabinete(self, gab, layouts, w, y):
        """Gabinete visto pelo vidro (fans como anéis de LED nos lugares reais) e, ao lado,
        RAM, headset e as zonas da MSI. Devolve o y logo abaixo."""
        ativo = gab["ativo"]
        GW = 262
        GH = GW * gabinete.ALTURA
        self._rotulo(0, y, "Gabinete", ativo, anchor="nw")
        y += 18
        topo = y

        def reg(it, chave, _sub):
            self.arcos.add(it)
            self._item(it, ativo, chave)
        GH = desenhar_gabinete(self, gab, 0, y, GW, reg, nomes=False, ativo=ativo)
        # coluna da direita
        bx, by = GW + 18, topo + 4
        xx = bx
        blocos = [l for l in layouts["corsair"] if not (l[3] == 1 and l[2] > 4)]
        for dev_id, modelo, ncol, nlin, leds, _chave, at in blocos:
            vazio = "#333" if at else CINZA_OFF
            if ncol * nlin == 1:
                it = self.create_oval(xx + 6, by + 22, xx + 36, by + 52, outline="", fill=vazio)
                self._item(it, at, (dev_id, leds[0][0]))
                self._rotulo(xx + 21, by + 82, "Headset", at)
                xx += 58
            else:
                bw, gap, ch = 11, 6, 70 / nlin
                for led_id, c, l in leds:
                    x0 = xx + 6 + c * (bw + gap)
                    it = self.create_rectangle(x0, by + l * ch, x0 + bw, by + (l + 1) * ch - 1,
                                               outline="", fill=vazio)
                    self._item(it, at, (dev_id, led_id))
                self._rotulo(xx + 6 + (ncol * (bw + gap) - gap) / 2, by + 82, "RAM", at)
                xx += ncol * (bw + gap) + 24
        mx, my = bx, by + 100
        for nome, _chave, at in layouts["msi"]:
            it = self.create_rectangle(mx + 4, my, mx + 40, my + 36, outline="",
                                       fill="#333" if at else CINZA_OFF)
            if at:
                self.msi.append(it)
                self.todos.append(it)
            self._rotulo(mx + 22, my + 48, "GPU" if "vídeo" in nome else "Placa-mãe", at)
            mx += 62
        return max(topo + GH, my + 58) + 12

    def tudo(self, hexa):
        for i in self.todos:
            self._pintar(i, hexa)

    def leds(self, cores):
        for chave, rgb in cores.items():
            for i in self.itens.get(chave, ()):
                self._pintar(i, rgb_hex(rgb))

    def zonas_msi(self, hexa):
        for i in self.msi:
            self.itemconfig(i, fill=hexa)


def _ret_arred(cv, x0, y0, x1, y1, r, **kw):
    """Retângulo de cantos arredondados (o Tk não tem)."""
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


NOMES_CURTOS = {"topo_tras": "trás", "topo_meio": "meio", "topo_frente": "frente",
                "lateral_cima": "cima", "lateral_baixo": "baixo", "traseira": "traseira",
                "frente_baixo": "base", "bomba": "cooler"}


def desenhar_gabinete(cv, gab, x0, y0, W, registrar, nomes=True, ativo=True):
    """Desenha o gabinete visto pelo vidro: caixa, placa-mãe com RAM, placa de vídeo,
    fans QX (quadro + anel de luz contínuo + pás) e o cooler (bloco + tela redonda).
    Cada LED vira um pedaço de arco do anel; registrar(item, chave, indice_sub) guarda
    os itens pra pintar depois. Devolve a altura usada."""
    H = W * gabinete.ALTURA
    X = lambda f: x0 + f * W                       # noqa: E731
    Y = lambda f: y0 + f * H                       # noqa: E731
    _ret_arred(cv, X(0) + 1, Y(0) + 1, X(1) - 1, Y(1) - 1, 10, fill="#141217",
               outline="#3a353d", width=2)
    px0, py0, px1, py1 = gabinete.PLACA_MAE
    _ret_arred(cv, X(px0), Y(py0), X(px1), Y(py1), 4, fill="#18161b", outline="#29252d")
    for a, b, c, d in gabinete.PENTES_RAM:
        cv.create_rectangle(X(a), Y(b), X(c), Y(d), fill="#2a262e", outline="")
    gx0, gy0, gx1, gy1 = gabinete.PLACA_VIDEO
    _ret_arred(cv, X(gx0), Y(gy0), X(gx1), Y(gy1), 4, fill="#1d1a20", outline="#302b33")
    if nomes:
        cv.create_text(X((gx0 + gx1) / 2), Y((gy0 + gy1) / 2), text="placa de vídeo",
                       fill="#3d3840", font=("Segoe UI", 8))
        cv.create_text(X(0.01), Y(1) + 9, text="◀ trás do gabinete", anchor="w",
                       fill=APAGADO, font=("Segoe UI", 8))
        cv.create_text(X(0.99), Y(1) + 9, text="frente ▶", anchor="e", fill=APAGADO,
                       font=("Segoe UI", 8))
    vazio = "#3a3540" if ativo else CINZA_OFF
    for i, papel, leds in gab["desenho"]:
        fx, fy, fr, _nome = gabinete.POSICOES.get(papel, gabinete.POSICOES["traseira"])
        cx, cy, rr = X(fx), Y(fy), fr * W
        cooler = papel == "bomba"
        lado = rr * (1.10 if cooler else 1.22)
        _ret_arred(cv, cx - lado, cy - lado, cx + lado, cy + lado, max(3, rr * 0.25),
                   fill="#232027" if cooler else "#19171c",
                   outline="#3a353f" if cooler else "#2b272f")
        n = max(1, len(leds))
        larg = max(2.0, rr * (0.22 if cooler else 0.26))
        ext = 360 / n
        for k, (led, _lx, _ly) in enumerate(leds):
            centro = 90 - 360 * k / n                    # começa no topo, sentido horário
            it = cv.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, start=centro - ext / 2 - 0.6,
                               extent=ext + 1.2, style="arc", outline=vazio, width=larg)
            registrar(it, (gab["dev_id"], led), i)
        if cooler:                                       # tela redonda do cooler
            rt = rr - larg * 0.9
            cv.create_oval(cx - rt, cy - rt, cx + rt, cy + rt, fill="#0c0b0e", outline="#2a262e")
        else:                                            # pás e miolo da fan
            ri = rr - larg * 0.6
            for ang in (35, 125, 215, 305):
                a = math.radians(ang)
                cv.create_line(cx + math.cos(a) * rr * 0.30, cy + math.sin(a) * rr * 0.30,
                               cx + math.cos(a) * ri, cy + math.sin(a) * ri,
                               fill="#2a2630", width=max(1, rr * 0.10))
            rh = rr * 0.30
            cv.create_oval(cx - rh, cy - rh, cx + rh, cy + rh, fill="#1e1b22", outline="#3a3540")
        if nomes:
            if papel.startswith("lateral"):            # do lado (não encosta na de baixo)
                cv.create_text(cx - lado - 5, cy, text=NOMES_CURTOS[papel], anchor="e",
                               fill=SUAVE, font=("Segoe UI", 8))
            else:
                cv.create_text(cx, cy + lado + 7, text=NOMES_CURTOS.get(papel, papel),
                               fill=SUAVE, font=("Segoe UI", 8))
    return H + (18 if nomes else 0)


class CanvasGabinete(tk.Canvas):
    """Gabinete grande (aba Gabinete), ao vivo, com as cores do "Identificar"."""

    W = LARGURA - 40

    def __init__(self, master):
        super().__init__(master, width=self.W, height=int(self.W * gabinete.ALTURA) + 20,
                         bg=CARTAO, highlightthickness=0, bd=0)
        self.itens, self.por_sub, self.todos = {}, {}, []

    def _registrar(self, it, chave, sub):
        self.itens.setdefault(chave, []).append(it)
        self.por_sub.setdefault(sub, []).append(it)
        self.todos.append(it)

    def montar(self, gab):
        self.delete("all")
        self.itens, self.por_sub, self.todos = {}, {}, []
        if not gab:
            self.create_text(self.W / 2, 60, text="Nenhum hub iCUE LINK encontrado.",
                             fill=SUAVE, font=("Segoe UI", 11))
            self.configure(height=120)
            return
        h = desenhar_gabinete(self, gab, 0, 4, self.W, self._registrar)
        self.configure(height=int(h + 8))

    def leds(self, cores):
        for chave, rgb in cores.items():
            for it in self.itens.get(chave, ()):
                self.itemconfig(it, outline=rgb_hex(rgb))

    def tudo(self, hexa):
        for it in self.todos:
            self.itemconfig(it, outline=hexa)

    def identificacao(self):
        for i, its in self.por_sub.items():
            for it in its:
                self.itemconfig(it, outline=gabinete.CORES_ID[i % len(gabinete.CORES_ID)])


class App:
    def __init__(self, root, iniciar_escondido):
        self.root = root
        self.cfg = ler_config()
        self.cfg.setdefault("desligados", [])
        perfis.garantir_perfis(self.cfg)
        perfis.carregar_perfil(self.cfg, self.cfg["perfil"])
        salvar_config(self.cfg)
        self.auto_perfil = None          # perfil ligado sozinho por causa de um jogo
        self.perfil_antes_auto = None
        self.conexao = {}
        self.pronto = False
        self.cor_geral = self.cfg.get("cor_papel", self.cfg["cor"])
        self.avisou_bandeja = iniciar_escondido
        self.linhas_disp = {}
        self.ultima_busca = None

        root.title("RGB Sync")
        root.configure(fg_color=FUNDO)
        root.resizable(False, False)
        # erros dentro da interface vão pro log (no .exe não há console pra vê-los)
        root.report_callback_exception = lambda *e: log.error(
            "erro na interface", exc_info=e)
        threading.excepthook = lambda a: log.error(
            "erro numa thread", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
        try:
            root.iconbitmap(ICO)
            root.after(300, lambda: root.iconbitmap(ICO))   # o customtkinter troca o ícone
        except Exception:
            pass
        self._montar()

        self.icon = pystray.Icon("RGBSync", self._img_bandeja(), "RGB Sync", self._menu())
        self.icon.run_detached()

        motor.ouvir_outras_copias(lambda aba=None: root.after(0, self.mostrar, aba),
                                  lambda: root.after(0, self.sair),
                                  lambda cmd: root.after(0, self.comando, cmd))
        root.protocol("WM_DELETE_WINDOW", self.esconder)
        # Só a janela principal conta: <Map>/<Unmap> também chegam de cada widget que
        # aparece/some dentro dela (trocar de aba, reorganizar um cartão) — reagir a esses
        # criava um loop que travava a interface.
        root.bind("<Map>", lambda e: e.widget is root and self._visivel(True))
        root.bind("<Unmap>", lambda e: e.widget is root and self._visivel(False))

        self.trab = motor.Trabalhador(lambda t, d: root.after(0, self.ao_status, t, d),
                                      desligados=self.cfg["desligados"])
        self.trab.mapa_hub = {int(k): v for k, v in self.cfg.get("mapa_hub", {}).items()}
        self.trab.start()
        self._atualizar_modo()
        self.atalhos = perfis.Atalhos(lambda i: root.after(0, self._atalho, i))
        self.atalhos.definir(len(self.cfg["perfis"]))
        self.vigia = perfis.Vigia(lambda: self.cfg["perfis"],
                                  lambda alvo: root.after(0, self._perfil_auto, alvo))
        self.vigia.start()
        self._iniciar_luzes()
        self._mostrar_perfis()
        if iniciar_escondido:
            root.withdraw()

        def manutencao():
            motor.corrigir_tarefa_se_preciso()
            motor.garantir_atalho_menu_iniciar()
            time.sleep(20)                       # deixa o PC terminar de iniciar
            self._buscar_outros(avisar_novos=True)
        threading.Thread(target=manutencao, daemon=True).start()

    # ================================================================ montagem
    def _cartao(self, pai, titulo=None, pady=(0, 10)):
        f = ctk.CTkFrame(pai, fg_color=CARTAO, corner_radius=14, border_width=1,
                         border_color=BORDA)
        f.pack(fill="x", padx=16, pady=pady)
        if titulo:
            ctk.CTkLabel(f, text=titulo, text_color=SUAVE, font=("Segoe UI", 12)).pack(
                anchor="w", padx=16, pady=(10, 0))
        return f

    def _botao(self, pai, texto, cmd, primario=False, **kw):
        if primario:
            return ctk.CTkButton(pai, text=texto, command=cmd, fg_color=DESTAQUE,
                                 hover_color=DESTAQUE_HOVER, text_color="#1a0d05",
                                 font=("Segoe UI Semibold", 12), height=32, **kw)
        return ctk.CTkButton(pai, text=texto, command=cmd, fg_color="#2a272d",
                             hover_color="#36323a", text_color=TEXTO, font=("Segoe UI", 12),
                             height=32, **kw)

    def _segmentado(self, pai, valores, cmd, altura=30, fonte=("Segoe UI", 12), forte=False):
        return ctk.CTkSegmentedButton(
            pai, values=valores, command=cmd, height=altura, font=fonte,
            fg_color=CARTAO if forte else FUNDO, unselected_color=CARTAO if forte else FUNDO,
            unselected_hover_color="#26232a",
            selected_color=DESTAQUE if forte else "#3a3438",
            selected_hover_color=DESTAQUE_HOVER if forte else "#443d42",
            text_color=TEXTO, corner_radius=12 if forte else 8)

    def _montar(self):
        r = self.root
        # largura fixa: a janela não "pula" ao trocar de aba
        tk.Frame(r, width=LARGURA + 32, height=1, bg=FUNDO).pack()
        topo = ctk.CTkFrame(r, fg_color="transparent")
        topo.pack(fill="x", padx=18, pady=(16, 10))
        try:
            img = ctk.CTkImage(Image.open(PNG), size=(36, 36))
            ctk.CTkLabel(topo, image=img, text="").pack(side="left")
        except Exception:
            pass
        ctk.CTkLabel(topo, text="RGB Sync", text_color=TEXTO,
                     font=("Segoe UI Semibold", 20)).pack(side="left", padx=(10, 0))
        self.lbl_estado = ctk.CTkLabel(topo, text="●  Conectando…", text_color=ALERTA,
                                       font=("Segoe UI", 12))
        self.lbl_estado.pack(side="right")

        # abas
        self.seg_aba = ctk.CTkSegmentedButton(
            r, values=list(ABAS), command=self._mudar_aba, height=30,
            font=("Segoe UI", 12), fg_color=FUNDO, unselected_color=FUNDO,
            unselected_hover_color="#1d1b20", selected_color="#2e2a31",
            selected_hover_color="#2e2a31", text_color=TEXTO)
        self.seg_aba.set(ABAS[0])
        self.seg_aba.pack(fill="x", padx=16, pady=(0, 10))

        self.pag_luz = ctk.CTkFrame(r, fg_color="transparent")
        self.pag_gab = ctk.CTkFrame(r, fg_color="transparent")
        self.pag_luzes = ctk.CTkFrame(r, fg_color="transparent")
        self.pag_perf = ctk.CTkFrame(r, fg_color="transparent")
        self.pag_disp = ctk.CTkFrame(r, fg_color="transparent")
        self._montar_luz(self.pag_luz)
        self._montar_aba_gabinete(self.pag_gab)
        self._montar_aba_luzes(self.pag_luzes)
        self._montar_perfis(self.pag_perf)
        self._montar_disp(self.pag_disp)
        self.pag_luz.pack(fill="x")

        self.rodape = ctk.CTkLabel(
            r, text=f"Fechar a janela mantém o RGB Sync na bandeja  ·  v{VERSAO}",
            text_color="#5c5558", font=("Segoe UI", 10))
        self.rodape.pack(pady=(0, 12))

    def _montar_luz(self, p):
        lp = ctk.CTkFrame(p, fg_color="transparent")
        lp.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(lp, text="Perfil", text_color=SUAVE, font=("Segoe UI", 12)).pack(
            side="left", padx=(2, 10))
        self.seg_perfil = self._segmentado(lp, list(self.cfg["perfis"]),
                                           lambda n: self.aplicar_perfil(n))
        self.seg_perfil.set(self.cfg["perfil"])
        self.seg_perfil.pack(side="left", fill="x", expand=True)
        self.seg_modo = self._segmentado(p, list(MODOS), self._mudar_modo, altura=38,
                                         fonte=("Segoe UI Semibold", 13), forte=True)
        self.seg_modo.set(_nome(MODOS, self.cfg["modo"]))
        self.seg_modo.pack(fill="x", padx=16, pady=(0, 10))

        cp = self._cartao(p, "Seus LEDs agora")
        self.card_previa = cp
        self.previa = Previa(cp)
        self.previa.pack(padx=20, pady=(6, 14))
        self.previa.montar({"corsair": [], "msi": []})

        # papel de parede
        self.c_papel = self._cartao(p)
        linha = ctk.CTkFrame(self.c_papel, fg_color="transparent")
        linha.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(linha, text="Monitor", text_color=TEXTO, font=("Segoe UI", 13)).pack(
            side="left")
        self.seg_monitor = self._segmentado(linha, list(MONITORES), self._mudar_monitor)
        self.seg_monitor.set(_nome(MONITORES, self.cfg["monitor"]))
        self.seg_monitor.pack(side="right")
        self.lbl_fonte = ctk.CTkLabel(self.c_papel, text="", text_color=SUAVE,
                                      font=("Segoe UI", 11), justify="left")
        self.lbl_fonte.pack(anchor="w", padx=16, pady=(0, 10))

        # cor fixa
        self.c_fixo = self._cartao(p)
        grade = ctk.CTkFrame(self.c_fixo, fg_color="transparent")
        grade.pack(fill="x", padx=14, pady=(14, 8))
        for i, (_nome_cor, cor) in enumerate(PRESETS):
            ctk.CTkButton(grade, text="", width=34, height=34, corner_radius=17,
                          fg_color=cor, hover_color=cor, border_width=2, border_color=CARTAO,
                          command=lambda c=cor: self.definir(c)).grid(row=0, column=i, padx=3)
        linha2 = ctk.CTkFrame(self.c_fixo, fg_color="transparent")
        linha2.pack(fill="x", padx=16, pady=(0, 14))
        self.amostra = ctk.CTkFrame(linha2, width=34, height=34, corner_radius=8,
                                    fg_color=self.cfg["cor"])
        self.amostra.pack(side="left")
        self.ent_hex = ctk.CTkEntry(linha2, width=96, height=32, fg_color=FUNDO,
                                    border_color=BORDA, text_color=TEXTO, font=("Consolas", 13))
        self.ent_hex.insert(0, self.cfg["cor"].upper())
        self.ent_hex.bind("<Return>", self._hex_digitado)
        self.ent_hex.bind("<FocusOut>", self._hex_digitado)
        self.ent_hex.pack(side="left", padx=10)
        self._botao(linha2, "Escolher cor…", self.escolher, width=120).pack(side="right")
        ctk.CTkButton(linha2, text="Apagar", width=70, height=32, fg_color="transparent",
                      border_width=1, border_color=BORDA, hover_color="#26232a",
                      text_color=SUAVE, font=("Segoe UI", 12),
                      command=lambda: self.definir("#000000")).pack(side="right", padx=8)

        # efeito
        self.c_efeito = self._cartao(p)
        le = ctk.CTkFrame(self.c_efeito, fg_color="transparent")
        le.pack(fill="x", padx=16, pady=(12, 6))
        self.seg_efeito = self._segmentado(le, list(efeitos.TIPOS), self._mudar_efeito)
        self.seg_efeito.set(_nome(efeitos.TIPOS, self.cfg["efeito"]))
        self.seg_efeito.pack(fill="x")
        lv = ctk.CTkFrame(self.c_efeito, fg_color="transparent")
        lv.pack(fill="x", padx=16, pady=(4, 6))
        ctk.CTkLabel(lv, text="Velocidade", text_color=TEXTO, font=("Segoe UI", 13)).pack(
            side="left")
        self.seg_vel = self._segmentado(lv, list(efeitos.VELOCIDADES), self._mudar_vel)
        self.seg_vel.set(_nome(efeitos.VELOCIDADES, self.cfg["velocidade"]))
        self.seg_vel.pack(side="right")
        # cor (respiração)
        self.l_ef_cor = ctk.CTkFrame(self.c_efeito, fg_color="transparent")
        ctk.CTkLabel(self.l_ef_cor, text="Cor", text_color=TEXTO, font=("Segoe UI", 13)).pack(
            side="left")
        self._botao(self.l_ef_cor, "Escolher…", self.escolher_cor_efeito, width=90).pack(
            side="right")
        self.amostra_ef = ctk.CTkFrame(self.l_ef_cor, width=28, height=28, corner_radius=8,
                                       fg_color=self.cfg["cor"])
        self.amostra_ef.pack(side="right", padx=8)
        for _n, cor in reversed(PRESETS[:7]):
            ctk.CTkButton(self.l_ef_cor, text="", width=22, height=22, corner_radius=11,
                          fg_color=cor, hover_color=cor,
                          command=lambda c=cor: self.cor_efeito(c)).pack(side="right", padx=2)
        # fonte (temperatura)
        self.l_ef_fonte = ctk.CTkFrame(self.c_efeito, fg_color="transparent")
        self.seg_fonte = self._segmentado(self.l_ef_fonte, list(efeitos.FONTES),
                                          self._mudar_fonte)
        self.seg_fonte.set(_nome(efeitos.FONTES, self.cfg["fonte_temp"]))
        self.seg_fonte.pack(side="left")
        self.lbl_sensor = ctk.CTkLabel(self.l_ef_fonte, text="", text_color=SUAVE,
                                       font=("Segoe UI Semibold", 13))
        self.lbl_sensor.pack(side="right")
        self.lbl_ef_info = ctk.CTkLabel(self.c_efeito, text="", text_color=SUAVE,
                                        font=("Segoe UI", 10), justify="left",
                                        wraplength=LARGURA - 40)
        self.lbl_ef_info.pack(anchor="w", padx=16, pady=(0, 10))

        # brilho
        cb = self._cartao(p)
        lb = ctk.CTkFrame(cb, fg_color="transparent")
        lb.pack(fill="x", padx=16, pady=(12, 12))
        ctk.CTkLabel(lb, text="Brilho", text_color=TEXTO, font=("Segoe UI", 13)).pack(side="left")
        self.lbl_brilho = ctk.CTkLabel(lb, text=f"{int(self.cfg['brilho'])}%", width=44,
                                       text_color=SUAVE, font=("Segoe UI", 12))
        self.lbl_brilho.pack(side="right")
        self.sl_brilho = ctk.CTkSlider(lb, from_=0, to=100, number_of_steps=100,
                                       command=self._mudar_brilho, button_color=DESTAQUE,
                                       button_hover_color=DESTAQUE_HOVER,
                                       progress_color=DESTAQUE, fg_color="#2a272d")
        self.sl_brilho.set(self.cfg["brilho"])
        self.sl_brilho.pack(side="right", fill="x", expand=True, padx=(16, 8))

    def _montar_disp(self, p):
        # ações
        acoes = ctk.CTkFrame(p, fg_color="transparent")
        acoes.pack(fill="x", padx=16, pady=(0, 10))
        self.bt_resync = self._botao(acoes, "⟳  Sincronizar tudo de novo", self.recarregar,
                                     primario=True)
        self.bt_resync.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.bt_busca = self._botao(acoes, "Procurar dispositivos", self.procurar)
        self.bt_busca.pack(side="left", fill="x", expand=True, padx=(5, 0))

        # aparelhos controlados
        c = self._cartao(p, "Sincronizando")
        self.lista_disp = ctk.CTkFrame(c, fg_color="transparent")
        self.lista_disp.pack(fill="x", padx=12, pady=(4, 10))
        ctk.CTkLabel(self.lista_disp, text="Conectando…", text_color=SUAVE,
                     font=("Segoe UI", 11)).pack(anchor="w", padx=4)

        # outros equipamentos
        c2 = self._cartao(p, "Equipamentos RGB conectados")
        self.lista_outros = ctk.CTkFrame(c2, fg_color="transparent")
        self.lista_outros.pack(fill="x", padx=12, pady=(4, 2))
        ctk.CTkLabel(self.lista_outros, text="Clique em “Procurar dispositivos”.",
                     text_color=SUAVE, font=("Segoe UI", 11)).pack(anchor="w", padx=4)
        self.lbl_busca = ctk.CTkLabel(c2, text="", text_color=APAGADO, font=("Segoe UI", 10),
                                      wraplength=LARGURA - 40, justify="left")
        self.lbl_busca.pack(anchor="w", padx=16, pady=(0, 8))

        # ajustes
        ca = self._cartao(p)
        la = ctk.CTkFrame(ca, fg_color="transparent")
        la.pack(fill="x", padx=16, pady=(12, 8))
        self.var_inicio = ctk.BooleanVar(value=motor.inicializacao_ativa())
        ctk.CTkSwitch(la, text="Iniciar com o Windows", variable=self.var_inicio,
                      command=self._mudar_inicio, text_color=TEXTO, font=("Segoe UI", 13),
                      progress_color=DESTAQUE).pack(side="left")
        ctk.CTkButton(la, text="Restaurar MSI original", width=10, height=26,
                      fg_color="transparent", hover_color="#26232a", text_color=SUAVE,
                      font=("Segoe UI", 11), command=self.restaurar).pack(side="right")

    # ================================================================ perfis
    def _salvar(self):
        perfis.guardar_no_perfil(self.cfg)
        salvar_config(self.cfg)

    def _ordem_perfis(self):
        return list(self.cfg["perfis"])

    def aplicar_perfil(self, nome, motivo=None):
        """Troca de perfil e atualiza tudo (janela, bandeja, aparelhos, cores).
        motivo: None (clique na janela), "atalho" ou "programa"."""
        if nome not in self.cfg["perfis"]:
            return
        if motivo != "programa":
            self.auto_perfil = None              # escolha manual manda
        self._salvar()                           # guarda o atual antes de trocar
        perfis.carregar_perfil(self.cfg, nome)
        self.seg_perfil.set(nome)
        self.seg_modo.set(_nome(MODOS, self.cfg["modo"]))
        self.seg_monitor.set(_nome(MONITORES, self.cfg["monitor"]))
        self.sl_brilho.set(self.cfg["brilho"])
        self.lbl_brilho.configure(text=f"{int(self.cfg['brilho'])}%")
        self.amostra.configure(fg_color=self.cfg["cor"])
        self.ent_hex.delete(0, "end")
        self.ent_hex.insert(0, self.cfg["cor"].upper())
        self.seg_efeito.set(_nome(efeitos.TIPOS, self.cfg["efeito"]))
        self.seg_vel.set(_nome(efeitos.VELOCIDADES, self.cfg["velocidade"]))
        self.seg_fonte.set(_nome(efeitos.FONTES, self.cfg["fonte_temp"]))
        self._atualizar_modo()
        if self.pronto:
            self.trab.desligar_dispositivos(set(self.cfg["desligados"]))
        self.enviar()
        self.icon.update_menu()
        self._mostrar_perfis()
        log.info("perfil: %s (%s)", nome, motivo or "janela")
        if motivo:
            try:
                extra = " (programa aberto)" if motivo == "programa" else ""
                self.icon.notify(f"Perfil \u201c{nome}\u201d{extra}", "RGB Sync")
            except Exception:
                pass

    def _atalho(self, i):
        ordem = self._ordem_perfis()
        if i < len(ordem):
            self.aplicar_perfil(ordem[i], "atalho")

    def _perfil_auto(self, alvo):
        """O vigia avisou: um programa associado abriu (alvo) ou fechou (None)."""
        if alvo:
            if alvo != self.cfg["perfil"]:
                if not self.auto_perfil:
                    self.perfil_antes_auto = self.cfg["perfil"]
                self.aplicar_perfil(alvo, "programa")
            self.auto_perfil = alvo
        elif self.auto_perfil:
            volta = self.perfil_antes_auto
            if self.cfg["perfil"] == self.auto_perfil and volta in self.cfg["perfis"]:
                self.aplicar_perfil(volta, "programa")
            self.auto_perfil = self.perfil_antes_auto = None

    def _perfis_mudaram(self):
        self.seg_perfil.configure(values=self._ordem_perfis())
        self.seg_perfil.set(self.cfg["perfil"])
        self.atalhos.definir(len(self.cfg["perfis"]))
        self.icon.update_menu()
        self._salvar()
        self._mostrar_perfis()

    def novo_perfil(self):
        nome = ctk.CTkInputDialog(text="Nome do novo perfil (copia o atual):",
                                  title="Novo perfil").get_input()
        nome = (nome or "").strip()[:20]
        if not nome or nome in self.cfg["perfis"]:
            return
        self._salvar()
        atual = self.cfg["perfis"][self.cfg["perfil"]]
        self.cfg["perfis"][nome] = dict(atual, desligados=list(atual["desligados"]),
                                        programas=[])
        self.cfg["perfil"] = nome
        self._perfis_mudaram()

    def renomear_perfil(self, nome):
        novo = ctk.CTkInputDialog(text=f"Novo nome para \u201c{nome}\u201d:",
                                  title="Renomear perfil").get_input()
        novo = (novo or "").strip()[:20]
        if not novo or novo in self.cfg["perfis"]:
            return
        self.cfg["perfis"] = {(novo if k == nome else k): v
                              for k, v in self.cfg["perfis"].items()}
        if self.cfg["perfil"] == nome:
            self.cfg["perfil"] = novo
        self._perfis_mudaram()

    def excluir_perfil(self, nome):
        if len(self.cfg["perfis"]) <= 1:
            return
        del self.cfg["perfis"][nome]
        if self.cfg["perfil"] == nome:
            # o perfil ativo sumiu: carrega outro (sem salvar o apagado em cima dele)
            self.aplicar_perfil(next(iter(self.cfg["perfis"])))
        self._perfis_mudaram()

    def mover_perfil(self, nome, delta):
        ordem = self._ordem_perfis()
        i = ordem.index(nome)
        j = max(0, min(len(ordem) - 1, i + delta))
        ordem.insert(j, ordem.pop(i))
        self.cfg["perfis"] = {k: self.cfg["perfis"][k] for k in ordem}
        self._perfis_mudaram()

    def adicionar_programa(self, nome):
        caminho = filedialog.askopenfilename(
            title=f"Programa que ativa o perfil {nome}",
            filetypes=[("Programas", "*.exe"), ("Todos os arquivos", "*.*")])
        if caminho:
            exe = os.path.basename(caminho)
            progs = self.cfg["perfis"][nome].setdefault("programas", [])
            if exe.lower() not in (x.lower() for x in progs):
                progs.append(exe)
            self._perfis_mudaram()

    def remover_programa(self, nome, exe):
        progs = self.cfg["perfis"][nome].get("programas", [])
        if exe in progs:
            progs.remove(exe)
        self._perfis_mudaram()

    def _montar_perfis(self, p):
        topo = ctk.CTkFrame(p, fg_color="transparent")
        topo.pack(fill="x", padx=16, pady=(0, 10))
        self._botao(topo, "+  Novo perfil (copia o atual)", self.novo_perfil,
                    primario=True).pack(side="left", fill="x", expand=True)
        self.lista_perfis = ctk.CTkFrame(p, fg_color="transparent")
        self.lista_perfis.pack(fill="x")
        dica = self._cartao(p)
        ctk.CTkLabel(dica, text="O que você muda na aba Iluminação fica salvo no perfil ativo.\n"
                     "Os atalhos funcionam em qualquer lugar, inclusive dentro de jogos.\n"
                     "Com um programa associado aberto, o perfil liga sozinho;\n"
                     "ao fechar o programa, volta o perfil anterior.",
                     text_color=SUAVE, font=("Segoe UI", 10), justify="left").pack(
            anchor="w", padx=16, pady=10)

    def _resumo_perfil(self, p):
        if p["modo"] == "efeito":
            txt = "Efeito: " + _nome(efeitos.TIPOS, p.get("efeito", "respiracao"))
            if p.get("efeito") == "temperatura":
                txt += " (" + ("GPU" if p.get("fonte_temp", "gpu") == "gpu" else "CPU") + ")"
        elif p["modo"] == "papel_parede":
            txt = f"Papel de parede ({_nome(MONITORES, p.get('monitor', 'principal')).lower()})"
        else:
            txt = "Cor fixa" if p["cor"] != "#000000" else "Apagado"
        txt += f" · {int(p['brilho'])}%"
        if p.get("desligados"):
            txt += f" · {len(p['desligados'])} desligado(s)"
        return txt

    def _mostrar_perfis(self):
        if not hasattr(self, "lista_perfis"):
            return
        for w in self.lista_perfis.winfo_children():
            w.destroy()
        ordem = self._ordem_perfis()
        for i, nome in enumerate(ordem):
            p = self.cfg["perfis"][nome]
            ativo = nome == self.cfg["perfil"]
            c = ctk.CTkFrame(self.lista_perfis, fg_color=CARTAO, corner_radius=14,
                             border_width=2 if ativo else 1,
                             border_color=DESTAQUE if ativo else BORDA)
            c.pack(fill="x", padx=16, pady=(0, 8))
            l1 = ctk.CTkFrame(c, fg_color="transparent")
            l1.pack(fill="x", padx=12, pady=(10, 0))
            ctk.CTkFrame(l1, width=18, height=18, corner_radius=9,
                         fg_color=p["cor"] if p["modo"] == "fixo" else DESTAQUE).pack(
                side="left", padx=(2, 8))
            ctk.CTkLabel(l1, text=nome, text_color=TEXTO,
                         font=("Segoe UI Semibold", 13)).pack(side="left")
            if i < 9:
                ctk.CTkLabel(l1, text=f" {perfis.texto_atalho(i)} ", fg_color="#2a272d",
                             corner_radius=6, text_color=SUAVE, font=("Consolas", 10),
                             height=18).pack(side="left", padx=8)
            if ativo:
                ctk.CTkLabel(l1, text="ATIVO", text_color=DESTAQUE,
                             font=("Segoe UI Semibold", 10)).pack(side="left")
            else:
                ctk.CTkButton(l1, text="Ativar", width=60, height=24, fg_color=DESTAQUE,
                              hover_color=DESTAQUE_HOVER, text_color="#1a0d05",
                              font=("Segoe UI Semibold", 11),
                              command=lambda n=nome: self.aplicar_perfil(n)).pack(side="right")
            ctk.CTkLabel(c, text=self._resumo_perfil(p), text_color=SUAVE,
                         font=("Segoe UI", 10), anchor="w").pack(anchor="w", padx=40)
            lp = ctk.CTkFrame(c, fg_color="transparent")
            lp.pack(fill="x", padx=36, pady=(4, 0))
            for exe in p.get("programas", []):
                ctk.CTkButton(lp, text=f"{exe}  \u2715", height=22, width=10,
                              fg_color="#2a272d", hover_color="#4a2a26", text_color=TEXTO,
                              font=("Segoe UI", 10),
                              command=lambda n=nome, e=exe: self.remover_programa(n, e)).pack(
                    side="left", padx=(0, 4), pady=2)
            ctk.CTkButton(lp, text="+ programa que ativa", height=22, width=10,
                          fg_color="transparent", border_width=1, border_color=BORDA,
                          hover_color="#26232a", text_color=SUAVE, font=("Segoe UI", 10),
                          command=lambda n=nome: self.adicionar_programa(n)).pack(
                side="left", pady=2)
            la = ctk.CTkFrame(c, fg_color="transparent")
            la.pack(fill="x", padx=32, pady=(2, 8))

            def peq(texto, cmd, cor=SUAVE, pai=la):
                return ctk.CTkButton(pai, text=texto, width=10, height=22,
                                     fg_color="transparent", hover_color="#26232a",
                                     text_color=cor, font=("Segoe UI", 10), command=cmd)
            peq("Renomear", lambda n=nome: self.renomear_perfil(n)).pack(side="left")
            if len(ordem) > 1:
                peq("Excluir", lambda n=nome: self.excluir_perfil(n), "#d0625a").pack(
                    side="left")
            if i > 0:
                peq("\u2191", lambda n=nome: self.mover_perfil(n, -1)).pack(side="right")
            if i < len(ordem) - 1:
                peq("\u2193", lambda n=nome: self.mover_perfil(n, 1)).pack(side="right")
        falharam = getattr(getattr(self, "atalhos", None), "falharam", [])
        if falharam:
            ctk.CTkLabel(self.lista_perfis, text="\u26a0 Atalhos já usados por outro programa: "
                         + ", ".join(falharam), text_color=ALERTA,
                         font=("Segoe UI", 10)).pack(anchor="w", padx=20, pady=(0, 6))

    # ================================================================ abas
    def _mudar_aba(self, nome):
        paginas = dict(zip(ABAS, (self.pag_luz, self.pag_gab, self.pag_luzes, self.pag_perf,
                                  self.pag_disp)))
        for pg in paginas.values():
            pg.pack_forget()
        paginas.get(nome, self.pag_luz).pack(fill="x", before=self.rodape)
        self.seg_aba.set(nome)
        self._vigiar_luzes()

    # ================================================================ lista de dispositivos
    def _linha(self, pai, titulo, sub, cor_sub=SUAVE, direita=None, selo=None):
        f = ctk.CTkFrame(pai, fg_color="transparent")
        f.pack(fill="x", pady=3)
        txt = ctk.CTkFrame(f, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True, padx=4)
        lt = ctk.CTkFrame(txt, fg_color="transparent")
        lt.pack(anchor="w")
        ctk.CTkLabel(lt, text=titulo, text_color=TEXTO, font=("Segoe UI", 12), height=18,
                     anchor="w").pack(side="left")
        if selo:
            ctk.CTkLabel(lt, text=f" {selo} ", fg_color=DESTAQUE, text_color="#1a0d05",
                         corner_radius=6, font=("Segoe UI Semibold", 9), height=16).pack(
                side="left", padx=6)
        ctk.CTkLabel(txt, text=sub, text_color=cor_sub, font=("Segoe UI", 10), height=14,
                     anchor="w").pack(anchor="w")
        if direita is not None:
            direita(f).pack(side="right", padx=4)
        return f

    def _mostrar_dispositivos(self, lista):
        for w in self.lista_disp.winfo_children():
            w.destroy()
        if not lista:
            ctk.CTkLabel(self.lista_disp, text="Nenhum aparelho conectado ainda.",
                         text_color=SUAVE, font=("Segoe UI", 11)).pack(anchor="w", padx=4)
            return
        for d in lista:
            var = ctk.BooleanVar(value=d["ativo"])

            def chave_sw(pai, d=d, var=var):
                return ctk.CTkSwitch(pai, text="", width=44, variable=var,
                                     progress_color=DESTAQUE,
                                     command=lambda: self._alternar(d["chave"], var.get()))
            if d["marca"] == "HyperX":
                titulo, det = "Teclado", f"{d['nome']} ({d.get('layout', '')})"
                qtd = f"{d['leds']} teclas"
            elif d["marca"] == "MSI":                    # "Placa de vídeo (RTX ...)"
                titulo, _, det = d["nome"].partition(" (")
                det = det.rstrip(")")
                qtd = f"{d['leds']} {'zona' if d['leds'] == 1 else 'zonas'}"
            else:
                titulo, det = _nome_amigavel(d["nome"]), d["nome"]
                qtd = f"{d['leds']} {'LED' if d['leds'] == 1 else 'LEDs'}"
            sub = " · ".join(x for x in (d["marca"], det if det != titulo else "", qtd) if x)
            if not d["ativo"]:
                sub += " · fora da sincronização"
            self._linha(self.lista_disp, titulo, sub, cor_sub=SUAVE if d["ativo"] else APAGADO,
                        direita=chave_sw)
            if d.get("aviso"):
                ctk.CTkLabel(self.lista_disp, text=f"⚠  {d['aviso']}", text_color=ALERTA,
                             font=("Segoe UI", 10), anchor="w", wraplength=LARGURA - 60,
                             justify="left").pack(anchor="w", padx=4, pady=(0, 4))
                if not getattr(self, "_avisou_ngenuity", False):
                    self._avisou_ngenuity = True
                    try:
                        self.icon.notify(d["aviso"], "RGB Sync — teclado")
                    except Exception:
                        pass

    # ---- luzes da casa (Tuya)
    PRESETS_LUZ = [("#ff0000"), ("#ff5a00"), ("#ffc800"), ("#00ff40"), ("#00e5ff"),
                   ("#0050ff"), ("#8000ff"), ("#ff00a0")]

    def _iniciar_luzes(self):
        self.luzes = {}
        self.cfg.setdefault("luzes", {})
        try:
            luzes.importar_automatico()
        except Exception:
            log.exception("importar luzes")
        for info in luzes.ler():
            self._nova_luz(info)
        self._mostrar_luzes()
        self._sync_t = 0.0
        self.root.after(500, self._tique_sync)

    def _nova_luz(self, info):
        luz = luzes.Luz(info, lambda i, e: self.root.after(0, self._estado_luz, i, e),
                        lambda i, ip: self.root.after(0, self._ip_luz, i, ip))
        self.luzes[info["id"]] = luz
        self.cfg["luzes"].setdefault(info["id"], {"sync": False, "brilho_sync": 60})
        luz.start()
        luz.ler_agora()
        # se o app fechou com a sincronização ligada, devolve a luz como estava
        foto = self.cfg["luzes"][info["id"]].get("foto")
        if foto and not self.cfg["luzes"][info["id"]].get("sync"):
            luz.restaurar(foto)
            self.cfg["luzes"][info["id"]].pop("foto", None)

    def _ip_luz(self, id_, ip):
        lista = luzes.ler()
        for l in lista:
            if l["id"] == id_:
                l["ip"] = ip
        luzes.salvar(lista)

    def _vigiar_luzes(self):
        ver = self.seg_aba.get() == "Luzes" and self.root.state() != "withdrawn"
        for luz in getattr(self, "luzes", {}).values():
            luz.vigiar = ver
            if ver:
                luz.ler_agora()

    def _montar_aba_luzes(self, p):
        self.lista_luzes = ctk.CTkFrame(p, fg_color="transparent")
        self.lista_luzes.pack(fill="x")
        self.widgets_luz = {}
        rod = ctk.CTkFrame(p, fg_color="transparent")
        rod.pack(fill="x", padx=16, pady=(0, 10))
        self._botao(rod, "Importar luzes (devices.json)…", self.importar_luzes).pack(
            side="left")
        ctk.CTkLabel(rod, text="Tuya · Smart Life · Ekaza — direto pela rede de casa",
                     text_color=APAGADO, font=("Segoe UI", 10)).pack(side="right")

    def importar_luzes(self):
        caminho = filedialog.askopenfilename(
            title="devices.json do tinytuya wizard", filetypes=[("devices.json", "*.json")])
        if not caminho:
            return
        try:
            luzes.importar(caminho)
        except Exception:
            log.exception("importar luzes")
            return
        for info in luzes.ler():
            if info["id"] not in self.luzes:
                self._nova_luz(info)
        self._mostrar_luzes()

    def _mostrar_luzes(self):
        for w in self.lista_luzes.winfo_children():
            w.destroy()
        self.widgets_luz = {}
        if not self.luzes:
            c = self._cartao(self.lista_luzes, "Nenhuma luz configurada")
            ctk.CTkLabel(c, text="Rode o assistente (tinytuya wizard) e importe o devices.json "
                         "com o botão abaixo.", text_color=SUAVE, font=("Segoe UI", 11),
                         wraplength=LARGURA - 40, justify="left").pack(anchor="w", padx=16,
                                                                       pady=(4, 12))
            return
        for id_, luz in self.luzes.items():
            self._cartao_luz(id_, luz)

    def _cartao_luz(self, id_, luz):
        info, conf = luz.info, self.cfg["luzes"][id_]
        c = self._cartao(self.lista_luzes)
        w = {"cartao": c}
        l1 = ctk.CTkFrame(c, fg_color="transparent")
        l1.pack(fill="x", padx=16, pady=(12, 2))
        ctk.CTkLabel(l1, text="💡  " + info["nome"], text_color=TEXTO,
                     font=("Segoe UI Semibold", 15)).pack(side="left")
        w["var_on"] = ctk.BooleanVar(value=False)
        w["sw_on"] = ctk.CTkSwitch(l1, text="", width=50, variable=w["var_on"],
                                   progress_color=DESTAQUE,
                                   command=lambda: self._luz_ligar(id_))
        w["sw_on"].pack(side="right")
        w["estado"] = ctk.CTkLabel(c, text="conectando…", text_color=APAGADO,
                                   font=("Segoe UI", 10))
        w["estado"].pack(anchor="w", padx=40)

        w["seg"] = self._segmentado(c, ["Branca", "Colorida"], lambda v: self._luz_modo(id_, v))
        w["seg"].pack(fill="x", padx=16, pady=(8, 6))
        # --- branca
        fb = ctk.CTkFrame(c, fg_color="transparent")
        w["f_branca"] = fb

        def linha_slider(pai, rotulo, cmd, esq=None, dir_=None, cor=DESTAQUE):
            f = ctk.CTkFrame(pai, fg_color="transparent")
            f.pack(fill="x", padx=16, pady=3)
            ctk.CTkLabel(f, text=rotulo, width=84, anchor="w", text_color=TEXTO,
                         font=("Segoe UI", 12)).pack(side="left")
            if dir_:
                ctk.CTkLabel(f, text=dir_, text_color=SUAVE, font=("Segoe UI", 10)).pack(
                    side="right")
            sl = ctk.CTkSlider(f, from_=0, to=100, number_of_steps=100, button_color=cor,
                               button_hover_color=DESTAQUE_HOVER, progress_color=cor,
                               fg_color="#2a272d", command=lambda v: cmd())
            sl.pack(side="right", fill="x", expand=True, padx=6)
            if esq:
                ctk.CTkLabel(f, text=esq, text_color=SUAVE, font=("Segoe UI", 10)).pack(
                    side="right")
            return sl
        w["sl_brilho_b"] = linha_slider(fb, "Brilho", lambda: self._luz_branca(id_))
        w["sl_temp"] = linha_slider(fb, "Temperatura", lambda: self._luz_branca(id_),
                                    "quente", "fria", "#cdd6ff")
        # --- colorida
        fc = ctk.CTkFrame(c, fg_color="transparent")
        w["f_cor"] = fc
        pr = ctk.CTkFrame(fc, fg_color="transparent")
        pr.pack(fill="x", padx=16, pady=(2, 4))
        for cor in self.PRESETS_LUZ:
            ctk.CTkButton(pr, text="", width=30, height=30, corner_radius=15, fg_color=cor,
                          hover_color=cor, border_width=2, border_color=CARTAO,
                          command=lambda c_=cor: self._luz_cor(id_, c_)).pack(side="left", padx=2)
        w["amostra"] = ctk.CTkFrame(pr, width=30, height=30, corner_radius=8, fg_color="#333")
        self._botao(pr, "Outra…", lambda: self._luz_escolher(id_), width=64).pack(side="right")
        w["amostra"].pack(side="right", padx=6)
        w["sl_brilho_c"] = linha_slider(fc, "Brilho", lambda: self._luz_cor(id_, None))
        w["cor"] = "#ff5a00"
        # --- sincronizar (opcional)
        fs = ctk.CTkFrame(c, fg_color="transparent")
        fs.pack(fill="x", padx=16, pady=(8, 2), side="bottom")
        w["var_sync"] = ctk.BooleanVar(value=conf.get("sync", False))
        ctk.CTkSwitch(fs, text="Sincronizar com o PC", variable=w["var_sync"],
                      progress_color=DESTAQUE, text_color=TEXTO, font=("Segoe UI", 12),
                      command=lambda: self._luz_sync(id_)).pack(side="left")
        w["sl_sync"] = ctk.CTkSlider(fs, from_=5, to=100, width=110, button_color=DESTAQUE,
                                     progress_color=DESTAQUE, fg_color="#2a272d",
                                     command=lambda v: self._luz_brilho_sync(id_, v))
        w["sl_sync"].set(conf.get("brilho_sync", 60))
        w["lbl_sync"] = ctk.CTkLabel(fs, text=f"{int(conf.get('brilho_sync', 60))}%", width=34,
                                     text_color=SUAVE, font=("Segoe UI", 10))
        w["lbl_sync"].pack(side="right")
        w["sl_sync"].pack(side="right", padx=4)
        ctk.CTkLabel(c, text=f"{info.get('produto', '')} · IP {info.get('ip') or '?'} · "
                     f"protocolo {info.get('versao')}", text_color=APAGADO,
                     font=("Segoe UI", 9)).pack(anchor="w", padx=16, pady=(0, 10), side="bottom")
        self.widgets_luz[id_] = w
        self._luz_modo_ui(id_, "white")
        self._luz_sync_ui(id_)
        if luz.online is not None:
            self._estado_luz(id_, luzes.ler_estado(luz.dps, info.get("v2", True))
                             if luz.online else None)

    # ---- atualização vinda da luz (estado real, inclusive mudanças pelo celular)
    def _estado_luz(self, id_, est):
        w = self.widgets_luz.get(id_)
        if not w:
            return
        self._sem_eco = True
        try:
            if est is None:
                w["estado"].configure(text="●  sem conexão (tentando de novo…)",
                                      text_color=ALERTA)
                return
            sync = self.cfg["luzes"][id_].get("sync")
            w["estado"].configure(text="●  sincronizando com o PC" if sync else
                                  ("●  ligada" if est["ligada"] else "●  desligada"),
                                  text_color=OK if est["ligada"] else SUAVE)
            mexendo = time.monotonic() - w.get("mexeu", 0) < 3
            if not mexendo:
                w["var_on"].set(est["ligada"])
            if sync or mexendo:
                return
            modo = "colour" if est["modo"] == "colour" else "white"
            self._luz_modo_ui(id_, modo)
            if modo == "white":
                w["sl_brilho_b"].set(est["brilho"])
                w["sl_temp"].set(est["temp"])
            else:
                w["sl_brilho_c"].set(est["brilho"])
                if est["rgb"]:
                    w["cor"] = rgb_hex(est["rgb"])
                    w["amostra"].configure(fg_color=w["cor"])
        finally:
            self._sem_eco = False

    def _luz_modo_ui(self, id_, modo):
        w = self.widgets_luz[id_]
        if w.get("modo") == modo:
            return
        w["modo"] = modo
        w["seg"].set("Colorida" if modo == "colour" else "Branca")
        w["f_branca"].pack_forget()
        w["f_cor"].pack_forget()
        (w["f_cor"] if modo == "colour" else w["f_branca"]).pack(fill="x", after=w["seg"])

    def _luz_sync_ui(self, id_):
        w = self.widgets_luz[id_]
        sync = self.cfg["luzes"][id_].get("sync")
        estado = "disabled" if sync else "normal"
        for k in ("seg", "sl_brilho_b", "sl_temp", "sl_brilho_c"):
            w[k].configure(state=estado)
        w["sl_sync"].configure(state="normal" if sync else "disabled")

    # ---- comandos manuais
    def _luz_ligar(self, id_):
        if getattr(self, "_sem_eco", False):
            return
        self.widgets_luz[id_]["mexeu"] = time.monotonic()
        self.luzes[id_].ligar(self.widgets_luz[id_]["var_on"].get())

    def _luz_modo(self, id_, nome):
        self.widgets_luz[id_]["mexeu"] = time.monotonic()
        self._luz_modo_ui(id_, "colour" if nome == "Colorida" else "white")
        if nome == "Colorida":
            self._luz_cor(id_, None)
        else:
            self._luz_branca(id_)

    def _luz_branca(self, id_):
        if getattr(self, "_sem_eco", False) or self.cfg["luzes"][id_].get("sync"):
            return
        w = self.widgets_luz[id_]
        w["mexeu"] = time.monotonic()
        w["var_on"].set(True)
        self.luzes[id_].branca(w["sl_brilho_b"].get(), w["sl_temp"].get())

    def _luz_cor(self, id_, hexa):
        if getattr(self, "_sem_eco", False) or self.cfg["luzes"][id_].get("sync"):
            return
        w = self.widgets_luz[id_]
        if hexa:
            w["cor"] = hexa
            w["amostra"].configure(fg_color=hexa)
            if w["seg"].get() != "Colorida":
                self._luz_modo_ui(id_, "colour")
        w["mexeu"] = time.monotonic()
        w["var_on"].set(True)
        self.luzes[id_].cor(hex_rgb(w["cor"]), max(5, w["sl_brilho_c"].get()))

    def _luz_escolher(self, id_):
        _, hexa = colorchooser.askcolor(color=self.widgets_luz[id_]["cor"], title="Cor da luz")
        if hexa:
            self._luz_cor(id_, hexa)

    # ---- sincronizar com o PC (opcional)
    def _luz_sync(self, id_):
        conf, luz = self.cfg["luzes"][id_], self.luzes[id_]
        ligar = self.widgets_luz[id_]["var_sync"].get()
        conf["sync"] = ligar
        if ligar:
            conf["foto"] = luz.foto()           # pra voltar como estava depois
            self._sync_ultima = {}
            self._sync_luzes(forcar=True)
        else:
            luz.restaurar(conf.pop("foto", None))
            luz.ler_agora()
        self._salvar()
        self._luz_sync_ui(id_)

    def _luz_brilho_sync(self, id_, v):
        self.cfg["luzes"][id_]["brilho_sync"] = int(v)
        self.widgets_luz[id_]["lbl_sync"].configure(text=f"{int(v)}%")
        self._sync_luzes(forcar=True)

    def _cor_pc(self):
        """A cor 'geral' que o PC está mostrando agora (pra luz do teto)."""
        modo = self.cfg["modo"]
        if modo == "papel_parede":
            return self.cor_geral
        if modo == "fixo":
            return self.cfg["cor"]
        t = time.monotonic()
        tipo = self.cfg["efeito"]
        if tipo == "temperatura":
            return getattr(self, "_cor_temp", "#3c8cff")
        cor = efeitos.cor_led(tipo, t, 0.5, hex_rgb(self.cfg["cor"]), self.cfg["velocidade"])
        return rgb_hex(round(min(255, c)) for c in cor)

    def _sync_luzes(self, forcar=False):
        if not getattr(self, "luzes", None):
            return
        cor = self._cor_pc()
        for id_, luz in self.luzes.items():
            conf = self.cfg["luzes"].get(id_, {})
            if not conf.get("sync"):
                continue
            chave = (cor, conf.get("brilho_sync"))
            if forcar or getattr(self, "_sync_ultima", {}).get(id_) != chave:
                self._sync_ultima = dict(getattr(self, "_sync_ultima", {}), **{id_: chave})
                luz.cor(hex_rgb(cor), conf.get("brilho_sync", 60))

    def _tique_sync(self):
        """Efeitos animados mudam a cor o tempo todo: manda pra luz ~3x por segundo."""
        try:
            if self.cfg["modo"] == "efeito" and self.cfg["efeito"] != "temperatura":
                self._sync_luzes()
        finally:
            self.root.after(350, self._tique_sync)

    # ---- gabinete
    NOMES_TIPO = {9: "Cooler (bomba)", 12: "Fan QX"}

    def _montar_aba_gabinete(self, p):
        topo = ctk.CTkFrame(p, fg_color="transparent")
        topo.pack(fill="x", padx=16, pady=(0, 10))
        self.bt_ident = self._botao(topo, "◉  Identificar fans (30 s)", self.identificar,
                                    primario=True)
        self.bt_ident.pack(side="left", fill="x", expand=True)

        cg = self._cartao(p, "Seu gabinete, visto pelo vidro")
        self.canvas_gab = CanvasGabinete(cg)
        self.canvas_gab.pack(padx=20, pady=(6, 12))
        self.canvas_gab.montar(None)

        self.c_gab = self._cartao(p, "Onde fica cada um")
        self.lista_gab = ctk.CTkFrame(self.c_gab, fg_color="transparent")
        self.lista_gab.pack(fill="x", padx=12, pady=(6, 2))
        ctk.CTkLabel(self.c_gab, text="Clique em “Identificar”: cada fan acende na cor ao lado do "
                     "nome dela (e o desenho mostra a mesma cor). Escolha a posição de cada uma — "
                     "o desenho e os LEDs mudam na hora. Fans que o hub não reconhece (ex.: a "
                     "RX120 traseira) não aparecem e mantêm a luz padrão delas.",
                     text_color=APAGADO, font=("Segoe UI", 10), wraplength=LARGURA - 40,
                     justify="left").pack(anchor="w", padx=16, pady=(4, 10))

    def _mostrar_gabinete(self, gab):
        for w in self.lista_gab.winfo_children():
            w.destroy()
        if not gab:
            ctk.CTkLabel(self.lista_gab, text="Nenhum hub iCUE LINK conectado.",
                         text_color=SUAVE, font=("Segoe UI", 11)).pack(anchor="w", padx=4)
            return
        opcoes = list(gabinete.NOMES.values())
        nfan = 0
        for i, (tipo, n) in enumerate(gab["subs"]):
            if tipo != gabinete.TIPO_COOLER:
                nfan += 1
            nome = self.NOMES_TIPO.get(tipo, "Aparelho")
            if tipo != gabinete.TIPO_COOLER:
                nome += f" {nfan}"
            cor = gabinete.CORES_ID[i % len(gabinete.CORES_ID)]
            f = ctk.CTkFrame(self.lista_gab, fg_color="transparent")
            f.pack(fill="x", pady=2)
            ctk.CTkFrame(f, width=16, height=16, corner_radius=8, fg_color=cor).pack(
                side="left", padx=(4, 8))
            ctk.CTkLabel(f, text=f"{nome}", text_color=TEXTO, font=("Segoe UI", 12)).pack(
                side="left")
            ctk.CTkLabel(f, text=f"  {gabinete.NOMES_CORES_ID[i % 8]} · {n} LEDs",
                         text_color=SUAVE, font=("Segoe UI", 10)).pack(side="left")
            var = ctk.StringVar(value=gabinete.NOMES[gab["mapa"][i]])
            ctk.CTkOptionMenu(f, values=opcoes, variable=var, width=150, height=26,
                              fg_color="#2a272d", button_color="#36323a",
                              button_hover_color="#443d42", text_color=TEXTO,
                              font=("Segoe UI", 11), dropdown_font=("Segoe UI", 11),
                              command=lambda v, i=i: self._mudar_posicao(i, v)).pack(
                side="right", padx=4)

    def _mudar_posicao(self, indice, nome):
        papel = next(k for k, v in gabinete.NOMES.items() if v == nome)
        self.cfg.setdefault("mapa_hub", {})[str(indice)] = papel
        self._salvar()
        self.trab.definir_mapa_hub(self.cfg["mapa_hub"])

    def identificar(self):
        if getattr(self, "_identificando", False):
            self.trab.parar_identificar()
            return
        self._identificando = True
        self.bt_ident.configure(text="■  Parar identificação")
        self.canvas_gab.identificacao()
        self.trab.identificar(30)

    def _fim_identificar_ui(self):
        self._identificando = False
        self.bt_ident.configure(text="◉  Identificar fans (30 s)")
        if self.cfg["modo"] == "fixo":
            self.canvas_gab.tudo(self._hex_com_brilho(self.cfg["cor"]))

    def _alternar(self, chave, ligado):
        deslig = set(self.cfg["desligados"])
        (deslig.discard if ligado else deslig.add)(chave)
        self.cfg["desligados"] = sorted(deslig)
        self._salvar()
        self.trab.desligar_dispositivos(deslig)

    def _mostrar_outros(self, lista):
        for w in self.lista_outros.winfo_children():
            w.destroy()
        if not lista:
            ctk.CTkLabel(self.lista_outros, text="Nenhum equipamento RGB USB encontrado.",
                         text_color=SUAVE, font=("Segoe UI", 11)).pack(anchor="w", padx=4)
        conhecidos = set(self.cfg.get("usb_conhecidos", []))
        primeira = "usb_conhecidos" not in self.cfg
        for d in lista:
            novo = not primeira and d["chave"] not in conhecidos
            self._linha(self.lista_outros, d["nome"], f"{d['fabricante']} · {d['texto']}",
                        cor_sub=COR_SITUACAO[d["situacao"]], selo="NOVO" if novo else None)
        self.lbl_busca.configure(
            text=f"Última busca: {time.strftime('%H:%M')}  ·  RAM e placa de vídeo vêm "
                 f"direto do iCUE/MSI e aparecem em “Sincronizando”.")

    # ================================================================ busca / recarregar
    def _buscar_outros(self, avisar_novos=False):
        """Roda em thread: procura equipamentos RGB USB e mostra/avisa os novos."""
        try:
            lista = busca.procurar()
        except Exception:
            log.exception("busca de dispositivos")
            lista = []
        conhecidos = set(self.cfg.get("usb_conhecidos", []))
        primeira = "usb_conhecidos" not in self.cfg
        novos = [d for d in lista if d["chave"] not in conhecidos]
        log.info("busca: %d equipamentos, novos: %s", len(lista), [d["nome"] for d in novos])
        self.root.after(0, self._mostrar_outros, lista)
        if avisar_novos and novos and not primeira:
            nomes = ", ".join(d["nome"] for d in novos[:3])
            try:
                self.icon.notify(f"Novo equipamento RGB encontrado: {nomes}. "
                                 "Veja em Dispositivos.", "RGB Sync")
            except Exception:
                pass

        def guardar():
            self.cfg["usb_conhecidos"] = sorted(conhecidos | {d["chave"] for d in lista})
            self._salvar()
        # guarda depois de mostrar (pra o selo NOVO aparecer nesta busca)
        self.root.after(200, guardar)
        self.root.after(0, lambda: self.bt_busca.configure(state="normal",
                                                           text="Procurar dispositivos"))

    def procurar(self):
        self.bt_busca.configure(state="disabled", text="Procurando…")
        self.trab.recarregar()                     # acha aparelhos novos nos SDKs também
        threading.Thread(target=self._buscar_outros, daemon=True).start()

    def recarregar(self):
        self.bt_resync.configure(state="disabled", text="Sincronizando…")
        self.lbl_estado.configure(text="●  Reconectando…", text_color=ALERTA)
        self.trab.recarregar()

    # ================================================================ barra de título
    def _barra_titulo_escura(self):
        """Windows 11: barra de título escura e da mesma cor do fundo. Reaplicada a
        cada vez que a janela aparece (o customtkinter mexe na moldura)."""
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
            u.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            u.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
            if r1 != 0:
                log.warning("barra de título escura falhou: hwnd=%s resultado=%s", hwnd, r1)
        except Exception:
            log.exception("barra de título")

    # ================================================================ bandeja
    def _cor_atual(self):
        return self.cor_geral if self.cfg["modo"] == "papel_parede" else self.cfg["cor"]

    def _img_bandeja(self):
        return icone(64, hex_rgb(self._cor_atual()))

    def _menu(self):
        def ui(func, *args):
            return lambda icon, item: self.root.after(0, func, *args)

        cores = pystray.Menu(*[pystray.MenuItem(n, ui(self.definir, c)) for n, c in PRESETS])
        return pystray.Menu(
            pystray.MenuItem("Abrir RGB Sync", ui(self.mostrar), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Papel de parede", ui(self._mudar_modo, "Papel de parede"),
                             checked=lambda i: self.cfg["modo"] == "papel_parede", radio=True),
            pystray.MenuItem("Efeito", ui(self._mudar_modo, "Efeito"),
                             checked=lambda i: self.cfg["modo"] == "efeito", radio=True),
            pystray.MenuItem("Cor fixa", ui(self._mudar_modo, "Cor fixa"),
                             checked=lambda i: self.cfg["modo"] == "fixo", radio=True),
            pystray.MenuItem("Perfis", pystray.Menu(lambda: tuple(
                pystray.MenuItem(n, ui(self.aplicar_perfil, n, "atalho"),
                                 checked=lambda i, n=n: self.cfg["perfil"] == n, radio=True)
                for n in self._ordem_perfis()))),
            pystray.MenuItem("Cores", cores),
            pystray.MenuItem("Apagar tudo", ui(self.definir, "#000000")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sincronizar tudo de novo", ui(self.recarregar)),
            pystray.MenuItem("Sair", ui(self.sair)),
        )

    # ================================================================ iluminação
    def _mudar_modo(self, nome):
        self.cfg["modo"] = MODOS[nome]
        self.seg_modo.set(nome)
        self._atualizar_modo()
        self.enviar()
        self.icon.update_menu()

    def _atualizar_modo(self):
        modo = self.cfg["modo"]
        for c in (self.c_papel, self.c_fixo, self.c_efeito):
            c.pack_forget()
        alvo = {"papel_parede": self.c_papel, "fixo": self.c_fixo}.get(modo, self.c_efeito)
        alvo.pack(fill="x", padx=16, pady=(0, 10), after=self.card_previa)
        if modo == "papel_parede":
            self.lbl_fonte.configure(text="Lendo o papel de parede…")
            self.previa.zonas_msi(self._hex_com_brilho(self.cor_geral))
        elif modo == "fixo":
            self.previa.tudo(self._hex_com_brilho(self.cfg["cor"]))
            if hasattr(self, "canvas_gab") and not getattr(self, "_identificando", False):
                self.canvas_gab.tudo(self._hex_com_brilho(self.cfg["cor"]))
        else:
            self._atualizar_efeito_ui()
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

    def comando(self, texto):
        """Controle externo (Stream Deck, scripts): python rgbsync_cmd.py perfil Noite
        Aceita: "perfil <nome>", "modo papel|fixo|efeito", "efeito <tipo>",
        "cor #rrggbb", "brilho <0-100>"."""
        verbo, _, arg = texto.strip().partition(" ")
        log.info("comando externo: %s", texto)
        if verbo == "perfil":
            self.aplicar_perfil(arg, "atalho")
        elif verbo == "modo":
            nome = {"papel": "Papel de parede", "fixo": "Cor fixa", "efeito": "Efeito"}.get(arg)
            if nome:
                self._mudar_modo(nome)
        elif verbo == "efeito" and arg in efeitos.TIPOS.values():
            self.cfg["modo"] = "efeito"
            self.seg_modo.set("Efeito")
            self.seg_efeito.set(_nome(efeitos.TIPOS, arg))
            self.cfg["efeito"] = arg
            self._atualizar_modo()
            self.enviar()
        elif verbo == "cor" and len(arg.lstrip("#")) == 6:
            self.definir("#" + arg.lstrip("#").lower())
        elif verbo == "identificar":
            self.identificar()
        elif verbo == "brilho" and arg.isdigit():
            self.sl_brilho.set(min(100, int(arg)))
            self._mudar_brilho(min(100, int(arg)))

    # ---- efeito
    INFO_EFEITO = {
        "respiracao": "A cor acende e apaga devagar em todos os aparelhos.",
        "onda": "Um arco-íris corre da esquerda para a direita nas fans, RAM e teclado.",
        "ciclo": "Todos os aparelhos passam juntos por todas as cores.",
        "temperatura": "Azul = frio · verde · amarelo · vermelho = quente "
                       "(GPU: 35 °C a 85 °C; CPU: 0% a 100% de uso).",
    }

    def _atualizar_efeito_ui(self):
        tipo = self.cfg["efeito"]
        self.l_ef_cor.pack_forget()
        self.l_ef_fonte.pack_forget()
        if tipo == "respiracao":
            self.l_ef_cor.pack(fill="x", padx=16, pady=(2, 6), before=self.lbl_ef_info)
        elif tipo == "temperatura":
            self.l_ef_fonte.pack(fill="x", padx=16, pady=(2, 6), before=self.lbl_ef_info)
        info = self.INFO_EFEITO[tipo]
        if tipo != "temperatura":
            info += "  Placa-mãe e GPU usam o efeito próprio da MSI."
        self.lbl_ef_info.configure(text=info)
        self.amostra_ef.configure(fg_color=self.cfg["cor"])
        self.seg_vel.configure(state="disabled" if tipo == "temperatura" else "normal")

    def _mudar_efeito(self, nome):
        self.cfg["efeito"] = efeitos.TIPOS[nome]
        self._atualizar_efeito_ui()
        self.enviar()

    def _mudar_vel(self, nome):
        self.cfg["velocidade"] = efeitos.VELOCIDADES[nome]
        self.enviar()

    def _mudar_fonte(self, nome):
        self.cfg["fonte_temp"] = efeitos.FONTES[nome]
        self.lbl_sensor.configure(text="")
        self.enviar()

    def cor_efeito(self, hexa):
        self.cfg["cor"] = hexa
        self.amostra_ef.configure(fg_color=hexa)
        self.amostra.configure(fg_color=hexa)
        self.ent_hex.delete(0, "end")
        self.ent_hex.insert(0, hexa.upper())
        self.enviar()

    def escolher_cor_efeito(self):
        _, hexa = colorchooser.askcolor(color=self.cfg["cor"], title="Cor da respiração")
        if hexa:
            self.cor_efeito(hexa)

    def enviar(self):
        self._salvar()
        if not self.pronto:
            return
        if self.cfg["modo"] == "efeito":
            self.trab.ativar_efeito({"tipo": self.cfg["efeito"], "cor": hex_rgb(self.cfg["cor"]),
                                     "velocidade": self.cfg["velocidade"],
                                     "brilho": self.cfg["brilho"],
                                     "fonte": self.cfg["fonte_temp"]})
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
        self._sync_luzes()

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
            self._titulo_agendado = True

            def aplicar():
                self._titulo_agendado = False
                self._barra_titulo_escura()
            self.root.after(150, aplicar)
        if hasattr(self, "trab"):
            self.trab.ligar_preview(sim and self.root.state() != "withdrawn")
        if hasattr(self, "seg_aba"):
            self._vigiar_luzes()

    def mostrar(self, aba=None):
        if aba in ABAS:
            self._mudar_aba(aba)
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
        try:
            self.atalhos.parar()
            self.vigia.parar()
        except Exception:
            pass
        try:
            for id_, luz in getattr(self, "luzes", {}).items():
                conf = self.cfg["luzes"].get(id_, {})
                if conf.get("sync") and conf.get("foto"):
                    luz.restaurar(conf["foto"])
            fim = time.monotonic() + 2
            while time.monotonic() < fim and any(l._pendente for l in self.luzes.values()):
                time.sleep(0.1)
            for luz in self.luzes.values():
                luz.parar()
        except Exception:
            log.exception("luzes ao sair")
        self.trab.fila.put(("sair", None))
        self.trab.join(timeout=5)
        self.icon.stop()
        self.root.destroy()

    # ================================================================ mensagens do motor
    def ao_status(self, tipo, dados):
        if tipo == "conexao":
            self.conexao = dados
            self.pronto = True
            if all(s == "ok" for s in dados.values()):
                self.lbl_estado.configure(text="●  Conectado", text_color=OK)
            else:
                ruins = [m.split(" (")[0] for m, s in dados.items() if s != "ok"]
                self.lbl_estado.configure(text=f"●  Aguardando {', '.join(ruins)}",
                                          text_color=ALERTA)
            self.enviar()
        elif tipo == "dispositivos":
            self._mostrar_dispositivos(dados)
        elif tipo == "recarregado":
            self.bt_resync.configure(state="normal", text="⟳  Sincronizar tudo de novo")
        elif tipo == "identificar_fim":
            self._fim_identificar_ui()
        elif tipo == "layouts":
            self._mostrar_gabinete(dados.get("gabinete"))
            self.canvas_gab.montar(dados.get("gabinete"))
            if getattr(self, "_identificando", False):
                self.canvas_gab.identificacao()
            self.previa.montar(dados)
            self._atualizar_modo()
            self._visivel(self.root.state() != "withdrawn")
        elif tipo == "preview":
            if self.cfg["modo"] in ("papel_parede", "efeito"):
                self.previa.leds(dados)
                if not getattr(self, "_identificando", False):
                    self.canvas_gab.leds(dados)
        elif tipo == "efeito_msi":
            if self.cfg["modo"] == "efeito" and self.cfg["efeito"] == "temperatura":
                self._cor_temp = dados
                self._sync_luzes()
            if self.cfg["modo"] == "efeito":
                self.previa.zonas_msi(dados if dados.startswith("#") else "#6b5cff")
        elif tipo == "sensor":
            self.lbl_sensor.configure(text=f"agora: {dados}")
        elif tipo == "papel_cor":
            geral, fonte = dados
            self.cor_geral = rgb_hex(geral)
            self.cfg["cor_papel"] = self.cor_geral
            self._salvar()
            if self.cfg["modo"] == "papel_parede":
                self._sync_luzes()
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
    log.info("=== app iniciado v%s %s | dados=%s", VERSAO, sys.argv[1:], DADOS)
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    App(root, iniciar_escondido="--bandeja" in sys.argv)
    root.mainloop()


if __name__ == "__main__":
    main()
