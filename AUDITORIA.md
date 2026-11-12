# Auditoría de VED-SYNC

Fecha: 2026-11-11. Desarrollo sobre el proyecto existente en `SRC-VED/VED-SYNC`.

**Proyecto en desarrollo, no terminado.** La última ejecución completa registrada superó **124 pruebas en 38,914 segundos, sin omisiones**, con **8.517 operaciones de escritura Python auditadas dentro del proyecto** y Git 2.53.0 disponible, en Linux con repositorios ficticios. Los detalles figuran en el apartado de esta ampliación y en el registro enlazado. Windows, GUI y medios físicos siguen sin validación nativa. `python3 -m compileall -q ved_sync tests tools` y `bash -n git.sh` terminaron con salida 0. El registro exacto está en [docs/RESULTADOS_PRUEBAS.txt](docs/RESULTADOS_PRUEBAS.txt).

## Directivas y pruebas permanentes

| Directiva | Estado | Evidencia automatizada / límite |
|---|---|---|
| 1. Un motor Python Windows/Ubuntu | Parcial | Motor común sin dependencias; suite ejecutada en Linux. Windows pendiente. |
| 2. SRC-VED es el padre | Comprobada | `PROJECT.parent`; fixtures dentro de `PROJECT/.test-runs`; control de destinos prohibidos. |
| 3. Cualquier número de proyectos y >=2 repositorios | Comprobada con fixtures | `test_independent_projects_and_dynamic_addition`, `test_two_and_four_repositories`. Configuración y proceso independientes por proyecto; panel agregado pendiente. |
| 4. Sincronización multidireccional | Comprobada con fixtures | `test_three_way_bidirectional_and_new_nested_binary`, alta de cuarto repositorio. |
| 5. Fechas, tamaños, SHA-256 e historial | Comprobada con fixtures | `test_hash_detects_same_size_and_date`, `test_version_archive`. |
| 6. Protección de incompatibles | Parcial ante escritores externos | Conflictos iniciales, ediciones simultáneas, bases antiguas y destino cambiado entre escaneo y copia. Las variantes permanecen en las raíces; se archiva antes de sustituir una versión compatible. No existe bloqueo frente a aplicaciones ajenas. |
| 7. No propagar borrados | Comprobada | `test_no_deletion_propagation`, `test_all_known_copies_missing_are_pending`. |
| 8. Caché persistente e integridad | Comprobada con fixtures; rendimiento pendiente | `tests/test_cache.py`: reutilización tras reinicio sin hashes de contenido, invalidación con fecha/tamaño iguales, expiración y verificación completa. TTL predeterminado 300 s, 0 estricto. Medición a gran escala pendiente. |
| 9. Disponibilidad e identidad tras cambios de unidad | Parcial | Desconexión/reconexión y búsqueda acotada por UUID en nuevo montaje ficticio. Requiere rutas accesibles y `search_roots` configurados o actualizar `paths`. No monta discos. USB/red/Windows reales pendientes. |
| 10. Alta de repositorios sin cambiar código | Comprobada | Alta por JSON de cuarto repositorio y rutas alternativas. |
| 11. Automatismo ligero | Parcial | Sondeo de nombres/metadatos, caché, pausas configurables y parada por interrupción. No hay watcher nativo de eventos ni mediciones de presupuesto de CPU/E/S. |
| 12. Preparar arranque sin activarlo | Preparada, validación nativa pendiente | Plantillas en `startup/`; prueba comprueba `--watch` y ausencia de `--apply`. No instaladas ni activadas. |
| 13. Cuatro indicadores permanentes | Parcial | Pruebas amarillo/verde, rojo de conflictos y gris de desconexión o acceso denegado, incluida pérdida de acceso en la verificación final que impide verde. Tkinter común; falta validación visual y de sesión en ambos SO. |
| 14. Interfaces por plataforma con motor común | Parcial | CLI y Tkinter usan Engine. Sin integración nativa de bandeja; GUI sin probar visualmente. |
| 15. Base modular para FOTOS | Preparada parcialmente | Motor, identidad y GUI separados; configuración por conjunto. Catalogación y duplicados pendientes. |

Las 13 comprobaciones previas permanecen cubiertas por la suite original; las nuevas pruebas añaden identidad, caché, proyectos independientes, alta dinámica y plantillas. La prueba de ambigüedad de rutas desactiva IDs para conservar su caso original; otra verifica que un UUID conocido resuelve rutas alternativas.

## Identificadores opcionales

`tests/test_identity.py` verifica UUID v4 distintos por raíz, persistencia, ausencia, creación desactivada, simulación sin escrituras en raíces, fallo de escritura, directorio POSIX de solo lectura, duplicación bloqueada, exclusión de escaneo/copias/versiones, exclusión Git, cambio de ruta, descubrimiento por UUID, nuevo registro en otro equipo simulado, regeneración sin eventos de contenido, datos inválidos y carrera de publicación atómica.

Lista interna explícita en `ved_sync/identity.py`. Los UUID no son credenciales. Publicación atómica mediante enlace duro desde temporal con fsync; si el sistema de archivos no lo soporta, se continúa sin ID. No se garantiza durabilidad del directorio frente a pérdida de alimentación. El motor no modifica Git externo: en un repositorio Git ajeno será necesario excluir el nombre localmente antes de usarlo. Aquí `.gitignore` lo excluye en todos los niveles.

## Interrupciones, seguridad y alcance

`test_resume_after_failure` comprueba reintento tras fallo de copia; `test_target_changed_after_scan_preserved` protege edición concurrente; `test_exclusive_lock` impide ejecución simultánea con el mismo registro. El historial permite continuar tras reiniciar. No hay reanudación por bloques ni prueba de corte físico de alimentación. La publicación nueva es atómica y exclusiva cuando hay enlaces duros. En la alternativa sin ese soporte, una interrupción durante la creación exclusiva puede dejar contenido parcial y requerir resolución manual. Un cierre abrupto puede dejar `run.lock`, que debe revisarse manualmente.

Todos los fixtures están dentro de `.test-runs`. `tools/check_tests.py` ejecuta la suite con un gancho de auditoría que rechaza escrituras Python fuera de VED-SYNC. Comprueba aperturas para escritura y operaciones de modificación del proceso principal, incluidos borrado de fixtures y enlaces; no constituye un sandbox general ni hereda auditoría en subprocesos. Los subprocesos CLI utilizan configuraciones ficticias. Las pruebas Git reales crean y, cuando corresponde, preparan exclusivamente repositorios desechables dentro de `.test-runs`; se comprueba el rechazo del padre y que sus metadatos ficticios permanecen intactos. El registro cuenta las operaciones auditadas.

No se han usado repositorios reales ni modificado otros proyectos, Windows, montajes, particiones o arranque. No se ha utilizado VirtualBox. No se ha instalado ni activado inicio automático. No se han ejecutado commits ni publicaciones. Los remotos usados en pruebas se configuran solo en repositorios ficticios y no se conectan a GitHub. Simulación sigue siendo el modo predeterminado. Los scripts Git existentes se conservan: requieren autorización explícita para escritura y rechazan el repositorio padre; `git.sh` se comprueba sintácticamente, `git.bat` requiere prueba nativa Windows. No se encontraron convenciones equivalentes en la inspección previa.

