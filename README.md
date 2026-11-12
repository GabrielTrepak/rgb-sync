# RGB Sync

Controle de RGB pessoal para Windows: **uma cor para o PC inteiro**, sincronizada entre
Corsair e MSI, usando só as APIs oficiais dos fabricantes.

| Marca | Dispositivos | Como |
|---|---|---|
| Corsair | iCUE LINK Hub (H150i LCD, fans QX), Vengeance RGB DDR5, HS80 | iCUE SDK (`cuesdk`) |
| MSI | Placa-mãe (JRGB/JARGB), placa de vídeo | Mystic Light SDK (DLL do plugin MSI do iCUE) |
| HyperX | Alloy Origins Core | ainda não suportado |

## Modos

- **Cor fixa** — escolha uma cor (ou um preset) e o PC inteiro fica nela.
- **Seguir papel de parede** — a cada 2 s o app olha o papel de parede e usa a cor
  que mais o representa, com transição suave. Funciona com o **Wallpaper Engine**
  (captura a janela onde ele desenha, então janelas abertas por cima não atrapalham;
  funciona com vídeo, cena e playlist) e com o papel de parede normal do Windows.
  Dá pra escolher os dois monitores, só o principal ou só o secundário.

> Se usar Wallpaper Engine, desligue o plugin de LED dele (Configurações → Plugins → LED)
> para ele não disputar o iCUE com o RGB Sync.

## Regras do projeto

- Só mexe em **iluminação**. Ventilação e bomba continuam com o iCUE / MSI Center,
  que precisam ficar instalados.
- **Nunca** atualiza nem grava firmware. Nada de acesso direto a SMBus/RAM.
- A MSI guarda a cor no dispositivo: na primeira execução o estado original é salvo
  em `msi_backup.json` (botão "Restaurar MSI original" na janela).
- Enquanto o app roda, ele tem controle exclusivo da iluminação Corsair. Ao sair,
  o iCUE volta para os efeitos dele.

## Instalação

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

No iCUE, o SDK precisa estar ativado (Configurações → Geral).

## Uso

- **Abrir RGB.bat** — abre a janela (ou mostra a que já está na bandeja).
- **iniciar_com_windows.ps1** — cria a tarefa agendada "RGB Sync" que inicia no login,
  elevada (o SDK da MSI exige admin) e escondida na bandeja. `-Remover` desfaz.
- **diagnostico_rgb.py** — diagnóstico somente leitura do que cada SDK enxerga.
- `python rgb_core.py --cor 0080ff --segundos 10` — teste rápido por linha de comando (como admin).

Fechar a janela só esconde o app; para sair: botão direito no ícone da bandeja → Sair.

## Arquivos

- `rgb_core.py` — backends Corsair e MSI + controlador
- `app.py` — janela (tkinter) + bandeja (pystray), instância única, reconexão no boot
- `papel_parede.py` — captura do papel de parede e escolha da cor (`python papel_parede.py` testa)
- `rgb.log` — log local
