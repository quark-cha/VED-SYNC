#!/usr/bin/env bash
# Git específico de VED-SYNC — Autor: Víctor Estrada Díaz.
# https://estradad.es/ — Código HL3: https://estradad.es/licencia.php
# Controla el Git de VED-SYNC, no un repositorio dentro de proyecto/ ni el de SRC-VED.
# ./git.sh --help muestra la ayuda; las escrituras requieren --autorizar.
set -eu
script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(CDPATH= cd -- "$script_dir/.." && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'No se encuentra Python 3 para el Git de VED-SYNC.' >&2
  exit 127
fi
if [ ! -f "$project_dir/git_control.py" ]; then
  echo 'No se encuentra el controlador Git propio de VED-SYNC.' >&2
  exit 1
fi
exec python3 "$project_dir/git_control.py" "$@"
