# Gera o executável do RGB Sync e instala/atualiza no PC.
#
#   powershell -ExecutionPolicy Bypass -File instalar.ps1
#
# 1. Gera "dist\RGB Sync\RGB Sync.exe" com o PyInstaller (a partir do .venv)
# 2. Fecha a cópia que estiver rodando
# 3. Copia para %LOCALAPPDATA%\Programs\RGB Sync
# 4. Cria o atalho no Menu Iniciar
# 5. Abre o app. Se a inicialização com o Windows apontava para outra cópia, o app
#    se reaponta sozinho (pede administrador UMA vez nesse caso).
# Configuração, backup da MSI e log ficam em %APPDATA%\RGB Sync (não são tocados).

param([switch]$SemBuild)
$ErrorActionPreference = 'Stop'
$raiz    = $PSScriptRoot
$py      = Join-Path $raiz '.venv\Scripts\python.exe'
$destino = Join-Path $env:LOCALAPPDATA 'Programs\RGB Sync'
$exe     = Join-Path $destino 'RGB Sync.exe'

if (-not $SemBuild) {
    & $py (Join-Path $raiz 'icone.py') | Out-Null
    & $py -m PyInstaller --noconfirm --clean --windowed --name 'RGB Sync' `
        --icon (Join-Path $raiz 'assets\rgbsync.ico') `
        --add-data "$(Join-Path $raiz 'assets');assets" `
        --collect-all customtkinter --collect-all cuesdk `
        --hidden-import pystray._win32 --hidden-import hid --hidden-import hyperx --collect-submodules tinytuya `
        --distpath (Join-Path $raiz 'dist') --workpath (Join-Path $raiz 'build') `
        --specpath (Join-Path $raiz 'build') `
        (Join-Path $raiz 'app.py')
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }
}

# fecha a cópia que está rodando (qualquer versão nova entende --sair)
if (Test-Path $exe) { Start-Process $exe -ArgumentList '--sair' -Wait }
Start-Sleep 2

New-Item -ItemType Directory -Force $destino | Out-Null
robocopy (Join-Path $raiz 'dist\RGB Sync') $destino /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "falha ao copiar (robocopy $LASTEXITCODE)" }

$atalho = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\RGB Sync.lnk'
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($atalho)
$lnk.TargetPath = $exe
$lnk.WorkingDirectory = $destino
$lnk.IconLocation = "$exe,0"
$lnk.Description = 'RGB Sync — Corsair + MSI sincronizados'
$lnk.Save()

# Se a inicialização com o Windows aponta para outra cópia, abre elevado uma vez
# para o app reapontar a tarefa para este .exe.
$xml = schtasks /query /tn 'RGB Sync' /xml 2>$null
$aponta = if ($xml) { ([xml]($xml -join "`n")).Task.Actions.Exec.Command } else { $null }
if ($aponta -and ($aponta.Trim('"') -ne $exe)) {
    Start-Process $exe -Verb RunAs
} else {
    Start-Process $exe
}
Write-Host "RGB Sync instalado em $destino"
