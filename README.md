# VED-SYNC

Sincronizador conservador en Python 3.10 o posterior. El proyecto vive siempre en `SRC-VED/VED-SYNC`; `../` es SRC-VED. No requiere bibliotecas externas para el motor. Estado de validación y límites: [AUDITORIA.md](AUDITORIA.md).

No se sincroniza ningún archivo ni directorio cuyo nombre empiece por punto, a
cualquier profundidad. `./` como referencia a la raíz se normaliza y se permite;
`./archivo.py` es válido y `./.oculto/archivo.py` queda excluido. La regla también
retira del trabajo activo los archivos ocultos de colas anteriores antes de leerlos.

## Inicio seguro

La limpieza se ejecuta bajo petición con `./limpieza.sh`; `./limpieza.sh --simular`
muestra qué retiraría. Borra registros de ejecución, cachés Python, temporales
reconocidos y colas finalizadas. Antes de retirar una cola, respalda y verifica por
SHA-256 la cola, el índice y su historial como conjunto. Conserva el estado, las
configuraciones, identidades, fuentes, `versions/`, `.original` y respaldos existentes.
Una cola pendiente se conserva; `--reiniciar-colas` permite retirarla expresamente
con respaldo y reconstruirla en el siguiente arranque. `--config RUTA.json` limita
los registros y colas a ese directorio de control. Rechaza ejecuciones activas,
enlaces y rutas fuera de VED-SYNC.

Al arrancar cada ciclo, el motor limpia automáticamente los registros de actividad
anteriores de ese conjunto y sus rotaciones, después de adquirir el bloqueo.
El log activo contiene sólo la ejecución actual. El estado, las colas y los respaldos
permiten reanudar; las muestras de tiempos se conservan para calcular estimaciones.

Desde `SRC-VED/VED-SYNC`, `./run.sh` en Ubuntu o `.\run.bat` en Windows arrancan vigilancia en simulación. `--once` ejecuta un ciclo y termina; `--apply` habilita copias explícitamente. Ver [arranque](docs/ARRANQUE.md).

```bash
python3 -m ved_sync                         # simulación, tres directorios ficticios vacíos
python3 -m unittest discover -v             # pruebas aisladas dentro del proyecto
python3 -m ved_sync --gui                   # ventana permanente, simulación
python3 -m ved_sync --watch                 # sondeo en consola, Ctrl+C para salir
```

En Windows, sustituir `python3` por `py -3`. El ejemplo nunca apunta a repositorios reales. Para ensayar una copia, crear manualmente un archivo de prueba en `demo/repos/uno`, ejecutar primero la simulación y después:

```bash
python3 -m ved_sync --apply
python3 -m ved_sync --gui --apply
```

`--apply` habilita copias y registro de versiones. Sin él, los repositorios no se modifican. La simulación crea el directorio local de control, su bloqueo temporal, el log de operaciones y las muestras de tiempos; no modifica el historial de versiones ni los repositorios. Salidas: 0 sin desincronización conocida, 1 si hay rojo y 2 para un error de configuración/ejecución. Gris significa no disponible, y puede coexistir con una salida 0 si todos los repositorios están ausentes: consultar siempre el JSON.

## Configuración portable

[config/example.json](config/example.json) configura tres repositorios. Las rutas relativas se resuelven desde el JSON, nunca desde el directorio desde el que se ejecuta el comando. Cada repositorio tiene un `id` estable y `path`, o una lista `paths` con ubicaciones alternativas. Si varias alternativas existen simultáneamente, se elige únicamente una coincidencia inequívoca con su UUID conocido; sin esa coincidencia se bloquea el repositorio. No se crean raíces de repositorios ausentes.

Se permiten variables de entorno y `~`. Usar rutas apropiadas a cada sistema: `E:/DATOS`, `//servidor/recurso`, `/media/usuario/USB/DATOS` o una ruta de red ya montada por el usuario. Una ruta accesible se vuelve a detectar en cada ciclo; el motor no monta discos ni arranca otros sistemas operativos. Las rutas alternativas de otro sistema suelen permanecer ausentes; conviene revisar siempre la simulación en cada equipo.

