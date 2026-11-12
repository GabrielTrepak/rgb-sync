# RGB Sync

Controle de RGB pessoal para Windows: o PC inteiro seguindo o **papel de parede** (ao vivo,
LED a LED) ou uma **cor fixa**, sincronizando Corsair e MSI pelas APIs oficiais dos fabricantes.

| Marca | Dispositivos | Como |
|---|---|---|
| Corsair | iCUE LINK Hub (H150i LCD, fans QX), Vengeance RGB DDR5, HS80 | iCUE SDK (`cuesdk`) |
| MSI | Placa-mÃ£e (JRGB/JARGB), placa de vÃ­deo | Mystic Light SDK (DLL do plugin MSI do iCUE) |
| HyperX | Alloy Origins Core (ANSI e ABNT2), tecla por tecla | protocolo da comunidade (OpenRGB), reescrito em `hyperx.py` â€” sÃ³ comandos de luz |

## Modos

- **Papel de parede** â€” ao vivo (atÃ© 12 quadros/s, ~0,1% de CPU com papel de parede em vÃ­deo).
  Na Corsair, **cada LED recebe a cor da regiÃ£o do papel de parede que corresponde Ã  posiÃ§Ã£o
  fÃ­sica dele** (cada pente de RAM vira uma faixa vertical em degradÃª; as fans do hub LINK pegam
  pedaÃ§os da esquerda para a direita). A MSI, que sÃ³ aceita uma cor por zona, recebe a cor geral
  a cada 2 s. Com a imagem parada (papel estÃ¡tico, Wallpaper Engine pausado num jogo) ele sÃ³
  confere 4Ã—/s e nÃ£o reenvia nada. Funciona com o **Wallpaper Engine** â€” vÃ­deo (captura a
  janela onde ele desenha, ~2 ms) e cena/web em DirectX (captura a camada da Ã¡rea de trabalho,
  ~20 ms, por isso roda a 6 quadros/s) â€” sem pegar as janelas abertas por cima, e com o papel
  de parede normal do Windows. Monitor: principal, secundÃ¡rio ou os dois.
- **Cor fixa** â€” 9 cores prontas, seletor de cor ou cÃ³digo hex.

> **Teclado HyperX:** feche o NGENUITY (e tire ele da inicializaÃ§Ã£o do Windows) â€” ele fica
> reenviando a cor dele e o teclado pisca entre as duas. O app avisa se ele estiver aberto.

> Se usar Wallpaper Engine, desligue o plugin de LED dele (ConfiguraÃ§Ãµes â†’ Plugins â†’ LED)
> para ele nÃ£o disputar o iCUE com o RGB Sync.

- **Efeito** â€” Corsair e teclado animados pelo app (20 quadros/s, LED a LED); placa-mÃ£e e GPU
  usam o efeito nativo da MSI com a mesma cor/velocidade (ela leva ~0,6 s por mudanÃ§a):
  - **RespiraÃ§Ã£o**: a cor escolhida acende e apaga (lenta / mÃ©dia / rÃ¡pida);
  - **Onda**: arco-Ã­ris correndo da esquerda pra direita nas fans, RAM e teclado;
  - **Ciclo**: tudo passa junto por todas as cores;
  - **Temperatura**: azul (frio) â†’ vermelho (quente), pela **temperatura da GPU** (NVML, direto
    do driver NVIDIA, 35â€“85 Â°C) ou pelo **uso da CPU** (0â€“100%). A temperatura da CPU exigiria
    um driver de baixo nÃ­vel, que o projeto evita de propÃ³sito.

## Gabinete (cooler e fans no lugar certo)

O hub iCUE LINK informa a corrente na ordem dos cabos (aqui: fan, fan, cooler, fan, fan, fan)
e quantos LEDs cada um tem. Em **Dispositivos â†’ Cooler e fans no gabinete**, "Identificar"
acende cada um numa cor por 30 s e vocÃª escolhe a posiÃ§Ã£o (topo trÃ¡s/meio/frente, lateral
cima/baixo, traseira, cooler). A partir daÃ­ cada LED do anel da fan pega o papel de parede
**no ponto real do gabinete** (vista pelo vidro: trÃ¡s Ã  esquerda, frente Ã  direita), a onda
passa pelas fans na ordem fÃ­sica, e a prÃ©via desenha o gabinete. Fans que o hub nÃ£o
reconhece (ex.: RX120 com o firmware atual do hub) ficam de fora.

## Aba Luzes (luzes da casa: Tuya / Smart Life / Ekaza)

Controle direto pela rede local (sem nuvem): ligar/desligar, **branca** (brilho e temperatura
quente↔fria) ou **colorida** (cores, seletor, brilho). O estado real é lido a cada 15 s com a
aba aberta (mudanças feitas pelo celular aparecem). Opcional: **Sincronizar com o PC** — a luz
segue a cor geral do PC com brilho próprio, e ao desligar (ou ao sair do app) volta como estava.

Configuração (uma vez): conta gratuita em platform.tuya.com → projeto de nuvem (Smart Home,
Western America) → vincular o app **Smart Life** (QR) → `python -m tinytuya wizard` na pasta do
projeto. O app importa as luzes do `devices.json` para `%APPDATA%\RGB Sync\luzes.json`.
Os arquivos com chaves (`devices.json`, `tinytuya.json`, `snapshot.json`, `tuya-raw.json`)
ficam fora do Git.

