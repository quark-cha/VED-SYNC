# Instalación

## Ubuntu

Requisito: Python >= 3.10. Desde `SRC-VED/VED-SYNC`:

```bash
python3 --version
python3 -m unittest discover -v
python3 -m ved_sync
```

Para la interfaz, Tkinter y una sesión gráfica deben estar disponibles. Si faltan, el administrador puede instalar los paquetes de Ubuntu `python3-tk` y, si se quiere un entorno virtual, `python3-venv`. Este proyecto no instala paquetes del sistema automáticamente.

Opcional, sin necesidad para ejecutar desde el directorio:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --no-deps -e .
ved-sync
```

La instalación editable puede descargar setuptools según el entorno. No se ha probado esa descarga en esta sesión. Ejecutar directamente `python3 -m ved_sync` no necesita conexión.

## Windows

Instalar Python 3.10 o posterior con el lanzador `py` y Tcl/Tk habilitados. Abrir PowerShell en `SRC-VED\VED-SYNC`:

```powershell
py -3 --version
py -3 -m unittest discover -v
py -3 -m ved_sync
py -3 -m ved_sync --gui
```

Opcional, sin activar scripts de PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m ved_sync
```

Windows no se ha ejecutado en esta sesión: estos pasos son instrucciones pendientes de validación nativa. La prueba de enlaces simbólicos requiere que Windows permita crearlos (modo desarrollador o privilegios adecuados).

## Continuidad y arranque

`--watch` o `--gui` mantienen el proceso activo. Dejar inicialmente la simulación. Para un inicio de sesión automático futuro, un administrador puede configurar el programador de tareas de Windows o una unidad de usuario de systemd en Ubuntu, indicando rutas absolutas del intérprete y del JSON. Se incluyen las plantillas `startup/ved-sync.service.example` y `startup/windows-login.cmd.example`, ambas en simulación. No se han instalado servicios o tareas ni modificado configuraciones del sistema.

## GitHub, solo mediante autorización explícita

No hay remoto predeterminado ni credenciales en el proyecto. Los siguientes son ejemplos para uso manual cuando se autorice; no se han ejecutado:

```bash
./git.sh init --autorizar
./git.sh add --autorizar .
./git.sh commit --autorizar -m "Inicio de VED-SYNC"
./git.sh remote --autorizar add origin URL_AUTORIZADA
./git.sh push --autorizar -u origin HEAD
```

En Windows sustituir `./git.sh` por `.\git.bat`; ambos reenvían los argumentos al controlador común sin el límite anterior de siete argumentos. Revisar antes `status` y `diff`. La primera ejecución sin un `.git` local se detiene, sin modificar SRC-VED. Los scripts no crean repositorios GitHub, no guardan contraseñas y no ejecutan Git automáticamente durante la sincronización.


## Preparar el inicio automático sin activarlo

Ubuntu: editar una copia de `startup/ved-sync.service.example` con rutas absolutas del proyecto, intérprete y JSON. Para una instalación futura autorizada, esa copia se ubicaría en el directorio de unidades de usuario de systemd. No ejecutar `systemctl enable` ni `start` durante estas pruebas. La plantilla utiliza consola; para interfaz gráfica deben comprobarse el entorno de sesión y Tkinter.

Windows: editar una copia de `startup/windows-login.cmd.example` con la ruta real. En una instalación futura, una tarea del Programador al iniciar sesión podría ejecutar esa copia. No registrar ni activar la tarea durante estas pruebas. `--watch` mantiene la consola; `--gui` abre los indicadores con Tcl/Tk instalado.

Mantener simulación hasta revisar los informes de cada equipo. Las plantillas no necesitan privilegios de administrador y no configuran acceso a particiones. Para varios proyectos, preparar una instancia por JSON con registros distintos. La validación de arranque nativo queda pendiente en ambos sistemas.


## Seguimiento durante las pruebas

La consola de progreso usa stderr y conserva el JSON en stdout. `--quiet` silencia la consola, pero mantiene los registros. Con el ejemplo: Ubuntu `tail -f .ved-sync/demo/operaciones.jsonl`; Windows PowerShell `Get-Content .ved-sync\demo\operaciones.jsonl -Tail 30 -Wait`. El historial de velocidades está en `.ved-sync/demo/tiempo.csv`. Los archivos de control permanecen dentro de VED-SYNC incluso en simulación.

Consultar [SALIDAS_Y_RECUPERACION.md](SALIDAS_Y_RECUPERACION.md) antes de usar `--recover`: exige un `.original` válido, no utiliza la caché para autorizar una recuperación y mantiene la simulación predeterminada.


## Lanzadores de este proyecto

Después de las pruebas: Ubuntu `./run.sh`, Windows `.\run.bat`. Inician vigilancia en simulación; `--once` realiza una sola comprobación. Para revisar y gestionar Git cuando el proyecto esté estable: Ubuntu `./git.sh`, Windows `.\git.bat`. El menú no encadena preparación, commit y push, y requiere autorización explícita para cada escritura.

Detalles: [ARRANQUE.md](ARRANQUE.md) y [GIT.md](GIT.md). Git debe pertenecer a VED-SYNC; no se utiliza el repositorio de SRC-VED. No se ha inicializado Git ni configurado un remoto en esta entrega.
