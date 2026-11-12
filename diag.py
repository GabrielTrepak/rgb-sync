"""Pergunta ao RGB Sync que está rodando como ele está (log, config, atalho...).

Uso:  python diag.py
"""
import json
import socket
import sys

try:
    with socket.create_connection(("127.0.0.1", 47652), timeout=3) as s:
        s.sendall(b"diag")
        dados = b""
        while True:
            parte = s.recv(65536)
            if not parte:
                break
            dados += parte
except OSError:
    sys.exit("RGB Sync não está rodando.")

info = json.loads(dados.decode("utf-8"))
log = info.pop("log", [])
sys.stdout.reconfigure(encoding="utf-8")
for k, v in info.items():
    print(f"{k}: {v}")
print("--- log")
print("\n".join(log))
