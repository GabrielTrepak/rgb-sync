"""
Perfis do RGB Sync: configurações salvas (modo, cor, brilho, monitor, aparelhos
ligados), trocadas pela janela, pela bandeja, por atalho global (Ctrl+Alt+1..9) ou
sozinhas quando um jogo/programa associado abre.

- Atalhos: RegisterHotKey do Windows numa thread própria (funcionam com qualquer
  janela em foco, inclusive jogos).
- Vigia: a cada 3 s olha os processos abertos (CreateToolhelp32Snapshot, sem abrir
  nenhum programa) e avisa quando um programa associado abre/fecha.
"""

import ctypes
import os
import threading
from ctypes import wintypes as W

from rgb_core import log

CAMPOS = ("modo", "cor", "brilho", "monitor", "desligados", "efeito", "velocidade",
          "fonte_temp")

PADROES = {
    "Jogo": {"modo": "papel_parede", "cor": "#0050ff", "brilho": 100, "monitor": "principal",
             "desligados": [], "programas": []},
    "Noite": {"modo": "fixo", "cor": "#ff5a00", "brilho": 20, "monitor": "principal",
              "desligados": [], "programas": []},
    "Trabalho": {"modo": "fixo", "cor": "#ffd6aa", "brilho": 60, "monitor": "principal",
                 "desligados": [], "programas": []},
}


def garantir_perfis(cfg):
    """Cria os perfis na primeira vez. O perfil "Jogo" herda a configuração atual
    (assim nada muda pra quem já usava o app)."""
    if cfg.get("perfis"):
        cfg.setdefault("perfil", next(iter(cfg["perfis"])))
        return
    perfis = {n: dict(v, desligados=list(v["desligados"]), programas=[])
              for n, v in PADROES.items()}
    perfis["Jogo"].update({c: cfg[c] for c in CAMPOS if c in cfg})
    cfg["perfis"] = perfis
    cfg["perfil"] = "Jogo"


def guardar_no_perfil(cfg):
    """Copia a configuração atual pro perfil ativo (salvamento automático)."""
    p = cfg["perfis"].get(cfg.get("perfil"))
    if p is not None:
        for c in CAMPOS:
            v = cfg.get(c)
            p[c] = list(v) if isinstance(v, (list, set, tuple)) else v


def carregar_perfil(cfg, nome):
    """Traz os valores do perfil pra configuração atual."""
    p = cfg["perfis"][nome]
    for c in CAMPOS:
        if c in p:
            cfg[c] = list(p[c]) if c == "desligados" else p[c]
    cfg["perfil"] = nome


# ============================================================= atalhos globais
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
_u32 = ctypes.windll.user32
_u32.RegisterHotKey.argtypes = [W.HWND, ctypes.c_int, W.UINT, W.UINT]
_u32.UnregisterHotKey.argtypes = [W.HWND, ctypes.c_int]
_u32.PostThreadMessageW.argtypes = [W.DWORD, W.UINT, W.WPARAM, W.LPARAM]


def texto_atalho(i):
    return f"Ctrl+Alt+{i + 1}"


class Atalhos:
    """Ctrl+Alt+1..N → ao_apertar(índice). Reinicie com definir(n) quando mudar a
    quantidade de perfis."""

    def __init__(self, ao_apertar):
        self.ao_apertar = ao_apertar
        self._tid = None
        self._thread = None
        self.falharam = []

    def definir(self, quantidade):
        self.parar()
        quantidade = min(quantidade, 9)
        pronto = threading.Event()

        def laco():
            self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
            self.falharam = []
            for i in range(quantidade):
                if not _u32.RegisterHotKey(None, i + 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
                                           0x31 + i):
                    self.falharam.append(texto_atalho(i))
            if self.falharam:
                log.warning("atalhos já usados por outro programa: %s", self.falharam)
            pronto.set()
            msg = W.MSG()
            while _u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self.ao_apertar(msg.wParam - 1)
                    except Exception:
                        log.exception("atalho")
            for i in range(quantidade):
                _u32.UnregisterHotKey(None, i + 1)

        self._thread = threading.Thread(target=laco, daemon=True)
        self._thread.start()
        pronto.wait(2)

    def parar(self):
        if self._thread and self._tid:
            _u32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(timeout=2)
        self._thread = self._tid = None


# ============================================================= vigia de programas
class _PE32(ctypes.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", W.DWORD),
                ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", W.DWORD),
                ("szExeFile", W.WCHAR * 260)]


_k32 = ctypes.windll.kernel32
_k32.CreateToolhelp32Snapshot.restype = W.HANDLE
_k32.Process32FirstW.argtypes = [W.HANDLE, ctypes.POINTER(_PE32)]
_k32.Process32NextW.argtypes = [W.HANDLE, ctypes.POINTER(_PE32)]
_k32.CloseHandle.argtypes = [W.HANDLE]


def processos_abertos():
    """Nomes (minúsculos) dos executáveis rodando agora."""
    snap = _k32.CreateToolhelp32Snapshot(0x00000002, 0)
    nomes = set()
    if not snap or snap == W.HANDLE(-1).value:
        return nomes
    pe = _PE32()
    pe.dwSize = ctypes.sizeof(_PE32)
    ok = _k32.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        nomes.add(pe.szExeFile.lower())
        ok = _k32.Process32NextW(snap, ctypes.byref(pe))
    _k32.CloseHandle(snap)
    return nomes


class Vigia(threading.Thread):
    """A cada 3 s: qual perfil deveria estar ativo por causa de um programa aberto?
    Chama ao_mudar(nome_do_perfil ou None) só quando isso muda."""

    INTERVALO = 3.0

    def __init__(self, obter_perfis, ao_mudar):
        super().__init__(daemon=True)
        self.obter_perfis = obter_perfis      # () -> {nome: {"programas": [...]}}
        self.ao_mudar = ao_mudar
        self._atual = None
        self._parar = threading.Event()

    def run(self):
        while not self._parar.wait(self.INTERVALO):
            try:
                perfis = self.obter_perfis()
                if not any(p.get("programas") for p in perfis.values()):
                    alvo = None
                else:
                    abertos = processos_abertos()
                    alvo = next((nome for nome, p in perfis.items()
                                 if any(os.path.basename(x).lower() in abertos
                                        for x in p.get("programas", []))), None)
                if alvo != self._atual:
                    self._atual = alvo
                    self.ao_mudar(alvo)
            except Exception:
                log.exception("vigia de programas")

    def parar(self):
        self._parar.set()
