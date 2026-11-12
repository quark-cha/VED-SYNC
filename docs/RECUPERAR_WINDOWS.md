# Recuperar proyectos de Windows en Ubuntu

Este modo usa Windows como referencia aunque los archivos de Ubuntu tengan fechas
posteriores. No se usa para sincronización multidireccional: escribe únicamente en
Ubuntu y conserva Windows como origen de lectura. No crea identificadores en Windows.

La configuración privada `.ved-sync-recuperacion.json` contiene:

- Origen: `/mnt/windows/Users/vedq/Desktop/desarrollo/SRC-VED`.
- Destino: SRC-VED, el directorio padre del VED-SYNC que se está ejecutando.
- `authoritative_source: "windows"` y `read_only: true` en ese origen.
- Registros y respaldos dentro de `VED-SYNC/.ved-sync/recuperacion-windows`.

VED-SYNC se excluye en ambas raíces para preservar el motor actual. También se
excluyen los nombres internos del motor, `.git`, identificadores, configuración
privada y respaldos `.original`. No se recupera el historial Git mediante este modo.
Los archivos exclusivos de Ubuntu se conservan y se informan como `preserved`, sin
activar el rojo ni impedir el éxito. La copia inversa está bloqueada desde el
principio: esos archivos no son trabajos pendientes. Nunca se propagan al origen
ni se borran. Lo mismo ocurre con los archivos que dejan de existir en Windows.

Los datos temporales de las pruebas se crean en `.test-runs` y se eliminan al
cerrar cada prueba. Ese nombre está reservado y excluido del motor a cualquier
profundidad y sin distinguir mayúsculas: no se lee su contenido, no se copia y no
genera conflictos ni pendientes. Las entradas antiguas de prueba que hubiera en
una cola se retiran del trabajo activo al reanudar, conservando el historial.
El comprobador `tools/check_tests.py` elimina también la carpeta temporal si queda
vacía. La recuperación real usa exclusivamente las raíces del JSON privado;
`demo/repos` y su configuración de ejemplo no intervienen en ella.

Para cada archivo de Windows que deba copiarse, se crea y verifica primero un
respaldo `.original` mediante SHA-256. Antes de sustituir un archivo distinto de
Ubuntu también se conserva y verifica su versión previa. Una verificación fallida
impide esa copia. Puede necesitarse espacio adicional para las dos versiones y el
archivo temporal. Los archivos iguales no se copian de nuevo.

## Ejecución manual

Se excluye siempre cualquier archivo o directorio cuyo nombre empiece por punto,
a cualquier profundidad: `.gitignore`, `.env`, `.venv-comparacion`, etc. La notación
`./` de la raíz no es un nombre oculto: `./archivo.py` se admite y
`./.oculto/archivo.py` se excluye. Esta regla se aplica antes del inventario, los
hashes, las copias y la verificación final, incluso a trabajos antiguos de la cola.
Se conserva su historial; no se presentan esas exclusiones como verificaciones nuevas.

El JSON privado permite `exclude_patterns`, una lista explícita de patrones. Se
aplican antes de calcular hashes, al comparar el historial y al copiar o recuperar.
Los nombres sin `/` se comparan con cada componente de la ruta; los que contienen
`/` parten de la raíz del repositorio. Se usan comodines simples sin distinguir
mayúsculas. No implementa reglas Git completas, negaciones ni lectura automática
de `.gitignore`.

En esta configuración se excluyen `*.zip` y `hashes*.json`, además de cachés Python,
entornos virtuales, temporales, registros y credenciales según los patrones
explícitos consultables en el JSON. Se han tomado como referencia los `.gitignore`
leídos de Windows sin modificarlos. No se trasladan indiscriminadamente reglas que
excluyen código, documentos o imágenes de proyectos concretos. Los archivos ya
existentes que ahora quedan excluidos se conservan: no se borran ni se comparan.
Los hashes internos de verificación de VED-SYNC siguen activos dentro de su control.

Lean: se excluyen `.lake`, `*.olean`, `*.olean.*`, `*.ilean` y `*.trace`, que son dependencias/cachés y
artefactos regenerables del entorno de compilación. Se conservan los fuentes
`*.lean`, `lakefile.lean`, `lakefile.toml`, `lake-manifest.json` y `lean-toolchain`.
Después de recuperar, las dependencias y los compilados se reconstruyen en Ubuntu
con las herramientas del proyecto. No se borran los artefactos que ya existan.
Las nuevas exclusiones se cargan al iniciar otra ejecución; no cambian la que ya
está corriendo.

`*.olean.*` incluye los archivos observados `.olean.server` y `.olean.private`;
no se excluyen fuentes solo por llamarse `server.py`, `Server.lean` o `Trace.lean`.
Por indicación del usuario también se excluye `*.has`, sin distinguir mayúsculas.

