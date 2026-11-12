#!/usr/bin/env bash
# Control Git de VED-SYNC: siempre relativo al propio script.
# Ayuda completa: ./git.sh --help (no ejecuta Git ni conecta con GitHub).
# Sin argumentos abre el menú; fuera de una terminal muestra solo el estado.
# Requiere Git propio de VED-SYNC y rechaza el repositorio padre de SRC-VED.
# init prepara Git local; este script todavía no crea el repositorio en GitHub.
# add, commit y push son pasos separados con autorización explícita.
# El menú solicita AUTORIZAR; los subcomandos requieren --autorizar.
# No contrata servicios; la lógica y las instrucciones residen en git_control.py.
set -eu
script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'No se encuentra Python 3. Instale Python 3 para usar el controlador Git.' >&2
  exit 127
fi
exec python3 "$script_dir/git_control.py" "$@"
