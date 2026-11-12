@echo off
setlocal
rem Ayuda completa: git.bat --help; no ejecuta Git ni conecta.
rem Sin argumentos abre menu en terminal o muestra estado fuera de terminal.
rem Controla solo el Git propio de VED-SYNC, nunca el de SRC-VED.
rem init inicializa Git local; no crea repositorios en GitHub.
rem Preparar, commit y push son pasos separados y requieren autorizacion.
rem El menu pide AUTORIZAR; los subcomandos necesitan --autorizar.
rem No contrata servicios. Comparte controlador e instrucciones con git.sh.
rem Control Git de VED-SYNC: siempre relativo al propio script.
where py >nul 2>&1
if not errorlevel 1 goto launcher
where python >nul 2>&1
if not errorlevel 1 goto python
 echo No se encuentra Python 3. Instale Python 3 para usar el controlador Git.
exit /b 127
:launcher
py -3 "%~dp0git_control.py" %*
exit /b %errorlevel%
:python
python "%~dp0git_control.py" %*
exit /b %errorlevel%
