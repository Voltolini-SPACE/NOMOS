# NOMOS uninstall (Windows) — remove a plataforma; dados só com -Purge confirmado.
param([switch]$Purge)
$ErrorActionPreference = "Stop"

$Prefix = if ($env:NOMOS_PREFIX) { $env:NOMOS_PREFIX } else { Join-Path $env:LOCALAPPDATA "NOMOS" }
$Data   = if ($env:NOMOS_HOME)   { $env:NOMOS_HOME }   else { Join-Path $env:USERPROFILE ".nomos" }

if (Test-Path $Prefix) {
    Remove-Item -Recurse -Force $Prefix
    Write-Host "Plataforma removida ($Prefix)."
} else {
    Write-Host "Nada instalado em $Prefix."
}

if ($Purge) {
    if (-not [Environment]::UserInteractive) {
        Write-Error "NEGADO (fail-closed): -Purge exige sessão interativa."
    }
    $conf = Read-Host "Digite exatamente 'APAGAR TUDO' para destruir os dados em $Data"
    if ($conf -ne "APAGAR TUDO") {
        Write-Host "Purga cancelada (confirmação incorreta)."
        exit 1
    }
    if (Test-Path $Data) { Remove-Item -Recurse -Force $Data }
    Write-Host "Dados do usuário destruídos ($Data)."
} else {
    Write-Host "Dados preservados em $Data (use -Purge para destruição definitiva)."
}