## Pendientes antes de producción

- Ejecutar suite y comprobar GUI en Windows y Ubuntu con sesión gráfica; verificar Python 3.10 y posteriores soportados.
- Ensayar USB, sistemas de archivos sin enlaces duros y unidades de red con datos ficticios; probar desconexión durante E/S y nombres incompatibles.
- Medir CPU, memoria y E/S a gran escala; evaluar watchers nativos si el sondeo resulta costoso.
- Endurecer recuperación de copias parciales, concurrencia externa, bloqueos tras cierre abrupto y pérdidas de alimentación.
- Validar arranque de sesión sin acceso a repositorios reales y scripts Git Windows en entorno desechable autorizado.
- Implementar catalogación y detección de duplicados para FOTOS si se activa esa fase.

No se considera VED-SYNC terminado mientras sigan estos requisitos sin implementar o comprobar.


## Ampliación: consola, log, tiempos y recuperación .original

Motor existente conservado. Se incorpora `ved_sync/telemetry.py` con tres componentes separados: salida de consola limitada, auditoría incremental y estimación persistente. Las 51 pruebas anteriores siguen formando parte de la suite completa; se añaden pruebas permanentes de telemetría, CLI y recuperación.

| Requisito | Estado | Evidencia y alcance |
|---|---|---|
| Consola en tiempo real y dos niveles de salida | Implementado y probado | CLI conserva JSON en stdout y envía progreso a stderr. `--quiet` mantiene log/CSV. Eventos de detección, comparación, sincronización, respaldo, recuperación, estados y problemas. Prueba CLI en subproceso. |
| Barras por archivo/proyecto, porcentaje, bytes y ETA | Implementado y probado con reloj controlado | Barra conjunta por transacción incluye escritura, hashes, respaldos y confirmación. Global reserva comprobación final/guardado. Pruebas niegan 100 % antes de confirmación, ante errores o conflictos. Si no hay base fiable, ETA indeterminada; inventario indeterminado sin denominador. Visual nativa de terminal Windows pendiente. |
| Evitar mensajes repetitivos y coste por bloque | Implementado; presupuesto de rendimiento pendiente | Actualizaciones acotadas a 250 ms y consola redirigida a 1 s. Reutilización de línea TTY y limitación de avisos repetidos. Prueba con 1000 avances sin generar 1000 líneas. El log conserva eventos de fases y transacciones. |
| Log detallado persistente y tail -f | Implementado y probado | `state_dir/operaciones.jsonl`, append incremental, vaciados periódicos y en límites de fase, sin reescribir el historial. Prueba lee un evento de error antes de cerrar y comprueba conservación entre ejecuciones. |
| Auditoría cronológica de sustituciones/recuperaciones | Implementado y probado | ID de ejecución y transacción, referencias de rutas, hashes anterior/nuevo, intención con fsync antes de modificar, confirmación duradera después de verificar destino. Fallos/interrupciones dejan transacción sin confirmar. Se prueba rechazo de sustitución cuando falla la escritura de intención. |
| No guardar credenciales/secretos en log | Implementado y probado para campos emitidos | Lista de campos permitidos; sin contenido, configuración ni texto libre de excepciones. Rutas/identificadores referenciados por digest abreviado. Prueba inyecta URL/contraseña ficticias y verifica su ausencia. El JSON de salida conserva la API previa y no forma parte del log filtrado. |
| tiempo.csv con medidas reales y límite | Implementado y probado | Operación, bytes, duración monotónica, velocidad, tipo de dispositivo, resultado y fecha UTC. Escritura incremental con descriptor reutilizado durante el ciclo; compactación atómica al límite, 1000 por defecto. Pruebas de reapertura, filas inválidas y límite de 10 tras 35 registros. |
| ETA histórica y ajuste dinámico | Implementado y probado | Al menos tres muestras válidas por operación/tipo; mediana y filtro ×4, ponderación reciente, exclusión de fallos/interrupciones y muestras demasiado cortas. Ajuste por velocidad observada tras 0,5 s y 256 KiB. ETA global basada en historial propio del proyecto. No interviene en decisiones de contenido. |
| .original antes de sustituciones | Implementado y probado | Respaldo `versions/<sha256>.original`, además del archivo legado por compatibilidad. Verificación completa antes de sustituir. Un respaldo ya existente corrupto bloquea la sustitución. No se borran versiones. Ambos archivos pueden duplicar espacio de cada versión única. |
| Verificación estricta antes de cualquier recuperación | Implementado y probado | Recuperación manual por repositorio/ruta/hash histórico con `--recover`, simulación predeterminada. SHA-256 sin caché del `.original` antes de tocar destino, revalidación durante copia y protección del contenido reemplazado. También la restauración automática de un archivo conocido ausente genera/reutiliza y verifica `.original` antes de escribir. |
| Recuperación ante respaldos malos o cambiantes | Implementado y probado | Rechazo de `.original` corrupto, ausente, enlazado o cambiado después de validar, sin recurrir al archivo legado. Ruta insegura/hash ajeno rechazados. Verificados respaldo corrupto y recuperación de archivo ausente, tanto explícita como automática. |
| Interrupciones, reintento y bloqueo | Comprobado para interrupciones capturadas | KeyboardInterrupt durante copia deja destino sin publicar, registra tiempos interrumpidos/transacción no confirmada, retira temporal/bloqueo y permite reintentar. Fallo de guardado impide 100 % global. Cortes físicos, escrituras externas y reanudación por bloques siguen pendientes. |
| Seguridad de pruebas | Comprobada con el guardia de auditoría Python | Fixtures en `.test-runs`; sin repositorios reales, particiones Windows, otros proyectos ni cambios del sistema. Los subprocesos CLI se mantienen en fixtures y no heredan el gancho Python. Pruebas adicionales impiden descubrir el directorio de control como repositorio y rechazan logs/CSV enlazados sin escribir sus destinos. Sin commits ni publicación. |

### Verificación de esta ampliación

El registro completo y el contador del control de escrituras están en [RESULTADOS_PRUEBAS.txt](docs/RESULTADOS_PRUEBAS.txt). El comando reproducible es:

```bash
python3 tools/check_tests.py
python3 -m compileall -q ved_sync tests tools
bash -n git.sh
```

**Resultado final comprobado: 90 pruebas superadas en 20,480 segundos, con 7.538 operaciones de escritura Python verificadas dentro de VED-SYNC.** Python 3.14.4 en Linux. Compilación Python y sintaxis Bash: salida 0 en esta ampliación.

### Rendimiento medido y límites

Medición reproducible: `python3 tools/benchmark_telemetry.py`. Tres repeticiones alternadas por variante, archivo de 16 MiB y tres repositorios ficticios. La referencia suprime telemetría mediante mocks solo en esa herramienta, conservando las operaciones del motor; no es una opción de producción. Incluye E/S real y fsync, excluye GUI y red.