## Controle externo (Stream Deck, scripts)

```powershell
python rgbsync_cmd.py perfil Noite
python rgbsync_cmd.py modo efeito        # papel | fixo | efeito
python rgbsync_cmd.py efeito onda        # respiracao | onda | ciclo | temperatura
python rgbsync_cmd.py cor ff0000
python rgbsync_cmd.py brilho 40
```

## Aba Perfis

- **Perfil** = modo, cor, brilho, monitor e quais aparelhos ficam ligados. VÃªm trÃªs prontos
  (Jogo, Noite, Trabalho); o que vocÃª muda na aba IluminaÃ§Ã£o fica salvo no perfil ativo.
- **Atalhos globais**: **Ctrl+Alt+1â€¦9** trocam de perfil de qualquer lugar (inclusive em jogo).
  TambÃ©m dÃ¡ pra trocar pelo seletor da aba IluminaÃ§Ã£o e pelo menu da bandeja.
- **Por programa**: associe um `.exe` a um perfil; quando ele abre, o perfil liga sozinho, e
  quando fecha volta o anterior (o vigia olha a lista de processos a cada 3 s).
- Criar (copia o atual), renomear, excluir e reordenar (a ordem define o atalho).

## Aba Dispositivos

- **Liga/desliga por aparelho**: o que estiver desligado sai da sincronizaÃ§Ã£o (na Corsair, o
  controle volta pro iCUE e ele mostra os efeitos dele; a MSI fica com a Ãºltima cor).
- **Sincronizar tudo de novo**: desconecta e reconecta iCUE e Mystic Light e reenvia as cores
  (tambÃ©m no menu da bandeja).
- **Procurar dispositivos**: reconecta os SDKs e lista os equipamentos RGB USB conectados de
  vÃ¡rias marcas, dizendo se sÃ£o compatÃ­veis. Aparelho novo ganha o selo **NOVO**; 20 s depois
  de iniciar o app faz essa busca sozinho e avisa na bandeja se aparecer algo novo.

## Regras do projeto

- SÃ³ mexe em **iluminaÃ§Ã£o**. VentilaÃ§Ã£o e bomba continuam com o iCUE / MSI Center,
  que precisam ficar instalados.
- **Nunca** atualiza nem grava firmware. Nada de acesso direto a SMBus/RAM.
- A MSI guarda a cor no dispositivo: na primeira execuÃ§Ã£o o estado original Ã© salvo
  (`msi_backup.json`) e o botÃ£o "Restaurar MSI original" volta para ele.
- Enquanto o app roda, ele tem controle exclusivo da iluminaÃ§Ã£o Corsair. Ao sair,
  o iCUE volta para os efeitos dele.

## Instalar / atualizar

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File instalar.ps1
```

O `instalar.ps1` gera o executÃ¡vel (PyInstaller), instala em
`%LOCALAPPDATA%\Programs\RGB Sync`, cria o atalho no Menu Iniciar e abre o app.
Rodar de novo atualiza (fecha a versÃ£o aberta antes).

No iCUE, o SDK precisa estar ativado.

## Uso

- Abra pelo **Menu Iniciar â†’ RGB Sync**. Com "Iniciar com o Windows" ligado, abre sem o aviso
  de administrador (o SDK da MSI exige admin; quem dÃ¡ a permissÃ£o Ã© a tarefa agendada).
- Fechar a janela sÃ³ esconde o app na bandeja (Ã­cone ao lado do relÃ³gio, com a cor atual no
  centro). BotÃ£o direito no Ã­cone: modo, cores, apagar, sair.
- Dados do usuÃ¡rio (config, backup da MSI, log): `%APPDATA%\RGB Sync`.
- `python diag.py` mostra o estado do app que estÃ¡ rodando (log, config, atalho...).
- `python rgb_core.py --cor 0080ff --segundos 10` â€” teste rÃ¡pido por linha de comando (admin).

## Arquivos

- `app.py` â€” interface (customtkinter) + bandeja (pystray) + abertura/elevaÃ§Ã£o
- `motor.py` â€” config, instÃ¢ncia Ãºnica, inicializaÃ§Ã£o com o Windows, laÃ§o ao vivo
- `rgb_core.py` â€” backends Corsair, MSI e teclado HyperX
- `hyperx.py` â€” protocolo e mapa de teclas (ANSI/ABNT2) do Alloy Origins Core (`python hyperx.py` testa)
- `papel_parede.py` â€” captura do papel de parede e cor por LED
- `efeitos.py` â€” efeitos (cÃ¡lculo por LED, estilos nativos da MSI) e sensores (GPU/CPU)
- `rgbsync_cmd.py` â€” controle externo do app que estÃ¡ rodando
- `perfis.py` â€” perfis, atalhos globais (RegisterHotKey) e vigia de programas
- `busca.py` â€” procura equipamentos RGB USB (`python busca.py` testa)
- `icone.py` â€” gera o Ã­cone da fogueira (`assets/`); o da bandeja tem o nÃºcleo na cor atual
- `instalar.ps1` â€” gera o .exe e instala
- `diagnostico_rgb.py` â€” diagnÃ³stico somente leitura dos SDKs
