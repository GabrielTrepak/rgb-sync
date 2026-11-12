# Liga ou desliga o RGB Sync na inicialização do Windows.
#
#   Ligar:     powershell -ExecutionPolicy Bypass -File iniciar_com_windows.ps1
#   Desligar:  powershell -ExecutionPolicy Bypass -File iniciar_com_windows.ps1 -Remover
#
# Cria uma tarefa agendada "RGB Sync" que roda no seu login, com privilégio elevado
# (o SDK da MSI exige) — assim o aviso do Windows aparece só UMA vez, agora.
# Não mexe em mais nada do sistema.

param(
    [switch]$Remover,
    [string]$Usuario = "$env:USERDOMAIN\$env:USERNAME"
)

$tarefa = "RGB Sync"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $admin) {
    $argumentos = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Usuario', "`"$Usuario`"")
    if ($Remover) { $argumentos += '-Remover' }
    Start-Process powershell -Verb RunAs -ArgumentList $argumentos -Wait
    exit
}

if ($Remover) {
    Unregister-ScheduledTask -TaskName $tarefa -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Inicialização com o Windows removida."
    exit
}

$pasta   = $PSScriptRoot
$pythonw = Join-Path $pasta '.venv\Scripts\pythonw.exe'
$app     = Join-Path $pasta 'app.py'

$acao      = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$app`" --bandeja" -WorkingDirectory $pasta
$gatilho   = New-ScheduledTaskTrigger -AtLogOn -User $Usuario
$gatilho.Delay = 'PT20S'   # dá tempo do iCUE e do MSI Center subirem
$principal = New-ScheduledTaskPrincipal -UserId $Usuario -LogonType Interactive -RunLevel Highest
$config    = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
                -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $tarefa -Action $acao -Trigger $gatilho -Principal $principal `
    -Settings $config -Description "RGB Sync: cor sincronizada Corsair + MSI" -Force | Out-Null
Write-Host "Pronto: RGB Sync vai iniciar com o Windows (pasta: $pasta)."
