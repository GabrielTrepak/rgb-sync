"""
Procura equipamentos RGB conectados por USB — inclusive os que o RGB Sync ainda não
controla — para você saber o que é compatível quando adicionar algo novo no PC.

Só LÊ a lista de dispositivos do Windows; não fala com nenhum aparelho.
Memória RAM e placa de vídeo não aparecem aqui (não são USB); essas vêm dos SDKs.

Teste:  python busca.py
"""

import json
import subprocess

# Fabricantes (Vendor ID USB) que costumam ter RGB.
FABRICANTES = {
    "1B1C": "Corsair", "0951": "HyperX", "03F0": "HyperX / HP", "046D": "Logitech",
    "1532": "Razer", "1038": "SteelSeries", "0B05": "ASUS", "1E71": "NZXT",
    "0CF2": "Lian Li", "2516": "Cooler Master", "048D": "Gigabyte (RGB Fusion)",
    "26CE": "ASRock", "1462": "MSI", "264A": "Thermaltake", "1E7D": "Roccat",
    "31E3": "Wooting", "3633": "Glorious", "0C45": "Redragon / genérico",
    "1A2C": "genérico (teclado RGB)", "320F": "Glorious / genérico",
}

# Como cada fabricante é tratado hoje.
SITUACAO = {
    "Corsair": ("compativel", "Compatível — pelo iCUE"),
    "MSI": ("compativel", "Compatível — pelo Mystic Light (placa-mãe/GPU)"),
    "HyperX": ("compativel", "Compatível — teclado Alloy Origins Core"),
    "HyperX / HP": ("compativel", "Compatível — teclado Alloy Origins Core"),
}

# Coisas desses fabricantes que não têm LED (não poluir a lista).
SEM_RGB = ("audio", "áudio", "microphone", "microfone", "bluetooth", "wireless adapter",
           "usb hub", "usb2.0 hub", "usb3.0 hub", "smbus", "pci", "vga controller", "mass storage", "card reader")

_PS = r"""
$out = Get-PnpDevice -PresentOnly | Where-Object {
    $_.InstanceId -match '^USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}\\' } | ForEach-Object {
  $d = (Get-PnpDeviceProperty -InstanceId $_.InstanceId `
        -KeyName DEVPKEY_Device_BusReportedDeviceDesc -ErrorAction SilentlyContinue).Data
  [pscustomobject]@{ id = $_.InstanceId; nome = $_.FriendlyName; desc = $d; status = $_.Status }
}
@($out) | ConvertTo-Json -Compress
"""


def procurar():
    """Lista de dicts: {chave, nome, fabricante, vid, pid, situacao, texto}."""
    r = subprocess.run(["powershell", "-NoProfile", "-Command", _PS], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=60)
    try:
        itens = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return []
    if isinstance(itens, dict):
        itens = [itens]
    vistos, out = set(), []
    for it in itens:
        iid = it.get("id", "").upper()
        vid, pid = iid[8:12], iid[17:21]
        fab = FABRICANTES.get(vid)
        if not fab or (vid, pid) in vistos:
            continue
        nome = (it.get("desc") or it.get("nome") or "").strip()
        if any(p in nome.lower() for p in SEM_RGB):
            continue
        if not nome or nome.lower().startswith(("usb composite", "dispositivo", "usb input")):
            nome = f"Dispositivo {fab}"
        vistos.add((vid, pid))
        situacao, texto = SITUACAO.get(fab, ("nao", "Ainda não suportado"))
        out.append({"chave": f"{vid}:{pid}", "nome": nome, "fabricante": fab, "vid": vid,
                    "pid": pid, "situacao": situacao, "texto": texto})
    ordem = {"compativel": 0, "planejado": 1, "nao": 2}
    out.sort(key=lambda d: (ordem[d["situacao"]], d["fabricante"], d["nome"]))
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for d in procurar():
        print(f"{d['chave']}  {d['fabricante']:<14} {d['nome']:<40} {d['texto']}")