Se conservan las dos mediciones: [inicial](docs/RESULTADOS_RENDIMIENTO_INICIAL.json) y [posterior a optimizar vaciados](docs/RESULTADOS_RENDIMIENTO.json). La inicial mostró medianas de 4,986 s con auditoría y 2,207 s de referencia (+125,87 %). La segunda mostró 6,185 s y 8,621 s respectivamente (−28,25 %), con muestras individuales entre 0,448 y 18,532 s. **La variabilidad impide atribuir esas diferencias a la telemetría o certificar que su coste sea despreciable.** No se presenta una mejora de rendimiento como demostrada.

Sí se comprueban límites de emisión por tiempo, escrituras incrementales, reutilización del descriptor CSV durante cada ciclo y compactación acotada. Se han eliminado fsync redundantes al iniciar una transacción y para el último dibujo de progreso; se conservan los de intención, confirmación y cierre cronológico. Queda pendiente medir un presupuesto estable de CPU/E/S en cada dispositivo y con muchos archivos pequeños. No se reduce la protección de datos para obtener mejores tiempos.

### Documentación y pendientes que se mantienen

Procedimiento, formato de salida, ETA, privacidad, publicación y recuperación: [SALIDAS_Y_RECUPERACION.md](docs/SALIDAS_Y_RECUPERACION.md), README e instalación actualizados. Los artefactos de log, tiempos y `.original` están excluidos de Git; los `.original` también quedan excluidos del contenido sincronizado mediante una lista explícita de sufijos internos.

La GUI sigue con sus indicadores previos y no recibe barras en esta fase. La salida combinada puede envolverse en terminales estrechas; su apariencia Windows/Ubuntu nativa requiere comprobación manual. El log de auditoría es persistente y no se poda automáticamente; solo `tiempo.csv` tiene límite. No se garantiza resistencia del log a manipulación ni recuperación de una última línea incompleta tras un cierre forzado. No hay transacción global entre repositorios ni garantías frente a pérdida de alimentación.

**VED-SYNC continúa en desarrollo.** Se mantienen los pendientes generales anteriores, incluida validación nativa de Windows/GUI/USB/red, presupuesto de rendimiento, concurrencia externa y recuperación física ante cortes.


## Git y lanzadores exclusivos de VED-SYNC

`git.sh`, `git.bat`, `run.sh` y `run.bat` residen en la raíz de **VED-SYNC**. El resultado final no deja scripts nuevos ni cambios de contenido en SRC-VED fuera de este proyecto. Se comprobó que el `.gitignore` del padre conserva sus 255 bytes originales.

### Git

Se inspeccionó el BAT existente de VED-SYNC. Para mantener equivalencia de revisiones y autorizaciones, la entrada del BAT se adaptó al controlador común `git_control.py`, compartido con Bash. Conserva las operaciones anteriores de status, diff, log, init, add, commit, remote y push; incorpora fetch y pull seguro. Esta adaptación fue necesaria para aplicar las mismas comprobaciones de rama, cambios y raíz en ambos sistemas, y elimina el límite anterior de siete argumentos del BAT.

El controlador exige `.git` propio y verifica la raíz con Git. Nunca usa el Git de SRC-VED ni el de otro padre. Se eliminan variables de entorno que podrían redirigir el directorio Git o índice. Antes de escribir muestra rama, estado y cambios preparados/sin preparar. Un archivo ya versionado pero ahora excluido bloquea escrituras hasta revisión manual; no se retira del índice automáticamente.

`./git.sh` o `.\git.bat` muestran un menú en una terminal. Fuera de terminal, sin argumentos solo muestran el estado. El menú exige confirmar cada operación concreta con `AUTORIZAR` después de revisar sus cambios. Los subcomandos requieren `--autorizar`; preparar, confirmar y publicar no se encadenan. Pull requiere árbol limpio, seguimiento y `--ff-only`. Push se limita a la rama actual con destino explícito; se bloquean forzado y borrado. Ambos scripts utilizan el mismo `.git/config` del proyecto; no se ha inventado ni configurado un remoto GitHub.

Las exclusiones propias de VED-SYNC cubren identificadores, logs, tiempo.csv, temporales, .original, estados, bloqueos y versiones internas. En la fase anterior, `git check-ignore` quedó omitida porque Git no estaba instalado. La revalidación posterior con Git real figura al final de esta auditoría: esa omisión ya está resuelta. No se han ejecutado inicializaciones, staging, commits, pushes ni consultas sobre repositorios reales.

Resultado histórico anterior: 23 casos Git, 22 superados y 1 omitido; junto a CLI, 30 casos con 1 omitido. La revalidación posterior amplía este conjunto y supera la comprobación que faltaba. Los casos que simulan commit/push utilizan exclusivamente un ejecutable Git ficticio dentro de `.test-runs`. Se comprueban menú, cancelación, orden de revisión/autorización, errores, rutas con espacios, HEAD separado, seguimiento, entorno y rechazo del repositorio padre. No validan autenticación o conectividad GitHub reales. La ejecución nativa BAT queda pendiente.

### Lanzadores del sincronizador

`run.sh` y `run.bat` arrancan el mismo módulo `ved_sync` con `--watch`, en simulación por defecto y con la configuración ficticia de ejemplo. Los argumentos se reenvían conservando espacios. `--apply` es explícito. La nueva opción `--once` realiza una comprobación y termina incluso con vigilancia activada; no se combina con GUI.

Cinco pruebas superadas comprueban arranque desde otro directorio, argumentos/rutas con espacios, ayuda sin sincronizar, simulación que no copia contenido ni crea IDs en repositorios y aplicación explícita sobre tres repositorios ficticios. El BAT se revisa estructuralmente y requiere validación Windows. Los lanzadores no instalan ni activan inicio de sesión automático.

### Resultados históricos de la fase de creación de scripts

```text
python3 -m unittest tests.test_git_control tests.test_cli -v
Ran 30 tests in 9.898s
OK (skipped=1)

python3 -m unittest tests.test_launchers -v
Ran 5 tests in 0.495s
OK
Repetición para investigar aviso del entorno: 5 pruebas, 0.465s, OK; salida 0.

python3 tools/check_tests.py
Ran 118 tests in 37.108s
OK (skipped=1)
Operaciones Python de escritura verificadas dentro de VED-SYNC: 8224
```

Los registros detallados se conservan en [RESULTADOS_PRUEBAS_GIT.txt](docs/RESULTADOS_PRUEBAS_GIT.txt), [RESULTADOS_PRUEBAS_ARRANQUE.txt](docs/RESULTADOS_PRUEBAS_ARRANQUE.txt) y [RESULTADOS_PRUEBAS.txt](docs/RESULTADOS_PRUEBAS.txt). Instrucciones: [GIT.md](docs/GIT.md) y [ARRANQUE.md](docs/ARRANQUE.md).

Durante algunas llamadas del entorno de ejecución apareció `Failed to create stream fd: Operation not permitted`, fuera del registro de unittest y con código de salida 0 en pruebas correctas. La repetición directa de los cinco casos de arranque terminó sin el aviso y con éxito. No se ha identificado su causa exacta ni se presenta como fallo del motor.