Para FOTOS, copiar el JSON a `config/fotos.json`, cambiar las raíces y asignar un `state_dir` propio, por ejemplo `../.ved-sync/fotos`. Ejecutar con `--config config/fotos.json`. Usar IDs estables y un registro distinto por conjunto de datos. No compartir el mismo registro entre procesos de equipos distintos.

Para repositorios fuera de VED-SYNC hacen falta **ambas** opciones `--apply --allow-external`. No se ha realizado ninguna prueba con datos reales. Aunque se habiliten, el programa rechaza destinos en otros proyectos de SRC-VED y en `/mnt/windows`. No configurar datos del sistema operativo. El registro y las versiones permanecen dentro de VED-SYNC.

## Cómo sincroniza

- Lee tamaño, fecha en nanosegundos y SHA-256. El hash decide el contenido: ni una fecha más reciente ni un tamaño igual prueban equivalencia.
- Conserva por archivo el hash vigente, hashes reconocidos por repositorio, observaciones y un historial de versiones con fecha. La primera importación de contenidos distintos queda en conflicto.
- Una edición basada en la versión vigente se propaga. Ediciones incompatibles y ediciones desde una base atrasada se bloquean; nunca se decide por «el más reciente». Los conflictos aparecen en JSON y mantienen luces rojas.
- Antes de sustituir un destino guarda y verifica el contenido anterior en `.ved-sync/<conjunto>/versions/<sha256>.original` y conserva el archivo legado `<sha256>`. Ambos respaldos se verifican antes de sustituir. Los contenidos idénticos comparten archivo de versión. El registro enlaza las versiones con sus rutas. No se podan versiones automáticamente.
- Un archivo conocido que falta se restaura desde un `.original` generado y verificado a partir de la copia vigente disponible; las eliminaciones y renombrados no se propagan. Un renombrado puede dejar ambos nombres.
- Revalida origen y destino alrededor de las copias y vuelve a escanear antes de indicar verde. Los archivos nuevos usan publicación exclusiva desde un temporal verificado cuando hay enlaces duros; en otros sistemas usan creación exclusiva y copia. Los reemplazos usan un temporal y sustitución. No se garantiza una transacción entre todos los repositorios.

Resolver un conflicto: detener la sincronización, conservar copias de las variantes y escribir manualmente el contenido acordado en todos los repositorios afectados, incluidos los desconectados cuando vuelvan. Reiniciar en simulación y verificar. No borrar el registro para «resolver» un conflicto: perdería la base de comparación.

## Indicadores y funcionamiento continuo

La ventana Tkinter permanece visible y solicita estar encima de otras ventanas. Hay una luz y texto por repositorio: amarillo durante el ciclo, verde tras verificar igualdad con todos los repositorios configurados, rojo ante diferencias, conflictos o errores, gris cuando la ruta no está disponible. Con un repositorio desconectado, los accesibles permanecen rojos porque no puede verificarse el conjunto completo. Verde corresponde al instante de la última comprobación.

El sondeo es secuencial; duerme `interval_seconds` tras cada ciclo y no acumula tareas. El hash se calcula por bloques de 1 MiB. El trabajo corre fuera del hilo de la interfaz. Para cerrar la ventana, espera a que termine la operación actual. Una unidad de red bloqueada puede retrasar el cierre.

## Recuperación y límites

El registro se sustituye de forma atómica por archivo. Al reiniciar se vuelve a comparar: las copias completas no se repiten. No hay reanudación por bloques ni garantía frente a cortes de corriente. Un fallo durante la creación de un archivo nuevo puede dejarlo parcial; se tratará conservadoramente en el siguiente ciclo y puede requerir resolución manual.

Un cierre abrupto puede dejar `.ved-sync/<conjunto>/run.lock`. Confirmar primero que no queda ningún proceso VED-SYNC y retirar **solo ese bloqueo** manualmente. No borrar el registro ni las versiones. El prefijo de archivo `.ved-sync-` está reservado para temporales: no se sincroniza. Los temporales abandonados no se borran automáticamente.

