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
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import colorchooser

import customtkinter as ctk
import pystray
from PIL import Image

import busca
import motor
from icone import icone
from motor import hex_rgb, ler_config, rgb_hex, salvar_config
from rgb_core import PASTA, log

VERSAO = "3.1"
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

MODOS = {"Papel de parede": "papel_parede", "Cor fixa": "fixo"}
MONITORES = {"Principal": "principal", "Secundário": "secundario", "Os dois": "ambos"}
ABAS = ("Iluminação", "Dispositivos")
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
                self.itens.setdefault(chave, item)
        return item

    def montar(self, layouts):
        self.delete("all")
        self.itens, self.msi, self.todos = {}, [], []
        w = int(self["width"])
        y = 4
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
        self.cfg.setdefault("desligados", [])
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
                                  lambda: root.after(0, self.sair))
        root.protocol("WM_DELETE_WINDOW", self.esconder)
        root.bind("<Map>", lambda e: self._visivel(True))
        root.bind("<Unmap>", lambda e: self._visivel(False))

        self.trab = motor.Trabalhador(lambda t, d: root.after(0, self.ao_status, t, d),
                                      desligados=self.cfg["desligados"])
        self.trab.start()
        self._atualizar_modo()
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
        self.pag_disp = ctk.CTkFrame(r, fg_color="transparent")
        self._montar_luz(self.pag_luz)
        self._montar_disp(self.pag_disp)
        self.pag_luz.pack(fill="x")

        self.rodape = ctk.CTkLabel(
            r, text=f"Fechar a janela mantém o RGB Sync na bandeja  ·  v{VERSAO}",
            text_color="#5c5558", font=("Segoe UI", 10))
        self.rodape.pack(pady=(0, 12))

    def _montar_luz(self, p):
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

    # ================================================================ abas
    def _mudar_aba(self, nome):
        self.pag_luz.pack_forget()
        self.pag_disp.pack_forget()
        (self.pag_luz if nome == ABAS[0] else self.pag_disp).pack(fill="x", before=self.rodape)
        self.seg_aba.set(nome)

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
            if d["marca"] == "MSI":                      # "Placa de vídeo (RTX ...)"
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
        self._linha(self.lista_disp, "Teclado HyperX", "Ainda não suportado — planejado",
                    cor_sub=APAGADO)

    def _alternar(self, chave, ligado):
        deslig = set(self.cfg["desligados"])
        (deslig.discard if ligado else deslig.add)(chave)
        self.cfg["desligados"] = sorted(deslig)
        salvar_config(self.cfg)
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
            salvar_config(self.cfg)
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
            pystray.MenuItem("Cor fixa", ui(self._mudar_modo, "Cor fixa"),
                             checked=lambda i: self.cfg["modo"] == "fixo", radio=True),
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
        papel = self.cfg["modo"] == "papel_parede"
        self.c_papel.pack_forget()
        self.c_fixo.pack_forget()
        (self.c_papel if papel else self.c_fixo).pack(fill="x", padx=16, pady=(0, 10),
                                                       after=self.card_previa)
        if papel:
            self.lbl_fonte.configure(text="Lendo o papel de parede…")
            self.previa.zonas_msi(self._hex_com_brilho(self.cor_geral))
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
            self._titulo_agendado = True

            def aplicar():
                self._titulo_agendado = False
                self._barra_titulo_escura()
            self.root.after(150, aplicar)
        if hasattr(self, "trab"):
            self.trab.ligar_preview(sim and self.root.state() != "withdrawn")

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
    log.info("=== app iniciado v%s %s | dados=%s", VERSAO, sys.argv[1:], DADOS)
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    App(root, iniciar_escondido="--bandeja" in sys.argv)
    root.mainloop()


if __name__ == "__main__":
    main()