`bash -n git.sh`, `bash -n run.sh` y la compilación Python terminaron con salida 0 al cerrar esta fase. La ausencia de Git de aquella fase queda resuelta por la revalidación posterior. Permanecen pendientes la comprobación de repositorios reales (excluidos por instrucción), autenticación y BAT nativo en Windows. No se declara terminado VED-SYNC ni se retiran los pendientes anteriores.


## Revalidación con Git real — 2026-11-11

Git está disponible en `/usr/bin/git`, versión **2.53.0**. Se repitió la comprobación `test_git_check_ignore_in_disposable_repository`, anteriormente omitida: ahora pasa con Git real. La ausencia de Git deja de ser un impedimento para estas pruebas locales. Python: 3.14.4; sistema de ejecución: Linux.

### Resultados actuales

```text
python3 -m unittest tests.test_git_control tests.test_cli -v
Ran 36 tests in 11.052s
OK

python3 tools/check_tests.py
Ran 124 tests in 38.914s
OK
Operaciones Python de escritura verificadas dentro de VED-SYNC: 8517

bash -n git.sh
Salida 0

python3 -m compileall -q tests/test_git_control.py git_control.py
Salida 0
```

**Todas las pruebas de esta ejecución pasan; ninguna queda omitida.** Esto describe la suite ejecutada en Linux, no una validación nativa de Windows. Registros completos actualizados: [RESULTADOS_PRUEBAS_GIT.txt](docs/RESULTADOS_PRUEBAS_GIT.txt) y [RESULTADOS_PRUEBAS.txt](docs/RESULTADOS_PRUEBAS.txt).

Se incorporan seis pruebas permanentes con Git real en `RealGitScriptTests`:

1. Estado, rama `pruebas` y diferencias desde otro directorio, sin alterar metadatos Git del proyecto ficticio.
2. Add explícito dentro del fixture: prepara contenido permitido y excluye IDs, logs, tiempo.csv, temporales, `.original`, estados, bloqueos y versiones; no crea commits.
3. Rechazo de Git del padre cuando el proyecto ficticio no tiene `.git` propio.
4. Rechazo de operaciones sin autorización, manteniendo índice, configuración y HEAD intactos.
5. Cancelación del menú sin preparar contenido ni crear commits.
6. Equivalencia entre Bash y el controlador usado por ambas rutas del BAT: mismo estado, misma salida/código de retorno y mismo remoto ficticio configurado localmente, sin conexión.

### Equivalencia de los scripts

| Aspecto | Evidencia actual | Alcance |
|---|---|---|
| Controlador y funciones | `git.sh` y las rutas `py -3`/`python` de `git.bat` invocan `git_control.py` con todos los argumentos | Verificado en código y pruebas estructurales; no hay dos implementaciones divergentes. |
| Funciones compartidas | Menú, status, diff, log, init, fetch, pull, add, commit, push y remote | Los permisos, opciones y bloqueos se resuelven en el mismo controlador. |
| Raíz del proyecto | Rutas relativas al script y verificación de `.git` propio | Con Git real se rechaza el padre y se conserva su metadata ficticia. |
| Rama, estado y diferencias | Git real en una raíz desechable con espacios | La rama sin commits se reconoce y el índice no cambia al consultar. |
| Exclusiones | `git check-ignore` real y add real solo dentro del fixture | Antes omitido; ahora comprobado sin omisiones. |
| Autorización y menú | Pruebas reales de cancelación y falta de autorización, además de la batería simulada | No se prepara, confirma o publica por defecto. |
| Commit/push y actualización segura | Se conservan pruebas con Git simulado de operaciones, avance rápido, errores y push limitado | No se ejecutan commits, fetch, pull ni push reales en esta revalidación. |
| Mismo remoto | Bash y el controlador del BAT leen la misma URL ficticia del mismo `.git/config` | Sin contacto con GitHub ni uso de credenciales; no acredita conectividad remota. |
| Ejecución nativa Windows | No hay `cmd.exe` en este entorno | Pendiente; no se afirma equivalencia de ejecución de CMD/Windows basándose solo en inspección. |

No fue necesario modificar `git.sh`, `git.bat` ni `git_control.py`. Se comprobaron sus hashes SHA-256 antes y después:

```text
git.sh          49fdb89d28be129eaa73f2c2cf1732bfeb85e8d849f7e84bf1b7b18b969fa437
git.bat         06c685e9c5ad580d5fb763f67215a09c20521ab879285173407a0b20bf8729af
git_control.py  1b667c7bc195a510758dd473b05331b2c07aede636cad81fc6b2381a40034200
```

### Seguridad y límites

Toda creación de metadatos Git y preparación de archivos ocurre exclusivamente en carpetas temporales dentro de `VED-SYNC/.test-runs`. Los fixtures inicializan un padre y un proyecto propios y se eliminan al finalizar; comprueban por SHA-256 que los metadatos del padre ficticio y su archivo testigo permanecen intactos. No se inicializa ni se prepara contenido en VED-SYNC real, SRC-VED u otros proyectos.

Las pruebas reales no heredan variables `GIT_*` del llamante; deshabilitan protocolos de transporte y solicitudes de credenciales, usan plantillas vacías y no hacen operaciones de red. El remoto de prueba usa `example.invalid` y se consulta solo mediante configuración local/get-url. Los subprocesos Git no heredan el gancho de auditoría Python; sus rutas y entornos son explícitos y los fixtures verifican el aislamiento. No se ejecutan commits ni publicaciones reales, no se lee Windows ni se copian credenciales.

La consulta sobre autorizar desde el móvil no cambia el alcance: estas pruebas no necesitan autenticación. `gh` no está instalado aquí; no se ha iniciado ninguna solicitud OAuth ni se han escrito credenciales. Autenticación GitHub, conectividad remota y ejecución nativa Windows siguen pendientes. Los demás pendientes generales de VED-SYNC se mantienen.


## Ayuda y comentarios de los lanzadores

Alcance de esta revisión: documentar el comportamiento existente en los comentarios de `run.sh`, `run.bat`, `git.sh` y `git.bat`, y ampliar la ayuda compartida del sincronizador y del controlador Git. No se añade creación de repositorios GitHub ni se ejecuta publicación alguna. No cambian las órdenes de arranque de los BAT; sus modificaciones son comentarios.

La ayuda de arranque incluye simulación predeterminada, tres raíces ficticias, aplicación explícita, ejemplos de vigilancia y de una pasada con `--once`, rutas de configuración, logs/tiempo.csv y condiciones de comprobación. Precisa que salida 0 no basta si hay raíces grises, y que antes de continuar deben revisarse todos los estados y `simulation: false`.

La ayuda Git incluye funciones, autorizaciones, ruta exclusiva del proyecto, ejemplos manuales de primer envío y códigos de error. Aclara que `init` es local, que el repositorio GitHub debe existir antes del primer push y que mostrar ejemplos no los ejecuta ni activa servicios. GitHub y la autenticación no se han utilizado durante esta revisión.

Verificación dirigida después del cambio:

```text
bash -n run.sh
bash -n git.sh
Salidas 0

./run.sh --help
./git.sh --help
Salidas 0, instrucciones en español

python3 -m compileall -q ved_sync git_control.py tests
Salida 0

python3 -m unittest tests.test_launchers tests.test_git_control tests.test_cli -v
Ran 44 tests in 12.075s
OK
```

Registro: [RESULTADOS_PRUEBAS_AYUDA.txt](docs/RESULTADOS_PRUEBAS_AYUDA.txt). Se refuerza la prueba de ayuda del lanzador y se añaden tres casos: ayuda junto a `--apply` sin copias/IDs/estado, ayuda Git explicativa sin invocar Git, y ayuda Git sin repositorio aunque se incluyan argumentos de publicación. Las pruebas restantes de este conjunto usan exclusivamente fixtures locales y, cuando simulan commit/push, Git ficticio. No se modifican repositorios reales ni se publican archivos.

La última suite completa registrada es la ejecución anterior de 124 pruebas. Esta revisión de ayuda se valida con los 44 casos dirigidos indicados; no se presenta como una nueva ejecución completa. La ejecución nativa de los BAT en Windows sigue pendiente. Guías: [ARRANQUE.md](docs/ARRANQUE.md) y [GIT.md](docs/GIT.md).


## Consola fija: cabecera y barra, sin desplazamiento

Cambio solicitado: una cabecera `<semáforo> <ubicación> <estado> PROYECTO completados/total`, con la barra en la fila inferior y ambas actualizadas en las mismas posiciones. ⌛ representa trabajo, ✓ final correcto y ! final con problemas. Hay equivalentes ASCII si la codificación no admite esos símbolos. Los colores mantienen su nombre legible. La simulación lleva `[SIM]`.

Se sustituye el listado de mensajes repetitivos por un bloque de dos filas ANSI/VT limitado por tiempo y ancho de terminal. La barra global mantiene la reserva para verificación y confirmación; el detalle completo permanece en el log. El contador suma rutas relativas únicas, excluye archivos internos y vuelve a comprobar sus resultados en el escaneo final. La ubicación refleja el repositorio en curso y vuelve a la carpeta del proyecto al concluir. La vista en terminal no imprime los bloques JSON entre ciclos; `--json` permite solicitarlos, y stdout redirigido o `--quiet` conservan ese informe.

Pruebas aisladas de esta revisión, sin arrancar el sincronizador:

```text
python3 -m compileall -q ved_sync tests
Salida 0

python3 -m unittest tests.test_console tests.test_telemetry -v
Ran 28 tests in 0.347s
OK
```

Registro: [RESULTADOS_PRUEBAS_CONSOLA.txt](docs/RESULTADOS_PRUEBAS_CONSOLA.txt). Se comprueban dos filas estables mediante interpretación de cursor a lo largo de avances y ciclos, iconos, final correcto, error/gris, longitudes Unicode sin envoltura, contadores únicos, salida redirigida, modos JSON/quiet y restauración del modo de terminal. Las pruebas de enrutado sustituyen Engine por un objeto inocuo: no copian ni sincronizan datos. Los tests de telemetría solo utilizan eventos ficticios y archivos de control temporales.

Se hicieron pruebas de integración sobre fixtures antes de que el usuario pidiera ejecutar él mismo el programa. Después de esa instrucción se respetó el límite: solo sintaxis y pruebas simuladas, sin arrancar run.sh ni ejecutar más sincronizaciones. No se ha ejecutado la suite completa ni la integración real tras el cambio final; la comprobación visual y la integración de arranque quedan pendientes de la ejecución del usuario. Windows nativo continúa sin validar. No hay GitHub, autenticación, suscripciones, commits ni publicaciones en esta revisión.


## Configuración local no propagable — 2026-11-12

Se incorpora el nombre explícito `.ved-sync-config.json` a la lista de archivos internos y a `.gitignore`. Se añade `.git` a la exclusión del motor para directorios y archivos de worktree. El mismo filtro se aplica al escaneo, al recorrido del historial y al control de destinos de copia. No se ha cambiado la lógica de arranque ni se han autorizado nuevas raíces para escritura.

Se guarda dentro de VED-SYNC un borrador privado con las ubicaciones aportadas por el usuario y la ruta USB pendiente (`null`). La ubicación Ubuntu se limita a SRC-VED, no al Escritorio entero. No se han leído esas raíces reales ni escrito en Windows. No se ha configurado `/dev/usbb` como directorio: falta la ruta montada. El borrador no es ejecutable con el validador actual y tampoco resuelve aún las restricciones de SRC-VED completo ni la superposición del estado; no debe tratarse como una configuración de producción lista.

Validación realizada sin arrancar el sincronizador:

```text
Validación JSON y aserciones sobre ubicaciones del borrador: correctas.
python3 -m unittest tests.test_internal_files -v
Ran 3 tests in 0.005s
OK
```

Registro: [RESULTADOS_PRUEBAS_CONFIG_LOCAL.txt](docs/RESULTADOS_PRUEBAS_CONFIG_LOCAL.txt). Se escanean tres repositorios ficticios en lectura, con configuraciones locales distintas, metadatos `.git` en directorio/archivo y configuración anidada. Solo se inspeccionan los archivos de contenido previstos. La prueba de copia se detiene en su guardia antes de escritura y usa un origen inexistente. No se invocan inicialización del motor, `run_once`, lanzadores ni comandos Git. Se conservan los ficheros privados de prueba y los límites anteriores sobre ejecución manual del usuario.

La exclusión Git se comprueba en esta revisión mediante su regla literal; no se han vuelto a ejecutar Git ni la suite de integración. La sincronización completa de SRC-VED y la ejecución visual continúan pendientes de configuración y autorización del usuario. Documentación: [CONFIGURACION_LOCAL.md](docs/CONFIGURACION_LOCAL.md).
# USB opcional preparado (2026-11-12)

El repositorio 3 del JSON local admite rutas vacías y descubrimiento mediante
`mounted_subdirectory`, raíces de búsqueda y UUID v4 registrado. Solo se consideran
volúmenes ya montados, sin seguir enlaces; UUID ausente o dispositivo desconectado
mantienen gris. Las coincidencias duplicadas bloquean la selección en rojo.
Se reconoce el repositorio tras cambiar el nombre del montaje y reconectarlo.
No se monta ningún dispositivo, se inicia ningún servicio ni se activa el JSON local.

Validación: `python3 -m unittest tests.test_usb_discovery tests.test_internal_files -v`:
10 pruebas correctas; salida en `docs/RESULTADOS_PRUEBAS_USB.txt`. Directorios
ficticios dentro de VED-SYNC y puntos de montaje simulados. No se ejecutó ningún
ciclo de sincronización ni los lanzadores; no se accedió a USB o repositorios reales.

Pendiente: registrar el UUID del USB elegido, validar integración ejecutada por el
usuario y detección nativa en Windows. La configuración SRC-VED completa conserva
los bloqueos anteriores de Windows, otros proyectos y solapamiento del control.
Estas pruebas específicas no equivalen a una suite completa ni a validación real.