No se admiten enlaces simbólicos ni archivos especiales. Los controles no son una frontera de seguridad frente a cambios maliciosos de enlaces/junctions. Los escritores externos que cambien un archivo justo entre la última comprobación y su sustitución no están bloqueados por el motor: para datos críticos usar archivos cerrados o instantáneas y verificar copias. El bloqueo impide dos instancias del motor con el mismo registro, no impide que otras aplicaciones editen datos.

El sondeo recorre nombres y metadatos dos veces por ciclo. La caché persistente evita releer contenido estable, con verificaciones SHA-256 periódicas. Grandes bibliotecas requieren mediciones antes de uso. No hay aún límites de ancho de banda, bandeja de sistema ni instalador; se incluyen plantillas de arranque sin activar. Se sincroniza contenido y se intenta conservar fechas; no se replica ACL, propietario, streams NTFS ni permisos de forma universal. Hay que validar nombres compatibles, mayúsculas/minúsculas y restricciones del sistema de archivos antes de cruzar plataformas. Windows, USB y redes reales quedan pendientes de ensayo.

## Instalación y Git

Los lanzadores específicos están en `proyecto/git.sh` y `proyecto/git.bat`.
Desde VED-SYNC: `./proyecto/git.sh` en Ubuntu o `.\proyecto\git.bat` en Windows.
Ambos usan `git_control.py` de la raíz y operan sobre el Git propio de VED-SYNC;
los lanzadores anteriores de la raíz continúan disponibles.
Si falta el repositorio Git propio, el primer arranque interactivo pregunta si se
quiere crear, con No como respuesta predeterminada. Sólo una respuesta afirmativa
inicializa el Git de VED-SYNC.
El nombre remoto debe coincidir con el nombre base de la carpeta padre de
`proyecto/`: aquí, `VED-SYNC`. La opción **2 — SUBIR CAMBIOS** prepara los archivos,
crea el commit y publica la rama actual. Pide un mensaje y confirmación con `s`.
Si falta la identidad de Git, pide el nombre y el correo antes de preparar archivos
y explica que identifican al autor y aparecerán en los commits. Pregunta si se
quieren guardar y reutilizar sólo en este proyecto (`S`), o usarlos sólo esta vez
(`n`). Si ya están configurados, muestra la identidad que reutiliza sin pedirla
de nuevo. Los datos se guardan al confirmar la operación, en la configuración
local de Git, fuera de los archivos publicados.
Si falta `origin`, pide la cuenta o URL del usuario de esta copia, sin datos
personales predeterminados. Indica por separado **COMMIT CREADO** y **SUBIDA COMPLETADA**;
si la subida falla, el commit queda guardado localmente. La opción **6** abre
las operaciones avanzadas por separado, incluida la configuración de otro remoto.

