# Arrancar VED-SYNC

Los dos lanzadores se encuentran en la raíz de `SRC-VED/VED-SYNC` y utilizan el mismo motor Python.

Ubuntu:

```bash
./run.sh
```

Windows:

```powershell
.\run.bat
```

Ambos arrancan vigilancia periódica (`--watch`) **en simulación**, con la configuración de ejemplo y sus tres repositorios ficticios. No copian contenido por defecto. Los registros locales del motor permanecen dentro del proyecto. Detener con `Ctrl+C`; el cierre capturado registra el resultado y libera el bloqueo. No instalan ni activan arranque automático.

Para una única comprobación:

```bash
./run.sh --once
./run.sh --once --config "config/pruebas.json"
```

Aplicar copias, únicamente sobre fixtures revisados durante esta fase:

```bash
./run.sh --once --config "config/pruebas.json" --apply
```

Para indicadores gráficos, con Tkinter y sesión gráfica disponibles:

```bash
./run.sh --gui
```

En Windows sustituir `./run.sh` por `.\run.bat` y conservar los mismos argumentos. `--once` no se combina con `--gui`. `--quiet` silencia el progreso de consola y conserva el JSON, log y tiempos. `--help` muestra opciones y termina sin sincronizar. Para recuperación explícita, utilizar directamente `python3 -m ved_sync --recover ...` según la guía de recuperación; el lanzador está destinado a vigilancia.

Las rutas del programa se resuelven desde la carpeta del propio lanzador, independientemente del directorio desde el que se invoque. Los argumentos con espacios deben ir entre comillas. Las rutas relativas de `--config` parten de VED-SYNC; las rutas de repositorios dentro del JSON se resuelven respecto al propio JSON.

Requieren Python >= 3.10; Ubuntu usa `python3`, Windows `py -3` y, en su ausencia, `python`. No requieren Git para arrancar el sincronizador. La interfaz gráfica requiere Tkinter; el funcionamiento de consola no lo necesita.

Pruebas no destructivas: `python3 -m unittest tests.test_launchers -v`. Se comprueban sintaxis Bash, simulación, reenvío de argumentos, rutas con espacios, equivalencia del módulo/opciones y aplicación explícita sobre tres repositorios ficticios. El BAT se revisa estructuralmente; la ejecución nativa en Windows queda pendiente.


## Ayuda integrada y comentarios

`./run.sh --help` y `.\run.bat --help` explican los repositorios ficticios predeterminados, simulación, aplicación explícita, vigilancia, salida con `--once`, comprobación de estados y archivos de control que se escriben. Mostrar la ayuda no ejecuta el sincronizador, incluso si también se proporciona `--apply`. Los encabezados de ambos lanzadores contienen ejemplos y remiten a esa ayuda.


## Consola en tres filas fijas

En una terminal compatible, la segunda fila contiene semáforo, ubicación, icono, nombre del proyecto y archivos completados/total. ⌛ indica que el ciclo trabaja; ✓ indica que terminó correctamente; ! indica final con problemas. El semáforo también incluye la palabra del color. `[SIM]` identifica la simulación. La ubicación muestra la raíz en curso y vuelve al proyecto al concluir; el contador considera cada ruta relativa una vez, sin multiplicarla por sus réplicas. Antes de terminar el inventario aparece `0/?`.

La tercera fila contiene la barra global, porcentaje, bytes y ETA. Si cabe, añade el nombre y porcentaje del archivo en curso. Las tres posiciones se reescriben sin añadir filas por cada evento. Las rutas largas se abrevian para evitar que la línea se envuelva. El detalle de operaciones y errores continúa en `operaciones.jsonl`.

Durante la confirmación final se indica `Guardando y cerrando` al 98 %. Al terminar,
la tercera fila dice `Finalizado correctamente` con el 100 %, `Finalizado con
pendientes`, `Finalizado con errores` o `Interrumpido`, según el resultado. Un cierre
sin confirmación deja de mostrar el reloj y se identifica como error; no fuerza
el verde ni el 100 %. En recuperación, el registro es `VED-Sync.cola.log` y conserva
una entrada final `cycle_finished` confirmada en disco antes de anunciar el éxito.

`--json` conserva el informe para automatizaciones y desactiva la pantalla fija. Al redirigir stdout se conserva automáticamente el JSON; `--quiet` mantiene el comportamiento anterior de JSON sin progreso. Sin terminal compatible, stderr muestra solo una instantánea final por ciclo, sin secuencias de cursor. En terminales que no admiten los iconos se utilizan `>` para trabajo y `+` para final correcto.

La representación se ha comprobado mediante eventos simulados y un emulador de cursor. Tras la instrucción del usuario de ejecutar él mismo el programa, no se han lanzado sincronizaciones ni demostraciones adicionales. La prueba visual real con `./run.sh` corresponde al usuario.

Antes de comparar el contenido, la primera fila indica los sentidos permitidos según la configuración, las protecciones y los permisos del destino. En recuperación muestra `Windows → Ubuntu | permitido; Ubuntu → Windows: bloqueado (solo lectura)`. En sincronización multidireccional se actualiza con cada dirección seleccionada e indica también si se permite la inversa. Al terminar conserva esa información. Los archivos exclusivos del destino de una recuperación autoritativa se conservan como información, sin activar el rojo ni exigir la copia inversa. Los fallos de copia o verificación siguen impidiendo el éxito. La segunda fila muestra estado y la tercera el progreso. En un terminal sin control de cursor se imprime solo la instantánea final.
