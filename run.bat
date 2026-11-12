@echo off
setlocal
rem Ayuda completa: run.bat --help; muestra instrucciones sin sincronizar.
rem Sin argumentos vigila en simulacion con tres repositorios ficticios.
rem run.bat --once simula un ciclo; run.bat --once --apply aplica las copias.
rem Ctrl+C termina la vigilancia. Con --apply revisar previamente la simulacion.
rem Sin aplicar solo escribe registros y tiempos en el control de VED-SYNC.
rem Terminal: cabecera fija y barra debajo; --json muestra el informe para scripts.
rem Reenvia todos los argumentos; no ejecuta Git ni activa suscripciones.
rem Arranque de VED-SYNC: vigilancia y simulacion por defecto.
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 goto launcher
where python >nul 2>&1
if not errorlevel 1 goto python
 echo No se encuentra Python 3. Instale Python 3 para arrancar VED-SYNC.
exit /b 127
:launcher
py -3 -m ved_sync --watch %*
exit /b %errorlevel%
:python
python -m ved_sync --watch %*
exit /b %errorlevel%
