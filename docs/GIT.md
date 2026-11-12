# Git de VED-SYNC en Ubuntu y Windows

Autor de la obra: **Víctor Estrada Díaz** — [web](https://estradad.es/) y
[licencia y condiciones](https://estradad.es/licencia.php).

Los lanzadores específicos están en **VED-SYNC/proyecto/git.sh** y
**VED-SYNC/proyecto/git.bat**. Controlan el Git de la raíz de VED-SYNC, no un
repositorio dentro de `proyecto/` ni el Git del padre SRC-VED. Ambos invocan el
controlador común `VED-SYNC/git_control.py`, con todos los argumentos y desde
cualquier directorio, incluidas rutas con espacios. Los lanzadores de la raíz
siguen disponibles y utilizan ese mismo controlador.

Desde VED-SYNC se puede entrar con `./proyecto/git.sh` en Ubuntu o
`.\proyecto\git.bat` en Windows. También se pueden ejecutar como `./git.sh` o
`.\git.bat` estando dentro de `proyecto/`. El repositorio propio y sus remotos
corresponden siempre a VED-SYNC; no se inicializa un segundo Git en `proyecto/`.

## Uso cuando el proyecto esté estable

Ubuntu, desde `SRC-VED/VED-SYNC`:

```bash
./git.sh
```

Windows, en esa misma carpeta:

```powershell
.\git.bat
```

En una terminal se abre el mismo menú en ambos sistemas:

1. **VER ESTADO**: muestra rama y cambios.
2. **SUBIR CAMBIOS**: prepara archivos, crea el commit y publica la rama actual.
3. **LIMPIEZA LOCAL**: ejecuta `limpieza.sh` en Ubuntu, cuando existe.
4. **INFORMACIÓN**: muestra proyecto y destino predeterminado.
5. **SALIR**.
6. **OPERACIONES AVANZADAS**: conserva las operaciones individuales anteriores.

La opción **2** pide el mensaje del commit y una confirmación con `s`. Muestra
el resultado de cada paso: **COMMIT CREADO** con su identificador y
**SUBIDA COMPLETADA** sólo si el push termina correctamente. Si falla el push,
indica que el commit queda conservado localmente. Al repetir la opción **2** sin
cambios nuevos, vuelve a intentar la subida sin crear un commit vacío.
Salir con **5**, **0**, Intro o cerrar la entrada no escribe nada.

Si Git todavía no conoce la identidad del usuario, la opción **2** pide su nombre
o alias y el correo del commit. Explica que identifican al autor y son visibles
en el historial, y que el correo `noreply` permite ocultar el correo personal.
Pregunta `¿Guardar y reutilizar estos datos sólo en este proyecto? [S/n]`.
Con `s` o Intro, al confirmar la operación se guardan con `git config --local`
únicamente en este proyecto, dentro de sus metadatos Git. Con `n`, se utilizan
sólo en el proceso actual, sin guardar la identidad en la configuración.
Si la identidad ya está configurada, muestra los datos que reutiliza sin volver
a pedirlos. No se cambia la configuración global. El nombre y correo seguirán
formando parte de cada commit creado en ambas modalidades.

Si todavía no existe el Git propio, el primer arranque interactivo pregunta
`¿Quieres crear el repositorio Git de VED-SYNC? [s/N]`. Sólo una respuesta afirmativa
lo inicializa; Intro, No o cerrar la entrada conservan la carpeta sin `.git`.
Esta confirmación inicial autoriza únicamente `git init`, sin commit ni remoto.
Los subcomandos sin terminal no solicitan entrada; se puede usar `menu` para mostrar
la pregunta o `init --autorizar` si se solicita expresamente desde un comando.

Sin terminal interactiva, la ejecución sin argumentos solo muestra el estado. `menu` abre el menú explícitamente; `--help` describe las operaciones sin ejecutar Git. Los mensajes del controlador están en español; los de Git dependen del idioma instalado.

La raíz y el nombre del repositorio se obtienen de la carpeta padre de `proyecto/`.
En esta aplicación son `SRC-VED/VED-SYNC` y `VED-SYNC`. No se utiliza `proyecto`
como nombre de repositorio. Las URL configuradas y las de publicación se comprueban
antes de conectar: su nombre final, quitando `.git`, debe coincidir con el nombre
base de la carpeta del proyecto. La comprobación admite HTTPS y SSH y no distingue
mayúsculas en el nombre del repositorio.

Para el primer envío, elegir **2**, escribir el mensaje y responder **s**.
Si falta `origin`, pide la cuenta de GitHub o la URL del usuario de esta copia.
Con una cuenta construye `https://github.com/CUENTA/VED-SYNC.git`. No contiene
una cuenta personal predeterminada ni importa configuraciones de otros discos.
Sólo guarda esa URL después de confirmar la operación.
El repositorio de GitHub debe existir antes de publicar.
No crea un repositorio remoto ni fuerza la subida si hay diferencias remotas.

Para usar otra cuenta o URL, entrar en **6 — OPERACIONES AVANZADAS** y elegir
**10 — Configurar origin**. En ese menú se mantienen por separado **5** preparar,
**6** commit y **7** publicar, con confirmación `AUTORIZAR` por operación.
También se puede abrir directamente con `./git.sh avanzado`.
Para ver el menú actualizado, salir con **0** y volver a ejecutar el lanzador.

Verificación del flujo sencillo (2026-11-12): **72 pruebas correctas**, incluida
la creación del primer commit y su envío con Git real a un repositorio local
desechable. La prueba comprueba que las huellas de ambos commits coinciden y que
el contenido llega íntegro. No se conecta a GitHub ni publica material del autor.

## Subcomandos equivalentes

Sustituir `./git.sh` por `.\git.bat` en Windows:

| Operación | Comando |
|---|---|
| Estado, rama y cambios pendientes | `./git.sh status` |
| Diferencias preparadas y sin preparar | `./git.sh diff` |
| Diez commits recientes | `./git.sh log` |
| Consultar cambios remotos | `./git.sh fetch --autorizar` |
| Actualizar sin crear un commit de mezcla | `./git.sh pull --autorizar` |
| Preparar todo VED-SYNC respetando exclusiones | `./git.sh add --autorizar .` |
| Preparar una ruta concreta | `./git.sh add --autorizar "ruta con espacios"` |
| Confirmar solo lo preparado | `./git.sh commit --autorizar -m "Mensaje"` |
| Publicar la rama actual con seguimiento configurado | `./git.sh push --autorizar` |
| Primer push con seguimiento explícito | `./git.sh push --autorizar -u origin NOMBRE_RAMA` |
| Consultar un remoto sin conectarse | `./git.sh remote --autorizar show origin` |

Los subcomandos de escritura requieren `--autorizar`; esa opción expresa la autorización al invocarlos manualmente. El menú avanzado añade una confirmación por comando. Las pruebas usan un Git simulado y repositorios desechables locales; no publican los proyectos del autor.

Antes de escribir se verifica la raíz real con Git, se muestra la rama, estado, resumen de cambios preparados/sin preparar y nombres de remotos. Una comprobación fallida interrumpe la operación y propaga el código de error. Con HEAD separado no se permite commit, pull o push. Pull requiere árbol limpio y seguimiento remoto, y siempre usa `--ff-only`; no crea commits de mezcla ni aplica stash automáticamente.

Push publica únicamente la rama actual mediante un destino explícito; no respeta configuraciones que accidentalmente publicarían todas las ramas. No admite forzar, borrar ramas, mirror ni otra rama por error. Add no admite `-f`, otros modificadores ni rutas fuera de VED-SYNC. Commit requiere mensaje y no incorpora cambios mediante `-a`. Para acciones avanzadas, revisar manualmente Git fuera del controlador; no se ejecutan por defecto.

## Git propio y mismo GitHub en ambos sistemas

Requisitos: Git instalado y Python 3.10 o posterior. Ubuntu utiliza `python3`; Windows utiliza `py -3`, o `python` si no existe el lanzador. `git.sh` y `git.bat` invocan el mismo `git_control.py`, siempre dentro del proyecto. Comparten el `.git/config` de VED-SYNC. Conservan el remoto existente si corresponde al proyecto; piden la cuenta o URL del usuario si falta. No guardan contraseñas ni tokens.

Es obligatorio un `.git` propio de VED-SYNC, incluido un archivo `.git` de worktree si
Git verifica la raíz correcta. Si sólo existe el Git de SRC-VED, el controlador
ofrece crear el de VED-SYNC en una sesión interactiva; sin terminal se detiene con
instrucciones. No inicializa ni altera el repositorio padre. Si se usan checkouts
separados en ambos sistemas, configurar en ambos el mismo remoto de GitHub del
proyecto y comprobar su seguimiento.

Si el proyecto aún no tiene Git propio, estos pasos son **instrucciones futuras**, no ejecutados en esta entrega:

```bash
./git.sh init --autorizar
./git.sh remote --autorizar add origin URL_DEL_REPOSITORIO_GITHUB_DE_VED_SYNC
./git.sh status
```

Usar una URL sin credenciales incrustadas; la autenticación corresponde al gestor de credenciales de Git o SSH. Crear el repositorio GitHub y establecer su URL requiere autorización explícita; estos scripts no crean repositorios en GitHub. No usar por error el remoto de otro proyecto de SRC-VED.

Tras revisar las exclusiones, preparar, confirmar y efectuar el primer push mediante los subcomandos de la tabla, indicando el nombre real de la rama mostrado en `status`. A partir de entonces el menú puede publicar con el seguimiento existente. No se modifica automáticamente la identidad Git, configuración global, credenciales ni ramas. Una instalación de Git nueva puede necesitar configurar nombre y correo antes del primer commit.

## Privacidad y credenciales

Cada persona que descargue el proyecto usa su propia configuración y su propio
acceso. El programa no busca identidades en particiones de Windows, no utiliza
la cuenta del autor como valor predeterminado y no solicita tokens mediante sus
propios formularios. La atribución de la obra a Víctor Estrada Díaz se conserva
como aviso de autoría; no se usa como identidad de quien crea nuevos commits.

La identidad del commit y las credenciales de acceso son datos distintos:
el nombre y el correo se incorporan a los commits y pueden ser públicos.
Para mantener privado el correo personal, configurar el correo `noreply` facilitado
por GitHub. [Documentación de correo de GitHub](https://docs.github.com/en/account-and-profile/concepts/email-addresses).

Para HTTPS, el controlador reinicia la lista de helpers de esa operación y utiliza
Git Credential Manager con el almacén seguro del sistema, libsecret en Linux o
wincred en Windows si están instalados. Con GCM, fuerza `secretservice` en Linux,
`wincredman` en Windows y `keychain` en macOS, sin recurrir a `plaintext`.
Si no hay almacén integrado, Ubuntu usa `credential-cache` durante 900 segundos;
en otros sistemas sin helper se solicita el acceso sin persistirlo.
No ejecuta `credential-store`, no lee `.git-credentials` y no añade credenciales
a las URL. No instala dependencias ni inicia autenticaciones al abrir el menú.
[Helpers de Git](https://git-scm.com/doc/credential-helpers),
[almacenes de GCM](https://github.com/git-ecosystem/git-credential-manager/blob/main/docs/credstores.md).

Los tokens se entregan al servidor elegido para autenticar operaciones HTTPS;
eso es necesario para acceder. No forman parte de archivos, commits ni páginas
publicadas. Con SSH, la autenticación se delega al cliente y agente SSH del usuario.
El programa suprime las variables de trazas de Git/GCM de sus procesos y desactiva
las redirecciones HTTP. El contenido de los secretos detectados nunca se imprime.

`.gitignore` excluye ficheros de credenciales, `.env` salvo ejemplos, llaves privadas
y directorios de almacenes conocidos. Además de estas exclusiones, el controlador
revisa contenido local antes de `add`, objetos del índice antes de `commit` y
objetos de todo el historial alcanzable antes de `push`. Bloquea tokens de GitHub,
claves privadas PEM/OpenSSH y URL con usuario y contraseña. Una comprobación
incompleta bloquea la operación. Un secreto borrado del archivo actual sigue
bloqueando la subida si permanece en un commit anterior.

Estas protecciones cubren las operaciones de los lanzadores del proyecto y los
formatos detectados; no pueden reconocer cualquier secreto arbitrario ni controlar
órdenes Git ejecutadas por fuera. No hay una garantía universal de ausencia de
secretos en contenido escrito por terceros. No se reescribe ni borra el historial
para resolver una detección: se detiene la publicación y se informa del problema.

## Exclusiones y archivos ya versionados

`.gitignore` excluye `.ved-sync-id`, temporales `.ved-sync-*`, logs, `operaciones.jsonl`, `tiempo.csv`, respaldos `*.original`, `.ved-sync/`, `.test-runs/`, `state.json`, `run.lock` y los directorios de versiones del motor. También mantiene las exclusiones previas de Python y repositorios ficticios.

Git no deja de versionar un archivo por añadirlo después a `.gitignore`. El controlador detecta archivos ya versionados que ahora están excluidos y bloquea las operaciones de escritura hasta revisarlos. No los borra ni modifica automáticamente el índice. Para revisarlos con Git instalado:

```bash
git -C /ruta/a/SRC-VED/VED-SYNC ls-files -ci --exclude-standard
```

Si hay que retirarlos del índice conservando los archivos locales, revisar y autorizar cada ruta antes de usar manualmente `git rm --cached -- RUTA`. No se ha ejecutado esa operación aquí. `.gitignore` no elimina secretos de commits históricos; cualquier limpieza histórica requiere revisión independiente.

## Motivo de la adaptación del BAT

El BAT existente de VED-SYNC ofrecía status, diff, log, init, add, commit, remote y push con autorización, pero no las revisiones completas de rama/cambios ni pull seguro. Se conserva ese conjunto de operaciones y se añaden las comprobaciones comunes, fetch y pull. La adaptación necesaria de la entrada BAT permite compartir exactamente las mismas reglas con Ubuntu y elimina la anterior limitación de siete argumentos. La lógica reside en un único controlador Python para evitar divergencias entre scripts.

No se han dejado scripts Git ni cambiado contenidos en SRC-VED fuera de VED-SYNC como resultado final. El `.gitignore` del padre conserva sus 255 bytes originales.

## Pruebas y alcance

```bash
bash -n git.sh
python3 -m unittest tests.test_git_control tests.test_cli -v
python3 tools/check_tests.py
```

Las pruebas usan un Git simulado y carpetas ficticias con espacios dentro de `.test-runs`, también con un repositorio padre ficticio que debe permanecer intacto. Verifican autorizaciones, menú, cancelación, estado/rama, errores, HEAD separado, exclusiones ya versionadas, avance rápido, push limitado y variables de entorno que podrían redirigir Git al padre.

Revalidación del 2026-11-11: Git 2.53.0 ya está disponible. La comprobación `git check-ignore` antes omitida pasa ahora con Git real. Se añaden seis pruebas reales permanentes de estado/rama, diferencias, add respetando exclusiones, rechazo del padre, autorización, cancelación y equivalencia con el controlador invocado por el BAT. Se crean y preparan únicamente repositorios desechables dentro de `.test-runs`; no se hacen commits, fetch, pull ni push reales.

Los 36 casos dirigidos de Git y CLI pasan sin omisiones. `git.sh` y las dos rutas Python del BAT invocan el mismo controlador; con Git real, Bash y ese controlador producen la misma salida y consultan el mismo remoto ficticio configurado localmente. Esto verifica la lógica compartida y el destino configurado, no la ejecución del BAT en Windows. No hay `cmd.exe` en este entorno, por lo que la ejecución nativa Windows, autenticación y conectividad GitHub siguen pendientes. Los scripts de producción no se modificaron en esta revalidación. Resultados en `RESULTADOS_PRUEBAS_GIT.txt` y `AUDITORIA.md`.

Las pruebas locales no requieren credenciales. No se leen ni copian las de Windows. La autorización desde un móvil corresponde al flujo web de GitHub CLI; `gh` no está instalado aquí y no se ha iniciado una solicitud de acceso.


## Ayuda integrada y comentarios

`./git.sh --help` y `.\git.bat --help` muestran las mismas instrucciones del controlador: alcance exclusivo de VED-SYNC, operaciones, autorización, secuencia manual de primer envío, códigos de salida y protecciones. Mostrar esta ayuda no ejecuta Git, no requiere un repositorio ni inicia autenticación. Los ejemplos impresos no se ejecutan.

La ayuda distingue expresamente Git local y GitHub: `init` solo prepara el Git local; crear el repositorio de GitHub sigue pendiente y no se ha añadido como parte de esta revisión documental. Los cuatro lanzadores incluyen comentarios de uso; la lógica operativa del BAT permanece sin cambios.
