# Wrapper docker compose untuk Windows tanpa Docker Desktop.
# Docker Engine berjalan di dalam WSL; port container diteruskan otomatis ke localhost Windows.
#
#   .\scripts\dc.ps1 up -d                       # Postgres saja (mode dev)
#   .\scripts\dc.ps1 --profile full up -d --build # stack lengkap
#   .\scripts\dc.ps1 logs -f db
#   .\scripts\dc.ps1 down                        # stop (data tetap)
#   .\scripts\dc.ps1 down -v                     # stop + hapus volume data
#
# Distro bisa diganti lewat env BHV_WSL_DISTRO (default Ubuntu-22.04).
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$distro = if ($env:BHV_WSL_DISTRO) { $env:BHV_WSL_DISTRO } else { 'Ubuntu-22.04' }
$composeArgs = @('compose', '-f', 'infra/docker-compose.yml')
if (Test-Path (Join-Path $root '.env')) { $composeArgs += @('--env-file', '.env') }

# wsl --cd menerima path Windows langsung. Output progres compose ke stderr itu normal.
wsl -d $distro --cd $root -- docker @composeArgs @args
exit $LASTEXITCODE
