# NOMOS installer (Windows) — falha fechado em qualquer inconsistência.
# Uso: baixe este script + o nomos-*.whl da release na MESMA pasta e rode:
#   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"

$Aqui    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Prefix  = if ($env:NOMOS_PREFIX) { $env:NOMOS_PREFIX } else { Join-Path $env:LOCALAPPDATA "NOMOS" }
$Venv    = Join-Path $Prefix "venv"
$Backups = Join-Path $Prefix "backups"
$BinDir  = Join-Path $Prefix "bin"

Write-Host "[1/6] Verificando integridade (SHA256SUMS)..."
$Sums = Join-Path $Aqui "SHA256SUMS"
if (Test-Path $Sums) {
    foreach ($linha in Get-Content $Sums) {
        if ($linha -match "^([0-9a-f]{64})\s+\*?(.+)$") {
            $esperado = $Matches[1]; $arquivo = Join-Path $Aqui $Matches[2].Trim()
            if (Test-Path $arquivo) {
                $obtido = (Get-FileHash -Algorithm SHA256 $arquivo).Hash.ToLower()
                if ($obtido -ne $esperado) {
                    Write-Error "FALHA: checksum divergente em $($Matches[2]) — instalação abortada (fail-closed)."
                }
            }
        }
    }
    Write-Host "      checksums OK."
} else {
    Write-Warning "SHA256SUMS ausente — prosseguindo apenas se isto for build local de desenvolvimento."
}

Write-Host "[2/6] Verificando Python >= 3.10..."
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { Write-Error "FALHA: Python 3.10+ não encontrado. Instale em https://python.org" }
& $py.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if ($LASTEXITCODE -ne 0) { Write-Error "FALHA: Python 3.10+ é obrigatório." }

Write-Host "[3/6] Backup da instalação anterior (rollback)..."
New-Item -ItemType Directory -Force -Path $Backups | Out-Null
if (Test-Path $Venv) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Compress-Archive -Path $Venv -DestinationPath (Join-Path $Backups "venv-$stamp.zip") -Force
    Write-Host "      backup: venv-$stamp.zip"
} else {
    Write-Host "      nenhuma instalação anterior."
}

Write-Host "[4/6] Criando ambiente isolado e instalando..."
$wheel = Get-ChildItem -Path $Aqui -Filter "nomos-*.whl" | Sort-Object Name | Select-Object -Last 1
if ($wheel) { $fonte = $wheel.FullName } else {
    # modo desenvolvimento: instala o código-fonte (pasta pai do installer/)
    $fonte = Split-Path -Parent $Aqui
}
Write-Host "      fonte: $fonte"
& $py.Source -m venv --clear $Venv
& (Join-Path $Venv "Scripts\python.exe") -m pip install --quiet --upgrade pip
& (Join-Path $Venv "Scripts\pip.exe") install --quiet $fonte
if ($LASTEXITCODE -ne 0) { Write-Error "FALHA: pip install não concluiu." }

Write-Host "[5/6] Publicando comando 'nomos'..."
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$shim = Join-Path $BinDir "nomos.cmd"
"@echo off`r`n`"$Venv\Scripts\nomos.exe`" %*" | Set-Content -Path $shim -Encoding ASCII

Write-Host "[6/6] Smoke pós-instalação..."
& (Join-Path $Venv "Scripts\nomos.exe") --version
if ($LASTEXITCODE -ne 0) { Write-Error "FALHA: smoke pós-instalação não passou." }

Write-Host ""
Write-Host "NOMOS instalado."
Write-Host "Comece com:  nomos"
$noPath = ($env:Path -split ";") -notcontains $BinDir
if ($noPath) {
    Write-Host "Para usar 'nomos' de qualquer lugar, adicione ao PATH do usuário:"
    Write-Host "  [Environment]::SetEnvironmentVariable('Path', `$env:Path + ';$BinDir', 'User')"
}
