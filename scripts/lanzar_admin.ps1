# Lanza el bot como ADMINISTRADOR (el juego corre elevado: sin esto no puede mover el mouse ni pulsar teclas).
# Uso (desde cualquier terminal, en la carpeta del proyecto):
#   .\scripts\lanzar_admin.ps1 --auto 2400 --fuego 28 --pausa 15
# Los argumentos se pasan tal cual a scripts/bot.py. El log queda en logs\ultima_sesion.log
$repo = Split-Path -Parent $PSScriptRoot
$log  = Join-Path $repo "logs\ultima_sesion.log"
$args_ = ($args -join " ")
$cmd = "cd '$repo'; py -X utf8 -u -W ignore scripts/bot.py $args_ 2>&1 | Tee-Object -FilePath '$log'"
Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile', '-NoExit', '-Command', $cmd