El proyecto no pide ni guarda tokens o contraseñas en sus archivos. Git usa el
almacén protegido del sistema mediante Git Credential Manager o libsecret;
si no está disponible, sólo los conserva en memoria durante 15 minutos en Ubuntu.
Antes de preparar, confirmar y publicar se revisan archivos y patrones de secretos;
la publicación también revisa el historial. Nombre y correo sí forman parte del
commit público: para ocultar el correo personal, usar un correo `noreply`.
Ver [privacidad del acceso Git](docs/GIT.md#privacidad-y-credenciales).

Si GitHub solicita `Password`, espera un token de acceso, no la contraseña de
la web. En Ubuntu puede evitar introducir tokens instalando
`sudo apt install git-credential-oauth`: el lanzador lo detecta y abre el navegador
para autorizar el acceso. Mantiene el almacén protegido o la caché de memoria;
no guarda tokens en archivos del proyecto. Un fallo de subida conserva el commit local.

Si GitHub responde que no encuentra el repositorio, el programa verifica la
cuenta autorizada. Si confirma que el destino falta en su propia cuenta, pregunta
si desea crearlo **privado**, **público** o **no crearlo** (Intro cancela).
Comprueba el índice y el historial antes de crear el destino; sólo tras la elección
crea el repositorio vacío y reintenta la subida. No crea un segundo commit para
ese reintento ni cambia la visibilidad de repositorios existentes.

Ver [docs/INSTALACION.md](docs/INSTALACION.md). `git.sh` y `git.bat` operan sobre el `.git` propio de VED-SYNC; evitan actuar sobre el repositorio padre. En una terminal preguntan antes de crearlo si falta y abren un menú con revisiones y confirmaciones explícitas; sin terminal muestran sólo estado e instrucciones. Admiten `status`, `diff`, `log` y, con `--autorizar`, `init`, `fetch`, `pull`, `add`, `commit`, `remote` y `push`. Ambos utilizan `git_control.py` y rechazan el Git del padre. Ver [guía Git](docs/GIT.md).


## Identidad opcional de los repositorios

Cada raíz puede contener `.ved-sync-id`: un UUID v4 propio de ese repositorio, independiente del proyecto y de las versiones de sus archivos. No es una credencial ni un secreto criptográfico. La lista explícita `INTERNAL_FILES` de `ved_sync/identity.py` y `INTERNAL_PREFIXES` excluyen los identificadores y temporales en todos los niveles del árbol, incluso del archivo de versiones. `.gitignore` excluye `.ved-sync-id` en VED-SYNC; al configurar repositorios Git externos en el futuro, añadir esa misma regla a sus exclusiones locales. El motor no modifica sus configuraciones Git ni elimina identificadores ya versionados.

Por defecto `persistent_ids: true` permite crear el identificador solo con `--apply`. `persistent_ids: false` desactiva su creación automática; los identificadores existentes siguen leyéndose para detectar duplicados. En simulación no se crea ninguno. Sin identificador se mantiene la sincronización por ID lógico y ruta, como antes.

La creación publica mediante enlace duro un temporal completo, escrito con `fsync`, sin sustituir un identificador concurrente. Un medio de solo lectura, o sin soporte para esa publicación atómica, continúa sin identificador. Los UUID duplicados bloquean los repositorios afectados, conservándolos separados. Un UUID inválido se conserva y se notifica como error. El motor nunca copia el UUID para resolver una duplicidad.

El registro guarda `repository_ids` asociado al `id` lógico de configuración. Al cambiar una ubicación, conservar ese `id`, mover la raíz con su archivo e incluir la nueva ruta en `paths`. Para buscarla bajo ubicaciones variables, se puede usar:

```json
{
  "id": "usb-fotos",
  "path": "../demo/repos/usb-anterior",
  "uuid": "e68bb94c-fdb3-4d64-8543-e1ee1d42d968",
  "search_roots": ["../demo/montajes"]
}
```

Sustituir el UUID del ejemplo por el del repositorio. `search_roots` examina solo cada raíz de búsqueda y sus hijos inmediatos, sin montar unidades, recorrer discos completos ni crear identidades en directorios encontrados durante esa búsqueda. Usar raíces lo más concretas posible. Sin UUID conocido, solo se consideran las rutas explícitas. Entre equipos nuevos, trasladar la configuración con el campo `uuid`; no compartir simultáneamente el registro de ejecución. La identidad reconoce la raíz, pero el historial de versiones sigue siendo necesario para reconocer ediciones antiguas.

Si se elimina un identificador, el repositorio vuelve a funcionar sin él y puede generar otro sin provocar copias de contenido. Eliminarlo pierde la continuidad de esa identidad. Sustituirlo por otro UUID ya existente produce un error de identidad hasta revisar la configuración. No hay recuperación automática de la identidad original sin el archivo o un registro anterior.

## Caché, integridad y varios proyectos

`integrity_seconds` vale 300 por defecto. La caché de SHA-256 persiste en el registro y se invalida por tamaño, fecha de modificación, fecha de cambio de metadatos, dispositivo o inode. Tras el intervalo se relee todo el contenido; `0` fuerza siempre SHA-256 completo. Una hora del sistema que retrocede también invalida la entrada. Las comprobaciones de origen y destino durante las copias siguen calculando hashes completos.

Una alteración invisible en todos esos metadatos puede tardar hasta la siguiente comprobación completa en detectarse. Verde significa igualdad comprobada con esa política de integridad, no una lectura completa de cada byte en cada sondeo. Para validación estricta utilizar `integrity_seconds: 0`. La caché debe permanecer protegida como el resto del historial.

Se admite cualquier número de proyectos mediante un JSON y `state_dir` distinto por proyecto, ejecutando una instancia por configuración. No existe aún un panel que agrupe proyectos. Añadir otro repositorio solo requiere incorporarlo al JSON y reiniciar la instancia. La prueba `test_independent_projects_and_dynamic_addition` verifica aislamiento y alta de un cuarto repositorio. Para FOTOS, el motor y los módulos de identidad e interfaz proporcionan una base separada; catalogación y detección de duplicados están pendientes.

Para ejecutar toda la batería con control adicional de escrituras Python:

```bash
python3 tools/check_tests.py
```

El control audita el proceso Python de pruebas; los subprocesos CLI se prueban con rutas ficticias y no heredan ese gancho de auditoría. Ver el alcance y los pendientes en `AUDITORIA.md`. Las plantillas de `startup/` preparan inicio de sesión en simulación y no se han instalado ni activado.


## Consola, log, tiempos y recuperación

La consola utiliza **tres filas fijas**: dirección de copia (por ejemplo Windows → Ubuntu), semáforo/ubicación/icono/proyecto/archivos y, debajo, barra global con bytes de E/S y ETA. El log conserva el detalle por archivo. En terminal no se imprimen bloques JSON entre avances; `--json`, `--quiet` o redirigir stdout mantienen la salida JSON para scripts. La simulación también registra actividad y tiempos dentro del directorio de control.

Cada `state_dir` contiene `operaciones.jsonl` (consultable con `tail -f`) y `tiempo.csv` (1000 muestras por defecto, configurable con `timing_limit`). Las estimaciones usan muestras exitosas filtradas por operación/tipo de dispositivo y se ajustan durante la operación. Configurar `device_type` por repositorio: `local`, `usb`, `network` o `unknown`.

Las sustituciones registran intención y confirmación duraderas. Las recuperaciones explícitas usan `--recover REPOSITORIO RUTA SHA256`, en simulación salvo `--apply`. **Toda recuperación, incluida la restauración automática de un archivo conocido ausente, verifica un `.original` por SHA-256 sin caché antes de escribir el destino.** Un respaldo corrupto impide la recuperación. Los identificadores, temporales y el sufijo `.original` son internos excluidos del contenido sincronizable.

Procedimiento completo, privacidad del log, interpretación de barras y límites: [docs/SALIDAS_Y_RECUPERACION.md](docs/SALIDAS_Y_RECUPERACION.md). Validación y mediciones: [AUDITORIA.md](AUDITORIA.md).


## Ubicaciones privadas de cada copia

El archivo `.ved-sync-config.json` es local y está excluido de la sincronización y de Git, igual que los metadatos `.git` se excluyen del motor. El borrador de ubicaciones reales todavía no se usa al arrancar: la demostración sigue siendo el valor predeterminado. Falta confirmar la carpeta montada del USB y adaptar de forma autorizada el soporte del SRC-VED completo. Ver [CONFIGURACION_LOCAL.md](docs/CONFIGURACION_LOCAL.md).
# Recuperación Windows → Ubuntu

Para recuperar los proyectos reales tomando Windows como referencia y conservando
VED-SYNC en Ubuntu, consultar [el procedimiento manual](docs/RECUPERAR_WINDOWS.md).
Requiere configuración privada y habilitación explícita; el arranque predeterminado
mantiene la demostración en simulación. No se ha ejecutado la recuperación real.

