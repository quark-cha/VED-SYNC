# Configuración local de ubicaciones

## Lectura y escritura remota opcional

En el modo multidireccional, un repositorio puede declarar
`"write_policy": "if_possible"`. Se intentan las copias permitidas; si el sistema
devuelve EACCES, EPERM o EROFS, se registra `write_unavailable` y se continúa
actualizando los demás destinos disponibles. No se modifican permisos, montajes ni
protecciones para forzar la escritura. Si posteriormente permite escribir, el
siguiente ciclo vuelve a comparar y aplicar los cambios compatibles.

Esta política no oculta conflictos, errores de lectura, fallos de SHA-256 ni otros
errores de copia. Una diferencia pendiente mantiene el estado desincronizado;
no es una terminación catastrófica del ciclo. El valor predeterminado sigue siendo
`"required"`, que registra los fallos de escritura como errores, sin cancelar
las copias independientes del mismo ciclo.

`"read_only": true` es distinto: permite aportar contenido sin intentar escribir
ni crear identificadores en esa raíz. Es la protección actual de Windows. No se
levantó el bloqueo de escritura en `/mnt/windows`. El comando de recuperación
autoritativa Windows → Ubuntu conserva su propósito; para sincronizar cambios en
ambas direcciones se utiliza una configuración sin `authoritative_source`, con
repositorios cuya escritura esté autorizada y conservación de conflictos.

El objetivo habitual es el mismo contenido y el mismo motor al arrancar este
mismo ordenador desde SSD o USB, en Windows o Ubuntu. No es necesario que el otro
sistema operativo esté arrancado: basta que su copia esté accesible como carpeta.
Las rutas locales de acceso pueden cambiar entre arranques y por eso el JSON
privado no se propaga. La prioridad fija de Windows pertenece únicamente a la
recuperación inicial; no debe imponerse después a las ediciones habituales de
Ubuntu. Que las dos copias lleguen a ser iguales requiere escritura disponible
en ambos destinos; una raíz de solo lectura puede dejar cambios pendientes.

Cada copia de VED-SYNC puede tener un `.ved-sync-config.json` propio en su raíz. Ese nombre está excluido expresamente del motor y de Git. No se sincroniza, no se guarda como versión de contenido y no se sustituye por el fichero de otra copia. La exclusión se aplica también cuando está anidado dentro de SRC-VED. La lista interna incluye además `.git`, tanto directorio como archivo de worktree.

`config/example.json` sigue siendo la configuración de demostración portable. No se ha modificado el arranque para que use automáticamente las ubicaciones reales.

## Borrador actual

Se ha guardado el archivo local con las dos ubicaciones conocidas. La segunda apunta a la carpeta SRC-VED dentro del Escritorio, para no incluir todo el Escritorio. La tercera está preparada para descubrir un USB registrado. Los tipos de dispositivo desconocidos no se han adivinado.

Un nombre como `/dev/usbb` representa un dispositivo, no una raíz de archivos válida para la sincronización. Debe indicarse la carpeta ya montada que contiene la copia SRC-VED, por ejemplo `/media/usuario/ETIQUETA/SRC-VED`. El programa no monta, formatea ni cambia particiones.

**El archivo completo sigue siendo un borrador, no una configuración lista para ejecutar.** El motor sigue bloqueando la escritura en Windows y la inclusión de otros proyectos, y exige separar el registro de las raíces. Adaptar la sincronización del SRC-VED completo y definir sus exclusiones requiere revisión antes de cualquier aplicación sobre datos reales. No se han levantado esas protecciones.

## Repositorio 3: USB opcional

```json
{
  "id": "3",
  "device_type": "usb",
  "paths": [],
  "search_roots": ["/media/victor", "/run/media/victor", "/mnt"],
  "mounted_subdirectory": "SRC-VED",
  "uuid": null
}
```

Para registrarlo una vez, hay que identificar la carpeta SRC-VED del USB ya montado y anotar en `uuid` el UUID v4 de su propio `.ved-sync-id`. Si aún no existe, queda pendiente crearlo explícitamente en ese repositorio cuando se autorice trabajar con él; no se debe copiar el de otro repositorio. No se ha registrado ni modificado ningún USB real.

Sin UUID registrado, el repositorio 3 permanece gris. Con UUID, cada comprobación busca la carpeta indicada dentro de los volúmenes ya montados en las raíces de búsqueda o sus hijos inmediatos. Solo acepta el UUID esperado. Al desconectar queda gris; al reconectar o cambiar el nombre del montaje se reconoce en la siguiente comprobación. Dos coincidencias del UUID producen rojo y bloquean su selección. No se siguen enlaces simbólicos ni se crean identificadores en dispositivos desconocidos.

La vigilancia incorpora el repositorio reconocido al siguiente ciclo del motor; no inicia el programa al conectar un USB ni instala servicios de arranque. No monta nada. Las raíces de búsqueda son locales y configurables; en Windows pueden indicarse raíces de unidades ya disponibles y la misma carpeta relativa. La detección nativa de Windows queda pendiente de validación en ese sistema.

Preparar este repositorio opcional no hace que las otras raíces estén verificadas ni convierte un estado gris en sincronización completa. El JSON local no se activa automáticamente: `run.sh` conserva la demostración por defecto.

## Validación sin sincronizar

```bash
python3 -m unittest tests.test_internal_files -v
```

Las pruebas escanean tres árboles ficticios en lectura, prueban el rechazo de destinos internos antes de cualquier copia y comprueban la regla Git. No se llama a `Engine.__init__`, `run_once`, a los lanzadores ni a Git; no se accede a las ubicaciones reales. Esto no sustituye una validación futura de integración del modo SRC-VED.
