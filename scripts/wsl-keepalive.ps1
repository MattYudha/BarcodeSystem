# WSL mematikan distro beberapa saat setelah sesi wsl.exe terakhir ditutup, dan Docker di
# dalamnya ikut berhenti -> koneksi ke localhost:5433 timeout. Jalankan skrip ini di terminal
# terpisah selama development untuk menjaga distro tetap hidup (Ctrl+C untuk berhenti).
#
#   .\scripts\wsl-keepalive.ps1
#
# Alternatif permanen: jalankan otomatis saat login lewat Task Scheduler.
$distro = if ($env:BHV_WSL_DISTRO) { $env:BHV_WSL_DISTRO } else { 'Ubuntu-22.04' }
Write-Host "Menjaga WSL '$distro' tetap hidup. Ctrl+C untuk berhenti."
wsl -d $distro -- bash -c "exec sleep infinity"