Si falla un escaneo, la consola muestra el código de error y el nombre del archivo
cuando el sistema lo proporciona. Los eventos de error del log local conservan `repository`, `path` cuando el
sistema lo proporciona y `detail` con el mensaje completo, además del código y
las referencias anteriores. Los eventos normales siguen usando referencias.
Los registros antiguos no contienen estos datos y no se pueden reconstruir. Un escaneo fallido impide considerar verificado ese árbol;
que el ciclo llegue al 98 por ciento no significa que haya copiado su contenido.

Desde VED-SYNC, para copiar realmente y terminar tras un ciclo:

```bash
./run.sh --config .ved-sync-recuperacion.json --restore-projects --once --apply
```

Para revisar operaciones sin modificar los proyectos, quitar `--apply`. Sin `--once`
continúa vigilando y aplicando la referencia de Windows; no editar Ubuntu durante
esa vigilancia si se quiere conservar su contenido como versión vigente.

`--restore-projects` es una habilitación explícita limitada al padre del motor y
exige un origen autoritativo de solo lectura y un único destino. Sin ella siguen
vigentes los bloqueos habituales para los otros proyectos. El bloqueo de escritura
en `/mnt/windows` permanece activo incluso con esa opción.

La consola recicla tres filas: `Windows → Ubuntu`, estado y barra de progreso.
Durante el guardado final muestra `Guardando y cerrando` al 98 %. Al confirmar el
ciclo muestra `Finalizado correctamente`, el icono ✓ y el 100 %. Si hay pendientes,
errores o interrupción, lo indica expresamente sin presentar el ciclo como éxito.
Al salir nunca conserva el reloj de trabajo: un cierre sin confirmación se indica
como error. Los cambios de consola requieren iniciar una nueva ejecución.
Antes de leer el contenido de los archivos, la primera fila muestra los sentidos
permitidos y bloqueados: `Windows → Ubuntu | permitido; Ubuntu → Windows: bloqueado (solo lectura)`.
Se comprueban la configuración, las protecciones del destino, su disponibilidad,
los permisos de escritura de su raíz y el estado de solo lectura del sistema de
archivos cuando la plataforma permite consultarlo. Los permisos de archivos y
subdirectorios pueden producir errores posteriores; estos siguen bloqueando el éxito.
Ctrl+C interrumpe; repetir el mismo comando retoma el primer pendiente de la cola.
La revisión de nombres, cambios y archivos que faltan se hace al final. Una copia
interrumpida se comprueba antes de repetirse; una copia confirmada sale de la cola.
No borrar el directorio de control si se necesitan sus respaldos e historial.

## Cola FIFO y reanudación

`VED-Sync.cola` está dentro de `.ved-sync/recuperacion-windows` y contiene solo las
copias pendientes, una por línea, en texto UTF-8 sin cabecera:

```text
2;1;UNIHOLOG/run.sh
```

Los campos son origen, destino y ruta relativa a SRC-VED. Los números se asignan
por el orden alfabético de los identificadores de repositorio. En la configuración
actual: 1 es `recuperados` (Ubuntu) y 2 es `windows` (Windows). La configuración
conserva Windows como origen de solo lectura; el formato de la cola no habilita
escrituras en un destino prohibido. Los nombres con punto y coma se citan como CSV.

La cola y el estado de confirmación se gestionan con un índice local transaccional
`.ved-sync-fifo.sqlite`. `VED-Sync.historial` conserva los resultados confirmados y
los metadatos de revisión, separados del fichero de cola. Cada copia confirmada se
retira del FIFO antes de pasar a la siguiente. Si se interrumpe después de publicar
un archivo pero antes de confirmar el trabajo, se comprueba su contenido al retomar:
no se sustituye de nuevo si ya coincide. La vista de texto se publica atómicamente;
si el corte interrumpe su actualización, se reconstruye desde el índice al arrancar.

Tras las copias hay una lista independiente de comprobaciones finales pendientes.
Su avance también se confirma por archivo: un corte no obliga a repetir todas las
comprobaciones ya confirmadas cuyos metadatos siguen iguales. Se revisan al final
los nombres y metadatos de ambos árboles para detectar añadidos, cambios y ausentes.
Los archivos exclusivos de Ubuntu se conservan y se informan sin error: no se exige
una copia inversa que la configuración prohíbe. El verde exige verificar todos los
archivos del origen en el destino, además de guardar el estado y cerrar el ciclo.

La primera preparación reutiliza el inventario del último estado guardado. No
recalcula todas las huellas antes de retomar la primera copia pendiente. La pantalla
restaura el avance de la lista persistente; si aparecen trabajos nuevos o cambios,
el total y el porcentaje pueden ajustarse. La lista no es un certificado histórico.