# Origen de solo lectura y recuperación desde Windows (2026-11-12)

Se añadió `read_only: true` por repositorio: no crea identificadores, no recibe
copias y rechaza recuperaciones explícitas hacia ese origen. El bloqueo de escritura
en /mnt/windows sigue vigente. Las importaciones desde ese origen hacia archivos
ausentes crean y verifican un .original antes de recuperar el contenido.

Suite completa: `python3 -m unittest discover -v`: 156 pruebas, 53.062 s, OK.
Resultado en `docs/RESULTADOS_PRUEBAS_RECUPERACION_WINDOWS.txt`. Incluye cinco casos
nuevos de origen de solo lectura y protección de respaldos. Se ejecutó antes de
pasar a la revisión de datos reales; no se ha ejecutado ninguna recuperación real.
Esta ejecución no utilizó el ejecutor adicional de auditoría de escrituras Python.

Se preparó un JSON privado `.ved-sync-recuperacion.json` y una carpeta vacía
`.ved-sync-recuperados/windows` dentro del proyecto; no se activaron. Tras la
indicación del usuario de trabajar con datos reales, se comprobó únicamente en
lectura la lista de entradas de Windows y su existencia en Ubuntu. Pendiente
confirmar destino y alcance antes de escribir en otros directorios de SRC-VED.

# Dirección de copia en consola (2026-11-12)

La terminal muestra tres filas fijas: dirección según las etiquetas de origen y
destino, estado y barra de progreso. Cada copia actualiza la dirección; antes de
seleccionar archivos indica comparación y al finalizar conserva la última dirección.
Los nombres de dirección son datos transitorios de consola y no se añaden al log.
La salida sin control de cursor conserva una instantánea final por ciclo.

Validación sin ejecutar el sincronizador: 30 pruebas de consola y telemetría
correctas mediante eventos y motor simulado. Resultado guardado en
`docs/RESULTADOS_PRUEBAS_DIRECCION.txt`. Se comprueba cambio de sentido en la misma
fila, tres posiciones estables, limpieza de controles, límites de ancho y cadencia.
No se ejecutaron los lanzadores ni se copiaron proyectos reales. La configuración
real Windows → Ubuntu sigue pendiente de preparación; este cambio solo adapta
la presentación y emite la dirección al seleccionar una copia del motor.

# Recuperación autoritativa preparada para ejecución manual (2026-11-12)

Windows → Ubuntu: `authoritative_source` exige un origen configurado de solo
lectura. Sus archivos tienen prioridad independientemente de las fechas y del
historial previo de Ubuntu. Antes de recuperar se verifica el .original del
origen y antes de sustituir se conserva y verifica la versión anterior del destino.
Los archivos exclusivos de Ubuntu se conservan y notifican como pendientes.

`--restore-projects` habilita expresamente un único destino: el padre del motor.
Exige dos repositorios y origen autoritativo de solo lectura. Excluye VED-SYNC
en ambas raíces y permite conservar el motor actual de Ubuntu. Sin esta opción
siguen vigentes los bloqueos de los demás proyectos; /mnt/windows permanece
prohibido para escritura. La configuración privada `.ved-sync-recuperacion.json`
apunta al Windows identificado y al padre relativo `..`; no está activada por defecto.
Procedimiento y comando en `docs/RECUPERAR_WINDOWS.md` y ayuda `--help`.

Resultado final: `python3 tools/check_tests.py`: 163 pruebas, 45.604 s, OK;
9316 operaciones Python de escritura comprobadas dentro de VED-SYNC. El control
de auditoría no se hereda a subprocesos; estos usan los repositorios ficticios de
sus fixtures. Resultado completo en `docs/RESULTADOS_PRUEBAS_RESTAURACION_SRC_VED.txt`.
También pasan la compilación de los módulos cambiados y `bash -n run.sh`.
La primera ejecución detectó expectativas de pruebas anteriores a la pantalla de
tres filas y una fixture sin la nueva opción; se corrigieron y se repitió la suite.

No se ejecutó el sincronizador sobre repositorios reales, ningún lanzador real ni
operaciones Git sobre los proyectos del usuario. Solo se inspeccionó en lectura la
lista de entradas Windows/Ubuntu en el trabajo previo. La ejecución y comprobación
visual reales quedan en manos del usuario. Compatibilidad nativa de Windows,
validación con USB real y demás requisitos previamente pendientes siguen sin
declararse completos. VED-SYNC no se declara terminado.

# Escritura remota condicionada (2026-11-12)

Nuevo `write_policy: "if_possible"` por repositorio: los rechazos EACCES, EPERM y
EROFS durante una copia se registran como `write_unavailable`, se mantienen
pendientes y no impiden actualizar los otros destinos. Si la escritura se permite
en otro ciclo, el motor puede completarla. Conflictos, verificación y demás errores
mantienen sus protecciones. No se fuerza ningún permiso ni montaje y una copia
desactualizada no se presenta en verde. `read_only: true` evita cualquier intento
de escritura o creación de identidad en esa raíz.

Resultado: `python3 tools/check_tests.py`: 167 pruebas, 48.215 s, OK;
9554 operaciones Python de escritura verificadas dentro de VED-SYNC, con la
limitación documentada de que el hook no se hereda a subprocesos. Cuatro pruebas
nuevas verifican rechazos de permisos/solo lectura, continuidad del destino local,
escritura remota disponible, errores de integridad y validación de la política.
Salida: `docs/RESULTADOS_PRUEBAS_ESCRITURA_OPCIONAL.txt`.

No se ejecutó sincronización real. La recuperación actual mantiene Windows como
referencia y solo lectura. El objetivo habitual sigue siendo multidireccional y
el mismo contenido desde ambos arranques del mismo ordenador; no debe conservar
una prioridad fija de Windows después de la recuperación inicial. La configuración
operativa futura, validación nativa de Windows y verificación real siguen pendientes.

# Puntos de control y reanudación (2026-11-12)

En la nueva ejecución manual se identificó además FileNotFoundError durante el
escaneo del destino Ubuntu (repository_ref del identificador `recuperados`).
La fase posterior de verificación no implica que se haya completado la recuperación:
el escaneo fallido no se incorpora al inventario de destinos. No se atribuye este
error a los permisos de Windows ni se conoce el archivo concreto con el log actual.

La interrupción real notificada por el usuario terminó con KeyboardInterrupt y
416 transacciones confirmadas, pero sin state.json: antes se guardaba únicamente
al concluir el ciclo. Se corrige ese límite mediante guardado atómico periódico
de caché e historial entre archivos y guardado adicional al gestionar Ctrl+C.
El intervalo mínimo entre guardados es 30 segundos; no garantiza una latencia
máxima si un archivo o un guardado tarda más. Solo se guardan hashes completados
y observaciones confirmadas; el archivo interrumpido no se declara completado.

La reanudación vuelve a enumerar y comparar; no restaura ciegamente un cursor ni
el porcentaje anterior. Reutiliza hashes válidos y no vuelve a copiar contenido
que ya coincide. Mantiene la comprobación de metadatos y caducidad de integridad.
No puede reconstruir retroactivamente la caché que la versión anterior no guardó.

