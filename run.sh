#!/usr/bin/env bash
# Arranque de VED-SYNC en Ubuntu: vigilancia y simulacion por defecto.
# Ayuda completa: ./run.sh --help (no arranca la sincronización).
# Recuperación real Windows → Ubuntu: ./run.sh --config .ved-sync-recuperacion.json --restore-projects --once --apply
# ./run.sh vigila en simulación: usa config/example.json y solo raíces ficticias.
# ./run.sh --once simula un ciclo y termina; Ctrl+C detiene la vigilancia.
# ./run.sh --once --apply aplica copias y respaldos; revisar antes la simulación.
# Sin aplicar se escriben únicamente registros/tiempos en el control del proyecto.
# Terminal: cabecera fija y barra debajo; --json muestra el informe para scripts.
# Reenvía todos los argumentos y resuelve el programa desde su propia carpeta.
# No ejecuta Git, no publica en GitHub y no activa servicios ni suscripciones.
set -eu
script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'No se encuentra Python 3. Instale Python 3 para arrancar VED-SYNC.' >&2
  exit 127
fi
cd -- "$script_dir"
exec python3 -m ved_sync --watch "$@"