Durante la recuperación no se genera `operaciones.jsonl` ni `tiempo.csv`. El registro
local `VED-Sync.cola.log` incluye los sentidos permitidos al comenzar, además de
actividad, errores, confirmaciones y memoria; está
limitado a 4 MiB más un segmento anterior de hasta 4 MiB, salvo el tamaño de la última
línea. Las muestras de rendimiento se mantienen solo en memoria, con límite de 1000.
El cierre escribe y confirma en disco una entrada `cycle_finished` con `result`,
`completed` y los contadores de archivos antes de mostrar el éxito en consola.
Al arrancar una nueva ejecución, el motor vacía este log y retira las rotaciones y
los registros de actividad antiguos del mismo conjunto, bajo el bloqueo de ejecución.
La primera entrada es el `cycle_started` de la ejecución nueva. La limpieza automática
conserva el estado, la cola y su historial para reanudar, además de los respaldos.
La cola, índice, historial, auxiliares y registros están excluidos del sincronizador
y de Git; no son archivos de distribución.

Para ver pendientes (desde VED-SYNC):

```bash
head -n 10 .ved-sync/recuperacion-windows/VED-Sync.cola
tail -F .ved-sync/recuperacion-windows/VED-Sync.cola
```

`-F` sigue el nombre porque la cola se sustituye al retirar trabajos confirmados.
Para seguir la actividad y las confirmaciones, incluida la revisión final:

```bash
tail -F .ved-sync/recuperacion-windows/VED-Sync.cola.log
```

## Bloqueos, espacio y reconstrucción

La limpieza local es manual, desde VED-SYNC:

```bash
./limpieza.sh --simular
./limpieza.sh
./limpieza.sh --reiniciar-colas
```

Sin opciones retira logs, muestras de tiempos, cachés Python, temporales reconocidos
y colas finalizadas cuyo estado está guardado. Una cola pendiente o sin cierre
confirmado se conserva. `--reiniciar-colas` la retira también de forma explícita.
En ambos casos, antes de retirar una cola guarda una copia verificada por SHA-256
del conjunto cola/índice/historial en `.ved-sync/backups/limpieza-*`. La siguiente
ejecución reconstruye el plan y vuelve a verificar a partir del estado conservado.
No elimina fuentes, configuración, identidades, `state.json`, `versions/`,
`.original`, respaldos existentes ni archivos de los proyectos de SRC-VED o Windows.
Rechaza enlaces, rutas fuera del motor y bloqueos activos, y mantiene los bloqueos
durante toda la limpieza. `--simular` no borra ni crea archivos.

En Ubuntu la recuperación usa un bloqueo del sistema operativo, liberado al morir
el proceso incluso con SIGKILL. Impide dos recuperaciones simultáneas. `run.lock`
permanece vacío al terminar correctamente; su existencia no indica ejecución activa.
Un bloqueo del formato antiguo solo se retira automáticamente si su PID ya no existe.

Antes de copiar se comprueba el espacio necesario para temporales, respaldos que
faltan y estado final, con margen. Sin espacio se conserva el pendiente y se para;
no se confirma ni se elimina por fallar. Hay que liberar espacio para continuar.

Después de dos ejecuciones consecutivas sin avance, la siguiente puede reconstruir
la lista desde el principio, conservando el historial. Primero respalda la cola,
índice e historial y verifica SHA-256. La reconstrucción del plan es transaccional;
un corte no publica media lista. El reinicio automático no se repite indefinidamente
sin avance, y tampoco se intenta si no hay espacio para hacerlo con seguridad.
Los archivos ya iguales se comprueban, sin volver a copiarlos.

Para solicitar una reconstrucción manual en una sola ejecución:

```bash
./run.sh --config .ved-sync-recuperacion.json --restore-projects --once --apply --reset-queue
```

Esta opción conserva un respaldo local del plan anterior en `queue-backups`; no
borra versiones originales de los archivos. No es necesaria para una reanudación
normal. No borrar cola, índice ni historial mientras haya trabajos pendientes.

## Memoria e integridad

El historial, la caché y los inventarios trabajan desde disco. Las copias y huellas
leen bloques de 1 MiB; en recuperación las escrituras se vacían y sincronizan cada
16 MiB, liberando caché de páginas propia cuando el sistema lo permite. No modifica
los ajustes del sistema ni desactiva oomd. Una presión de memoria causada por el
conjunto de la sesión todavía puede terminar el proceso; el FIFO permite retomar.

El JSON sigue conservando el historial de archivos, las huellas y su esquema.
Durante el trabajo no se reescribe entero cada 30 segundos: la cola confirma por
operación. El estado final se exporta por registros con fsync y sustitución atómica.
Los respaldos originales y sus comprobaciones SHA-256 se mantienen.

Esta preparación no ejecuta la recuperación, no monta unidades, no inicia servicios
ni realiza operaciones Git. Una ejecución futura solo debe considerarse completa
tras revisar errores, pendientes y verificaciones.