Suite completa: 172 pruebas, 49.846 s, OK; 9823 operaciones Python de escritura
comprobadas dentro de VED-SYNC (el hook no se hereda a subprocesos). Salida en
`docs/RESULTADOS_PRUEBAS_REANUDACION.txt`. Cinco pruebas adicionales de puntos de
control pasan también tras ajustar que el intervalo cuente desde el final del
guardado: 0.387 s, salida en `docs/RESULTADOS_PRUEBAS_CHECKPOINT_FINAL.txt`.
Se prueba interrupción durante comparación y copia, reutilización de caché,
no repetición de copias completadas, simulación y fallo del guardado al interrumpir.

El agente no ejecutó la recuperación real. Solo leyó el registro de la ejecución
que el usuario mantiene activa. La fase verification corresponde al 85 por ciento;
el semáforo rojo no demuestra por sí solo una detención. Las mejoras del código
se aplican al arrancar un proceso nuevo, no al que ya estaba ejecutándose.

# Exclusión de ZIP y hashes de publicación (2026-11-12)

Tras revisar en lectura los .gitignore de Windows y localizar archivos hashes.json
en la caché del inventario, se añadió `exclude_patterns` configurable. El JSON
privado de recuperación excluye *.zip, hashes*.json y artefactos generales de caché,
entornos, temporales, registros y credenciales. No se aplican automáticamente todas
las reglas Git: algunas excluyen documentos, imágenes o incluso código del proyecto.
Se preservan las reglas explícitas sin modificar los .gitignore consultados.

Las exclusiones se aplican antes del hash, a los elementos del historial que se
comparan y a los destinos de copia y recuperación. No generan conflictos ni copias
ficticias. Los archivos previamente presentes no se borran. Los SHA-256 internos
de VED-SYNC se mantienen separados, dentro del directorio local de control.

Ante errores de escaneo, se pasa a la consola el nombre del archivo cuando el
sistema lo proporciona, junto con el código de excepción. El registro persiste
solo su referencia, no su ruta literal. No se conoce aún la causa concreta del
FileNotFoundError de la ejecución real anterior ni se declara resuelto por filtrar.

Validación completa: `python3 tools/check_tests.py`: 177 pruebas, 37.118 s, OK;
10074 operaciones Python de escritura verificadas dentro de VED-SYNC, con la
limitación habitual de subprocesos. Salida en `docs/RESULTADOS_PRUEBAS_EXCLUSIONES.txt`.
Incluye cinco pruebas nuevas de exclusión con tres repositorios ficticios. Tras
esa ejecución se añadió y pasó una prueba de visualización del error y nombre:
`docs/RESULTADOS_PRUEBA_ERROR_VISIBLE.txt`. No cambió código funcional después
de la suite completa. No se lanzó el sincronizador sobre proyectos reales.

# Exclusiones Lean de recuperación (2026-11-12)

Tras observar ExpGrowth.olean en la ejecución del usuario se añadieron al JSON
privado `.lake`, `*.olean` y `*.ilean`. No son necesarios para recuperar fuentes;
se regeneran en el entorno de destino. Se conservan archivos .lean, manifiesto
de dependencias, configuración Lake y lean-toolchain. No se borran los existentes.
Validación: cinco pruebas de exclusiones correctas y siete comprobaciones en
memoria de los patrones reales (tres exclusiones y cuatro nombres conservados).
No se ejecutó sincronización ni se modificaron los proyectos reales. Los cambios
de configuración solo se aplican a procesos nuevos.

# Artefactos server/private y trace (2026-11-12)

La caché real se inspeccionó solo en lectura y confirmó nombres .olean.server,
.olean.private y .trace. Se añadieron `*.olean.*` y `*.trace` al JSON privado,
sin excluir nombres de fuentes que contengan server o trace. Siete comprobaciones
en memoria pasaron (cuatro exclusiones y tres fuentes conservados). No se ejecutó
la sincronización ni se borraron archivos existentes; los patrones se cargan en
el siguiente arranque.

# Exclusión .has (2026-11-12)

Se añadió `*.has` al JSON privado de recuperación por instrucción expresa del
usuario. Cuatro comprobaciones en memoria verifican la exclusión, también en
subdirectorios y mayúsculas, conservando nombres parecidos que no terminan en .has.
No se ejecutó sincronización ni se borraron archivos. Se aplica al siguiente arranque.


# Diagnóstico local de errores (2026-11-12)

Por indicación del autor, Víctor Estrada Díaz, se conservan en los eventos error
del registro local el repositorio, la ruta cuando está disponible y el mensaje
completo del sistema. Los eventos normales mantienen referencias; no se incluyen
contenidos de archivos ni configuración. EventList ya no descarta detail en errores.
La referencia 31c2bdc06b89ba86290e0627 corresponde al id recuperados (Ubuntu),
no al id windows. Esto identifica el árbol del error histórico consultado, pero
no recupera la ruta ni permite determinar su causa. Los cambios se aplican al
arrancar otro proceso; no se interrumpió ni reinició la recuperación del usuario.
Respaldos previos de los cuatro archivos modificados verificados con SHA-256 en
.ved-sync/backups/20261112-diagnostico-errores.
Validación: python3 tools/check_tests.py, 179 pruebas, 40.576 s, OK;
10086 operaciones Python de escritura verificadas dentro de VED-SYNC, con las
limitaciones de subprocesos descritas por la herramienta. Incluye regresión de
EventList a JSONL para ruta, repositorio y mensaje.

# Reducción de memoria tras SIGKILL (2026-11-12)

El autor, Víctor Estrada Díaz, aportó el registro de systemd-oomd que confirma
la terminación del grupo de terminal a las 03:09:44 por presión de memoria
(2.8G para el grupo; no implica que toda esa memoria fuera solo del motor).
Se sustituyó la carga completa del texto JSON por lectura incremental por registros,
compartiendo claves y cadenas de 64 caracteres. Se libera el estado anterior antes
de recargar, se usan Entry con slots, no se retienen registros sustituidos en jobs
y se liberan los inventarios iniciales antes de verificar. El estado histórico y
los respaldos reales no se modificaron. No se reinició la recuperación del usuario.
Respaldos previos verificados por SHA-256 en .ved-sync/backups/20261112-memoria.
Pruebas: suite completa, 182 casos, 46.647 s, OK; tras compartir cadenas de
64 caracteres, 8 pruebas dirigidas de lectura y reanudación, 0.600 s, OK.
Lectura del estado real de 219306437 bytes: 191669 entradas de historial,
198515 de caché, pico RSS 457168 KiB, 4.59 s. Solo lectura; no se registraron rutas
ni contenidos en consultas externas.
La prueba sintética de 200000 entradas en dos repositorios terminó antes de recibir
la petición de detenerla: comparación, verificación y guardado correctos;
pico RSS 597.6 MiB con límite de espacio virtual de 1024 MiB. No prueba el consumo
máximo de una recuperación real ni elimina la presión de memoria de otras apps.
El directorio temporal fue eliminado por TemporaryDirectory; se retiraron el
generador y las salidas auxiliares por petición del usuario. No se harán más
pruebas grandes ficticias. Se conservan solo pruebas pequeñas y este resumen.
El porcentaje no se restaura: se recalcula al comparar lo pendiente; las copias
ya iguales no se repiten. No se alteró el estado para aparentar otro avance.

