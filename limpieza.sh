#!/usr/bin/env bash
# VED-SYNC — Autor: Víctor Estrada Díaz. https://estradad.es/
# Código: HL3 y condiciones del autor: https://estradad.es/licencia.php
# Limpieza local bajo petición. --simular muestra el plan sin borrar.
set -eu
script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'No se encuentra Python 3.' >&2
  exit 127
fi
exec python3 -B "$script_dir/ved_sync/cleanup.py" "$@"
