@echo off
setlocal
rem Git especifico de VED-SYNC - Autor: Victor Estrada Diaz.
rem https://estradad.es/ - Codigo HL3: https://estradad.es/licencia.php
rem Controla el Git de VED-SYNC, nunca el de proyecto ni el padre SRC-VED.
rem git.bat --help muestra ayuda. Las escrituras requieren --autorizar.
if not exist "%~dp0..\git_control.py" (
  echo No se encuentra el controlador Git propio de VED-SYNC.
  exit /b 1
)
where py >nul 2>&1
if not errorlevel 1 goto launcher
where python >nul 2>&1
if not errorlevel 1 goto python
echo No se encuentra Python 3 para el Git de VED-SYNC.
exit /b 127
:launcher
py -3 "%~dp0..\git_control.py" %*
exit /b %errorlevel%
:python
python "%~dp0..\git_control.py" %*
exit /b %errorlevel%
