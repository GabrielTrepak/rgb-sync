# RGB Sync

Controle de RGB pessoal para Windows: o PC inteiro seguindo o **papel de parede** (ao vivo,
LED a LED) ou uma **cor fixa**, sincronizando Corsair e MSI pelas APIs oficiais dos fabricantes.

| Marca | Dispositivos | Como |
|---|---|---|
| Corsair | iCUE LINK Hub (H150i LCD, fans QX), Vengeance RGB DDR5, HS80 | iCUE SDK (`cuesdk`) |
| MSI | Placa-mãe (JRGB/JARGB), placa de vídeo | Mystic Light SDK (DLL do plugin MSI do iCUE) |
| HyperX | Alloy Origins Core (ANSI e ABNT2), tecla por tecla | protocolo da comunidade (OpenRGB), reescrito em `hyperx.py` — só comandos de luz |

## Modos

- **Papel de parede** — ao vivo (até 12 quadros/s, ~0,1% de CPU com papel de parede em vídeo).
  Na Corsair, **cada LED recebe a cor da região do papel de parede que corresponde à posição
  física dele** (cada pente de RAM vira uma faixa vertical em degradê; as fans do hub LINK pegam
  pedaços da esquerda para a direita). A MSI, que só aceita uma cor por zona, recebe a cor geral
  a cada 2 s. Com a imagem parada (papel estático, Wallpaper Engine pausado num jogo) ele só
  confere 4×/s e não reenvia nada. Funciona com o **Wallpaper Engine** — vídeo (captura a
  janela onde ele desenha, ~2 ms) e cena/web em DirectX (captura a camada da área de trabalho,
  ~20 ms, por isso roda a 6 quadros/s) — sem pegar as janelas abertas por cima, e com o papel
  de parede normal do Windows. Monitor: principal, secundário ou os dois.
- **Cor fixa** — 9 cores prontas, seletor de cor ou código hex.

> **Teclado HyperX:** feche o NGENUITY (e tire ele da inicialização do Windows) — ele fica
> reenviando a cor dele e o teclado pisca entre as duas. O app avisa se ele estiver aberto.

> Se usar Wallpaper Engine, desligue o plugin de LED dele (Configurações → Plugins → LED)
> para ele não disputar o iCUE com o RGB Sync.

## Aba Dispositivos

- **Liga/desliga por aparelho**: o que estiver desligado sai da sincronização (na Corsair, o
  controle volta pro iCUE e ele mostra os efeitos dele; a MSI fica com a última cor).
- **Sincronizar tudo de novo**: desconecta e reconecta iCUE e Mystic Light e reenvia as cores
  (também no menu da bandeja).
- **Procurar dispositivos**: reconecta os SDKs e lista os equipamentos RGB USB conectados de
  várias marcas, dizendo se são compatíveis. Aparelho novo ganha o selo **NOVO**; 20 s depois
  de iniciar o app faz essa busca sozinho e avisa na bandeja se aparecer algo novo.

## Regras do projeto

- Só mexe em **iluminação**. Ventilação e bomba continuam com o iCUE / MSI Center,
  que precisam ficar instalados.
- **Nunca** atualiza nem grava firmware. Nada de acesso direto a SMBus/RAM.
- A MSI guarda a cor no dispositivo: na primeira execução o estado original é salvo
  (`msi_backup.json`) e o botão "Restaurar MSI original" volta para ele.
- Enquanto o app roda, ele tem controle exclusivo da iluminação Corsair. Ao sair,
  o iCUE volta para os efeitos dele.

## Instalar / atualizar

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File instalar.ps1
```

O `instalar.ps1` gera o executável (PyInstaller), instala em
`%LOCALAPPDATA%\Programs\RGB Sync`, cria o atalho no Menu Iniciar e abre o app.
Rodar de novo atualiza (fecha a versão aberta antes).

No iCUE, o SDK precisa estar ativado.

## Uso

- Abra pelo **Menu Iniciar → RGB Sync**. Com "Iniciar com o Windows" ligado, abre sem o aviso
  de administrador (o SDK da MSI exige admin; quem dá a permissão é a tarefa agendada).
- Fechar a janela só esconde o app na bandeja (ícone ao lado do relógio, com a cor atual no
  centro). Botão direito no ícone: modo, cores, apagar, sair.
- Dados do usuário (config, backup da MSI, log): `%APPDATA%\RGB Sync`.
- `python diag.py` mostra o estado do app que está rodando (log, config, atalho...).
- `python rgb_core.py --cor 0080ff --segundos 10` — teste rápido por linha de comando (admin).

## Arquivos

- `app.py` — interface (customtkinter) + bandeja (pystray) + abertura/elevação
- `motor.py` — config, instância única, inicialização com o Windows, laço ao vivo
- `rgb_core.py` — backends Corsair, MSI e teclado HyperX
- `hyperx.py` — protocolo e mapa de teclas (ANSI/ABNT2) do Alloy Origins Core (`python hyperx.py` testa)
- `papel_parede.py` — captura do papel de parede e cor por LED
- `busca.py` — procura equipamentos RGB USB (`python busca.py` testa)
- `icone.py` — gera o ícone da fogueira (`assets/`); o da bandeja tem o núcleo na cor atual
- `instalar.ps1` — gera o .exe e instala
- `diagnostico_rgb.py` — diagnóstico somente leitura dos SDKs
