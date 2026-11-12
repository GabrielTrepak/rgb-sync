"""
Diagnóstico RGB — SOMENTE LEITURA.

Este script NÃO muda cores, NÃO pede controle exclusivo de nenhum dispositivo,
NÃO grava firmware e NÃO acessa SMBus/RAM diretamente. Ele só pergunta:

  1. Quais programas de RGB estão rodando (para achar conflitos).
  2. Quais dispositivos USB de RGB o Windows enxerga.
  3. O que o iCUE expõe pelo SDK oficial da Corsair (lista de dispositivos).
  4. (Só se rodar como administrador) o que o Mystic Light da MSI expõe pelo SDK oficial.
  5. Se o servidor do OpenRGB está ativo.

Uso:  .venv\\Scripts\\python.exe diagnostico_rgb.py
"""

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
from datetime import datetime

RELATORIO = []


def out(linha=""):
    print(linha)
    RELATORIO.append(linha)


def titulo(t):
    out()
    out("=" * 70)
    out(t)
    out("=" * 70)


def powershell_json(cmd):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd + " | ConvertTo-Json -Depth 3"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if not r.stdout.strip():
        return []
    data = json.loads(r.stdout)
    return data if isinstance(data, list) else [data]


# ---------------------------------------------------------------- 1. processos
SOFTWARES_RGB = {
    "iCUE": "Corsair iCUE",
    "Mystic_Light_Service": "MSI Mystic Light (MSI Center)",
    "MSI.CentralServer": "MSI Center",
    "NGenuity2Helper": "HyperX NGENUITY",
    "OpenRGB": "OpenRGB",
    "SignalRgb": "SignalRGB",
    "SignalRgbLauncher": "SignalRGB",
    "LightingService": "ASUS Armoury Crate",
}


def secao_processos():
    titulo("1. PROGRAMAS DE RGB RODANDO")
    procs = powershell_json("Get-Process | Select-Object ProcessName")
    nomes = {p["ProcessName"] for p in procs}
    ativos = sorted({v for k, v in SOFTWARES_RGB.items() if k in nomes})
    for a in ativos:
        out(f"  [rodando] {a}")
    if len(ativos) > 1:
        out()
        out(f"  ⚠ {len(ativos)} programas de RGB ativos ao mesmo tempo.")
        out("    Eles podem disputar os mesmos LEDs (causa comum de 'para de funcionar').")
    return ativos


# ---------------------------------------------------------------- 2. USB
USB_CONHECIDOS = {
    ("1B1C", "0C3F"): "Corsair iCUE LINK System Hub",
    ("1B1C", "0C4E"): "Corsair iCUE LINK (tela LCD do H150i)",
    ("1B1C", "0A6B"): "Corsair HS80 (receptor wireless)",
    ("03F0", "098F"): "HyperX Alloy Origins Core",
    ("1462", "7D75"): "MSI Mystic Light — placa-mãe MS-7D75 (B650 Tomahawk)",
    ("0DB0", "422D"): "Áudio Realtek da placa-mãe (não é RGB)",
}


def secao_usb():
    titulo("2. DISPOSITIVOS USB DE RGB QUE O WINDOWS ENXERGA")
    devs = powershell_json(
        "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match "
        "'^USB\\\\VID_(1B1C|0951|03F0|1462|0DB0)&PID_[0-9A-F]{4}\\\\' } "
        "| Select-Object Status, FriendlyName, InstanceId"
    )
    vistos = set()
    for d in devs:
        iid = d["InstanceId"].upper()
        vid = iid.split("VID_")[1][:4]
        pid = iid.split("PID_")[1][:4]
        if (vid, pid) in vistos:
            continue
        vistos.add((vid, pid))
        nome = USB_CONHECIDOS.get((vid, pid), d.get("FriendlyName") or "desconhecido")
        out(f"  [{d['Status']}] {vid}:{pid}  {nome}")
    out()
    out("  Obs.: RAM e GPU não aparecem aqui — elas usam o barramento SMBus/I2C,")
    out("  não USB. Por isso este script não as sonda diretamente.")


# ---------------------------------------------------------------- 3. iCUE SDK
def _desconectar(sdk):
    # Bug do cuesdk 4.0.84: disconnect() apaga a referência do callback ANTES de
    # chamar CorsairDisconnect, que ainda dispara o callback -> crash (access violation).
    # Guardamos a referência até a desconexão terminar.
    handler = getattr(sdk, "session_state_changed_event_handler", None)
    sdk.disconnect()
    del handler


