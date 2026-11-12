# Consola, auditoría, estimaciones y recuperación

Todas las pruebas utilizan raíces ficticias dentro de VED-SYNC. Estos ejemplos mantienen la simulación salvo cuando se indica `--apply`. Ejecutar desde `SRC-VED/VED-SYNC`. En Windows sustituir `python3` por `py -3`.

## Dos salidas simultáneas

```bash
python3 -m ved_sync --config config/example.json
python3 -m ved_sync --config config/example.json --watch
python3 -m ved_sync --config config/example.json --quiet
```

En una terminal interactiva, stderr muestra una cabecera fija y una barra en la fila inferior. Las operaciones detalladas se registran en el log; los problemas cambian el semáforo. El JSON se obtiene con `--json`, con `--quiet` o al redirigir stdout. `--json` y `--quiet` desactivan la pantalla fija y conservan registros/tiempos. La GUI mantiene sus indicadores previos.

La cabecera tiene el formato `<semáforo> <ubicación> <⌛/✓/!> PROYECTO completados/total`; debajo permanece la barra. La terminal reescribe esas dos filas con movimientos de cursor ANSI/VT, limitados a cuatro actualizaciones por segundo salvo al finalizar. No imprime un mensaje por operación. El texto se recorta según el ancho de terminal para evitar saltos de línea. En Windows se intenta habilitar VT únicamente en la consola del proceso y se restaura su modo al cerrar; falta validación nativa. Sin soporte de terminal, se imprime solo una instantánea final de dos líneas por ciclo.

El monitor conserva progreso por archivo para escritura, SHA-256, respaldo y confirmación. La pantalla compacta muestra una barra global y añade el porcentaje/nombre de archivo cuando hay espacio; el log conserva los bytes y ETA por operación. Los bytes de trabajo representan **E/S acumulada**, no solo tamaño de archivo. La barra del proyecto reserva fases: comparación hasta 30 %, operaciones de contenido hasta 85 %, verificación final hasta 98 % y confirmación completa. Los contadores corresponden a la fase indicada; no suman tamaños de fases distintas. El trabajo planificado puede incluir respaldos que luego se reutilicen; los pesos globales son aproximados y no una predicción exacta de tiempo.

Ni un archivo ni un proyecto muestran 100 % mientras su transacción o confirmación esté pendiente. Un archivo termina después de verificar el destino y registrar su confirmación duradera; el proyecto termina después de la comprobación final, guardado de estado, escritura de tiempos y cierre cronológico duradero. Los conflictos, errores, repositorios ausentes y verificaciones imposibles impiden el 100 % global. La finalización de una fase SHA-256 no se presenta como finalización del archivo que aún se está escribiendo o respaldando.

Si se conoce el tamaño pero no una velocidad fiable, se muestra porcentaje por bytes y **ETA indeterminado**. Durante detección o inventario sin denominador conocido, también la barra es indeterminada. No se inventan segundos restantes.

## Registro cronológico

Cada proyecto escribe en su `state_dir`, separado de los repositorios:

- `operaciones.jsonl`: una estructura JSON por línea.
- `tiempo.csv`: muestras acotadas para estimación.
- `versions/<sha256>.original`: respaldos verificados.
- `versions/<sha256>`: archivo de versión conservado por compatibilidad.

Con la configuración de ejemplo:

```bash
tail -f .ved-sync/demo/operaciones.jsonl
```

PowerShell:

```powershell
Get-Content .ved-sync\demo\operaciones.jsonl -Tail 30 -Wait
```

Cada ciclo comienza limpiando automáticamente los registros de actividad anteriores
y sus rotaciones, una vez adquirido el bloqueo. El archivo activo se vacía conservando
su inode para que los visores vean el reinicio. Durante ese ciclo las entradas se
añaden incrementalmente. Se vacía el búfer al iniciar fases, ante problemas, como
máximo cada 250 ms durante actividad y al terminar. Las intenciones de modificación
y sus confirmaciones usan además `fsync`. El estado, las colas, el historial de
versiones y las muestras de tiempos se conservan para reanudar y estimar duraciones.
`tail -f` puede aplicar su propio intervalo de refresco.

Campos de auditoría: fecha UTC, identificador de ejecución, referencia de proyecto, evento, transacción, referencias de archivo/repositorio, SHA-256 esperado/calculado, resultado, estado, tipo de excepción y progreso. `transaction_intent` precede a toda sustitución o publicación de contenido; `transaction_committed` solo aparece después de verificar el destino. `transaction_unconfirmed` obliga a revisar el resultado, aunque el destino haya podido cambiar antes del fallo. Las recuperaciones añaden `recovery_verified` antes de acceder al destino y `recovery` al finalizar.

No se registran contenido de archivos, configuración completa, URLs, mensajes libres de excepciones, contraseñas ni credenciales. En el log, los nombres y rutas son referencias SHA-256 abreviadas de 24 caracteres para evitar copiar secretos incluidos en una ruta o URI. La consola muestra nombres de repositorios y archivos de forma transitoria para que se puedan reconocer; esos campos de presentación no se escriben en el log. Para correlacionar localmente una ruta con el log:

```bash
python3 -c 'from pathlib import Path; from ved_sync.telemetry import token; print(token(Path("demo/repos/uno/archivo.txt").resolve()))'
```

