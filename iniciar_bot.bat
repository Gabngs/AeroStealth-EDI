@echo off
rem Lanza el bot como ADMINISTRADOR (el juego corre elevado y si no, no se puede mover el mouse ni pulsar teclas).
rem Doble clic (o por comando: .\iniciar_bot.bat): arranca ya ACTIVO, no abre el juego. Opcional: iniciar_bot.bat 20  -> se inicia solo y se cierra a los 20 minutos.
rem Registro en logs\bot.log
setlocal
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "ARGS=--start"
if not "%~1"=="" set /a SECS=%~1*60 & call set "ARGS=--auto %%SECS%%"

net session >nul 2>&1
if %errorlevel%==0 goto :run

echo Pidiendo permisos de administrador...
if "%~1"=="" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
) else (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%~1' -Verb RunAs"
)
exit /b

:run
cd /d "%REPO%"
if not exist logs mkdir logs
echo Bot en %REPO%  %ARGS%
powershell -NoProfile -Command "py -X utf8 -u -W ignore scripts/bot.py %ARGS% 2>&1 | Tee-Object -FilePath logs\bot.log"
pause