def secao_icue():
    titulo("3. iCUE SDK (oficial Corsair) — o que o iCUE deixa controlar")
    try:
        from cuesdk import CueSdk, CorsairDeviceFilter, CorsairDeviceType, CorsairSessionState
    except ImportError:
        out("  cuesdk não instalado. Rode: .venv\\Scripts\\pip install cuesdk")
        return None

    sdk = CueSdk()
    conectado = threading.Event()
    ultimo_estado = {"s": None}

    def on_state(evt):
        ultimo_estado["s"] = evt.state
        if evt.state == CorsairSessionState.CSS_Connected:
            conectado.set()

    sdk.connect(on_state)
    if not conectado.wait(timeout=10):
        out(f"  ✗ Não conectou ao iCUE (estado: {ultimo_estado['s']}).")
        out("    Verifique em iCUE → Configurações → Geral se a opção do SDK")
        out("    ('Enable SDK' / 'Ativar SDK' / integrações) está ligada.")
        _desconectar(sdk)
        return None

    det, _ = sdk.get_session_details()
    if det:
        v = det.server_host_version
        out(f"  ✓ Conectado. Versão do iCUE informada pelo SDK: {v.major}.{v.minor}.{v.patch}")
    devices, err = sdk.get_devices(CorsairDeviceFilter(device_type_mask=CorsairDeviceType.CDT_All))
    resultado = []
    if not devices:
        out(f"  Nenhum dispositivo exposto (erro: {err}).")
    else:
        out()
        out(f"  {'TIPO':<22} {'MODELO':<38} {'LEDs':>5} {'CANAIS':>6}")
        out(f"  {'-'*22} {'-'*38} {'-'*5} {'-'*6}")
        for d in devices:
            tipo = str(d.type).split(".")[-1].replace("CDT_", "")
            out(f"  {tipo:<22} {d.model[:38]:<38} {d.led_count:>5} {d.channel_count:>6}")
            resultado.append({"tipo": tipo, "modelo": d.model, "leds": d.led_count,
                              "canais": d.channel_count})
    _desconectar(sdk)
    return resultado


# ---------------------------------------------------------------- 4. Mystic Light SDK
MLAPI_DLLS = [
    r"C:\Program Files\Corsair\Corsair iCUE5 Software\plugins\MSI\MysticLight_SDK_x64.dll",
]
MLAPI_ERROS = {0: "OK", -1: "ERRO", -2: "TIMEOUT", -3: "NÃO IMPLEMENTADO",
               -4: "NÃO INICIALIZADO", -101: "ARGUMENTO INVÁLIDO",
               -102: "DISPOSITIVO NÃO ENCONTRADO", -103: "NÃO SUPORTADO"}


def _safearray_bstrs(psa):
    oa = ctypes.windll.oleaut32
    lb, ub = ctypes.c_long(), ctypes.c_long()
    oa.SafeArrayGetLBound(psa, 1, ctypes.byref(lb))
    oa.SafeArrayGetUBound(psa, 1, ctypes.byref(ub))
    vals = []
    for i in range(lb.value, ub.value + 1):
        idx = ctypes.c_long(i)
        bstr = ctypes.c_void_p()
        oa.SafeArrayGetElement(psa, ctypes.byref(idx), ctypes.byref(bstr))
        vals.append(ctypes.wstring_at(bstr.value) if bstr.value else "")
        oa.SysFreeString(bstr)
    oa.SafeArrayDestroy(psa)
    return vals


def secao_mystic():
    titulo("4. MSI Mystic Light SDK (oficial MSI) — placa-mãe e GPU")
    if not ctypes.windll.shell32.IsUserAnAdmin():
        out("  (pulado) O SDK da MSI exige administrador.")
        out("  Para incluir esta parte, rode o terminal como administrador.")
        return None
    dll_path = next((p for p in MLAPI_DLLS if os.path.exists(p)), None)
    if not dll_path:
        out("  MysticLight_SDK_x64.dll não encontrada.")
        return None
    os.add_dll_directory(os.path.dirname(dll_path))
    dll = ctypes.WinDLL(dll_path)
    r = dll.MLAPI_Initialize()
    if r != 0:
        out(f"  ✗ MLAPI_Initialize falhou: {MLAPI_ERROS.get(r, r)}")
        return None
    tipos, leds = ctypes.c_void_p(), ctypes.c_void_p()
    r = dll.MLAPI_GetDeviceInfo(ctypes.byref(tipos), ctypes.byref(leds))
    resultado = []
    if r != 0:
        out(f"  ✗ MLAPI_GetDeviceInfo falhou: {MLAPI_ERROS.get(r, r)}")
    else:
        for t, n in zip(_safearray_bstrs(tipos), _safearray_bstrs(leds)):
            out(f"  ✓ {t:<20} zonas/LEDs: {n}")
            resultado.append({"tipo": t, "leds": n})
    if hasattr(dll, "MLAPI_Release"):
        dll.MLAPI_Release()
    return resultado


# ---------------------------------------------------------------- 5. OpenRGB
def secao_openrgb():
    titulo("5. OpenRGB")
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", 6742))
        out("  ✓ Servidor SDK do OpenRGB ativo na porta 6742.")
        return True
    except OSError:
        out("  ✗ OpenRGB não está rodando (ou não está instalado).")
        return False
    finally:
        s.close()


# ---------------------------------------------------------------- main
def main():
    out(f"Diagnóstico RGB — {datetime.now():%Y-%m-%d %H:%M}  (somente leitura)")
    dados = {
        "programas_ativos": secao_processos(),
        "usb": secao_usb(),
        "icue": secao_icue(),
        "mystic_light": secao_mystic(),
        "openrgb_ativo": secao_openrgb(),
    }
    pasta = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(pasta, "diagnostico_rgb.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(RELATORIO))
    with open(os.path.join(pasta, "diagnostico_rgb.json"), "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2, default=str)
    out()
    out("Relatório salvo em diagnostico_rgb.txt e diagnostico_rgb.json")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