El informe JSON existente conserva sus rutas relativas y detalles; no debe confundirse
con el log filtrado de la ejecución actual. Las referencias no son credenciales ni una
garantía criptográfica de anonimato. Los digests y referencias permiten correlación,
no autentican el registro contra un atacante. Si se necesita conservar un log para
diagnóstico, hay que copiarlo antes de arrancar el ciclo siguiente. Un cierre forzado
puede dejar una última línea incompleta y una intención sin confirmar; no se ofrece
recuperación transaccional ante pérdida física de alimentación.

## tiempo.csv y ETA

Columnas: `operation`, `bytes`, `duration_seconds`, `bytes_per_second`, `device_type`, `result`, `executed_at`. Los intervalos se miden con reloj monotónico y las fechas se escriben en UTC. Operaciones: `sha256`, `write`, `backup`, `file`, `recovery`, `recovery_check` y `project`. Los resultados distinguen `ok`, `failed`, `interrupted` y, a nivel de proyecto, `pending`.

Cada repositorio admite `device_type`: `local`, `usb`, `network` o `unknown` (predeterminado). Es una declaración de configuración, no una detección del hardware. El proyecto completo usa `mixed` y aprende en su propio historial. No se mezclan muestras de operaciones ni tipos de dispositivo distintos para ETA por operación.

```json
{
  "timing_limit": 1000,
  "repositories": [
    {"id": "uno", "path": "../demo/repos/uno", "device_type": "local"},
    {"id": "dos", "path": "../demo/repos/dos", "device_type": "usb"}
  ]
}
```

Este fragmento se integra en un JSON con `state_dir` propio. `timing_limit` admite entre 10 y 100000 filas, con 1000 por defecto. La escritura habitual es incremental. Al alcanzar el límite, una compactación atómica conserva el 90 % más reciente y continúa añadiendo; el archivo nunca supera el límite de muestras. No se limita el historial de versiones de archivos.

La estimación necesita al menos tres muestras válidas de esa operación y tipo. Ignora resultados fallidos/interrumpidos, muestras inferiores a 4096 bytes o 5 ms, valores inválidos y velocidades fuera del intervalo mediana/4 a mediana×4. Pondera más las muestras recientes restantes. No presupone una velocidad si esos criterios no se cumplen.

Durante una operación, después de al menos medio segundo y 256 KiB procesados, incorpora velocidad observada: 70 % actual y 30 % histórica cuando existe. Sin historial, esa ventana observable puede proporcionar la primera ETA. La ETA global necesita historial válido del proyecto; combina duración histórica con avance real observado. Las estimaciones nunca intervienen en hashes, versiones, resolución de conflictos o decisiones de recuperación.

El coste de confirmación duradera puede dominar muchos archivos pequeños; no se elimina para mejorar una cifra de rendimiento. `tools/benchmark_telemetry.py` compara registros activos frente a una referencia de instrumentación suprimida mediante mocks, solo en fixtures locales. No ofrece un modo de producción sin auditoría. Las mediciones locales y sus límites están en AUDITORIA.md.

## Recuperación estricta de .original

Los `.original` se guardan fuera de los repositorios, bajo `state_dir/versions`. Se mantiene también el archivo legado por hash; esto puede duplicar el espacio de respaldo de cada versión única. El sufijo `.original`, `.ved-sync-id` y los temporales `.ved-sync-*` son internos reservados: se excluyen de sincronización y de copias de contenido en cualquier nivel. No se eliminan automáticamente.

Antes de sustituir una versión compatible, VED-SYNC crea y verifica sus respaldos. Si un `.original` existente no coincide con su SHA-256, bloquea la sustitución. Los conflictos siguen conservando las variantes en sus raíces; no se sobrescriben para resolverlos.

La restauración automática de un archivo conocido ausente también genera o reutiliza un `.original` verificado desde la versión vigente accesible. Si el respaldo existe corrupto, bloquea esa restauración sin crear el destino. Las incorporaciones iniciales y los repositorios nuevos siguen el flujo normal de copia.

Una recuperación manual es explícita, requiere un SHA-256 que pertenezca al historial de ese archivo y utiliza exclusivamente su `.original`:

```bash
python3 -m ved_sync --config config/example.json --recover dos archivo.txt SHA256_DEL_HISTORIAL
# Solo con fixtures revisados y autorización para aplicar:
python3 -m ved_sync --config config/example.json --recover dos archivo.txt SHA256_DEL_HISTORIAL --apply
```

`SHA256_DEL_HISTORIAL` se sustituye por los 64 caracteres hexadecimales reales. No admite `--watch` o `--gui` simultáneamente. Rutas ascendentes, absolutas, internas y enlaces se rechazan. No restaura automáticamente en los demás repositorios.

La lectura SHA-256 del `.original` es completa y no usa caché. Un respaldo ausente, corrupto, enlazado, desconocido o cambiado entre validación y copia impide recuperar. No se recurre al archivo legado como alternativa sin verificar. Si el destino existe, también se protege con un `.original` verificado antes de sustituirlo. Tras recuperar, los repositorios quedan pendientes de una comparación completa; no se fabrica un estado verde ni se fuerza un nuevo hash vigente.

La publicación de archivos nuevos usa enlace duro exclusivo cuando el sistema lo permite. En sistemas sin ese soporte, utiliza creación exclusiva con copia y verificación completa; una interrupción física durante esa alternativa puede dejar un archivo parcial. La interrupción capturada elimina temporales y libera el bloqueo; se prueba que un nuevo ciclo puede completar una copia interrumpida antes de publicarse. No hay reanudación por bloques, bloqueo de escritores externos ni garantía ante cortes de alimentación.
