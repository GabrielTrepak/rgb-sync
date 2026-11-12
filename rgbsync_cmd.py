"""Controla o RGB Sync que está rodando (para Stream Deck, atalhos, scripts).

Exemplos:
  python rgbsync_cmd.py perfil Noite
  python rgbsync_cmd.py modo efeito          (papel | fixo | efeito)
  python rgbsync_cmd.py efeito onda          (respiracao | onda | ciclo | temperatura)
  python rgbsync_cmd.py cor ff0000
  python rgbsync_cmd.py brilho 40
"""
import socket
import sys

if len(sys.argv) < 3:
    sys.exit(__doc__)
try:
    with socket.create_connection(("127.0.0.1", 47652), timeout=2) as s:
        s.sendall(("cmd:" + " ".join(sys.argv[1:])).encode("utf-8"))
except OSError:
    sys.exit("RGB Sync não está rodando.")