# Inventario de trabajo en disco (2026-11-12)

Por instrucción del autor, Víctor Estrada Díaz, se continúa la corrección tras
la segunda terminación por presión de memoria. El registro aportado confirma
Firefox a las 03:49:14 (4.3G para su grupo) y terminal a las 03:49:31 (1.5G para
su grupo). No se equipara consumo de grupo con RSS exclusivo del sincronizador.

Se usa SQLite como caché de trabajo para historial, huellas e inventarios de
escaneo. Se activa siempre en restore_projects y para estados >= 8 MiB en otros
modos. El JSON sigue siendo autoritativo; conserva el esquema, historial y huellas.
Se carga bajo bloqueo sin mantener los registros completos en RAM. La exportación
es por registro, compacta y atómica, con fsync. La base de trabajo tiene nombre
fijo y se retira antes de soltar el bloqueo; tras SIGKILL se reconstruye en el
siguiente arranque bajo bloqueo. SQLite dispone de caché de páginas de 4 MiB.
Esto no limita la RAM total: listas de planificación y eventos aún están en RAM.
Se impide guardar una instancia cuyo estado está diferido sin haberlo cargado.
La recuperación explícita vuelve a escribir el registro de historial modificado
en su sección de disco antes de guardar. Se añaden PID y medidas RSS de Linux
a inicio, estado cargado, checkpoint y fin, para diagnosticar la ejecución real.

Respaldos previos verificados por SHA-256 en
.ved-sync/backups/20261112-inventario-disco. El archivo __main__.py coincide con
su respaldo; la limpieza se realiza dentro del bloqueo del motor.
Pruebas pequeñas de recorrido JSON/disco/JSON, Unicode, arranques consecutivos,
reutilización de caché, interrupción de copia, reanudación y protección del estado
diferido. La suite final completa pasa: 187 pruebas, 46.026 s, OK; 10484 operaciones
Python de escritura verificadas dentro de VED-SYNC, con la limitación documentada
de subprocesos. Salida consolidada en docs/RESULTADOS_PRUEBAS_INVENTARIO_DISCO.txt;
retiradas las salidas temporales intermedias.

Se midió solo la carga del estado real de 219306437 bytes en una base temporal
con límite de espacio virtual de 128 MiB: historial 191669 entradas, caché 198515,
pico RSS 21.7 MiB y 7.57 s. La base y el directorio temporal se retiraron al
terminar. No se ejecutó una recuperación real ni una nueva prueba grande ficticia.
La medida no garantiza el pico de todo el ciclo real ni evita la presión causada
por otras aplicaciones. El state.json real y sus temporales anteriores no se
modificaron en estas comprobaciones.
Retirado el bloqueo 75274 de la segunda ejecución terminada por oomd; respaldo SHA-256 verificado.

# FIFO persistente y limpieza de recuperación (2026-11-12)

Por instrucciones del autor, Víctor Estrada Díaz (https://estradad.es/;
https://estradad.es/licencia.php), la recuperación utiliza una cola de texto
VED-Sync.cola con origen;destino;ruta relativa y solo copias pendientes.
En esta configuración 1=recuperados, 2=windows. Las confirmaciones se conservan
en VED-Sync.historial y el índice transaccional privado .ved-sync-fifo.sqlite;
los pendientes de revisión final se gestionan por separado. La cola se publica
atómicamente y se reconstruye desde el índice tras un corte. Se confirma y retira
cada trabajo antes del siguiente; las copias publicadas sin confirmar se verifican
antes de repetirse. La revisión final descubre añadidos, cambios y ausentes.
El bloqueo POSIX se libera con la muerte del proceso, impide concurrencia y
conserva un inode estable para evitar carreras entre propietarios.

Se reconstruye una vez tras dos intentos sin avance; el contador se reinicia
al avanzar. Existe --reset-queue con --once, --restore-projects y --apply.
La reconstrucción conserva y verifica por SHA-256 el plan anterior. Sin espacio
se conservan pendientes, se para y se espera a liberar espacio. No se borra trabajo
por fallar ni se repiten reinicios automáticos sin progreso indefinidamente.
Las escrituras grandes se sincronizan y descargan de caché cada 16 MiB; las
lecturas también liberan su caché propia cuando el sistema admite posix_fadvise.

La recuperación deja de generar operaciones.jsonl y tiempo.csv; las muestras de
rendimiento quedan en RAM (1000 máximo). VED-Sync.cola.log está acotado a 4 MiB
más un segmento anterior, con actividad, errores completos, PID y medidas RSS.
Cola, historial, índice, registros y auxiliares están excluidos del sincronizador
y de Git. Setuptools incluye solo ved_sync*, sin directorios de control.

Validación: 205 pruebas completas, 71.337 s, OK; 12315 operaciones Python de
escritura verificadas dentro de VED-SYNC, con la limitación habitual de subprocesos.
Tras retirar pendientes antiguos ahora excluidos: 41 pruebas dirigidas, 29.736 s,
OK. Incluyen SIGKILL real con dos archivos pequeños durante copia, revisión y
transacción de confirmación; reanudación sin retirar el bloqueo a mano; ausencia
de recopia de confirmados y de repetición de revisiones confirmadas; FIFO, nombres
CSV, conversión a texto, archivos añadidos, edición del destino con respaldo,
respaldo corrupto, espacio insuficiente, estancamiento, reinicio manual, concurrencia,
exclusión de artefactos y ausencia de nuevos registros de operaciones/tiempos.
Se retiraron las salidas temporales de pruebas; no se añadieron pruebas grandes.

Preparación real solo desde el estado y metadatos guardados, sin leer contenidos
ni copiar: 20787 archivos conocidos, 20729 copias confirmadas y 58 pendientes;
porcentaje del trabajo de copia 82.5. Pico RSS de preparación 30.9 MiB con límite
de espacio virtual de 256 MiB. La revisión final detectará trabajos no inventariados.
El state.json real no se reescribió. El bloqueo de la ejecución terminada 79378
se respaldó con SHA-256 y se retiró antes de preparar. Los respaldos de código
están en .ved-sync/backups/20261112-cola-fifo; el cambio inicial de formato de la
cola conserva un respaldo local verificado del plan, sin registros de operaciones.

Por petición expresa se eliminaron, sin archivarlos, operaciones.jsonl, tiempo.csv,
dos temporales de estado y un temporal huérfano de respaldo: 5 archivos,
2812365309 bytes. Se conservaron todos los respaldos publicados de archivos y el
estado de reanudación. No se inició otra recuperación. Si un visor conserva abierto
un archivo eliminado, su espacio no se libera físicamente hasta cerrar ese visor.
La reanudación persistente no garantiza que el sistema operativo nunca envíe
SIGKILL por presión de memoria del conjunto de la sesión.
