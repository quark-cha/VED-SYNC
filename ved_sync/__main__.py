import argparse
import json
import sqlite3
from pathlib import Path
import threading
import sys

from .telemetry import Console

from .engine import Engine, PROJECT


SYNC_HELP = """Qué hace y dónde trabaja:
  Compara y sincroniza los repositorios del JSON mediante SHA-256 e historial.
  No propaga borrados ni resuelve conflictos sobrescribiendo las variantes.
  La configuración de ejemplo usa solo tres repositorios ficticios:
  demo/repos/uno, demo/repos/dos y demo/repos/tres, dentro de VED-SYNC.

Cómo ejecutar desde la raíz de VED-SYNC:
  ./run.sh                         Vigilancia continua en simulación; Ctrl+C sale.
  ./run.sh --once                   Simular una comprobación y terminar.
  ./run.sh --once --apply           Aplicar una comprobación y terminar.
  ./run.sh --config config/pruebas.json --once
                                   Simular con otro JSON revisado previamente.
  ./run.sh --gui                    Indicadores gráficos; requiere Tkinter.
  ./run.sh --config .ved-sync-recuperacion.json --restore-projects --once --apply
                                   Recuperar Windows → Ubuntu con el JSON privado.
                                   Windows es referencia; VED-SYNC queda excluido.
                                   Conserva .original verificados antes de sustituir.
  En Windows, sustituir ./run.sh por .\\run.bat con los mismos argumentos.
  Sin lanzador: python3 -m ved_sync realiza un ciclo, salvo que se use --watch.

Qué modifica:
  Sin --apply no modifica el contenido ni crea identificadores en las raíces.
  Sí escribe logs, tiempo.csv y un bloqueo temporal en el directorio de control.
  Con --apply permite copias, respaldos .original e identificadores opcionales.
  Los UUID y respaldos internos no se propagan como archivos de usuario.
  Las rutas del JSON parten de ese JSON; los lanzadores parten de su carpeta.

Cómo comprobar el resultado:
  La terminal muestra tres filas fijas: dirección de copia, semáforo/ruta/icono/proyecto/archivos y barra.
  ⌛ indica trabajo; ✓ final correcto; ! final con problemas; [SIM] es simulación.
  --json muestra el informe JSON y evita la pantalla fija; redirigir stdout conserva JSON.
  Antes de continuar, comprobar simulation: false en JSON y todos los estados en verde.
  Con rojo, gris, errores o conflictos, detenerse y revisar el informe JSON.
  Salida 0: ningún estado rojo; no garantiza que las raíces grises estén presentes.
  Salida 1: hay desincronización conocida. Salida 2: error de configuración/ejecución.
  --once evita que la vigilancia quede abierta; no se combina con --gui.
  La recuperación explícita usa python3 -m ved_sync --recover ..., no run.sh.

Este programa no crea repositorios GitHub, no publica código ni activa servicios.
Guías: docs/ARRANQUE.md y docs/SALIDAS_Y_RECUPERACION.md.
"""


class SpanishHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, 'Uso: ' if prefix is None else prefix)


def main():
    parser = argparse.ArgumentParser(
        prog='ved-sync', description='VED-SYNC: simulación por defecto',
        formatter_class=SpanishHelpFormatter, epilog=SYNC_HELP, add_help=False)
    parser._optionals.title = 'Opciones'
    parser.add_argument('-h', '--help', action='help', help='Mostrar esta ayuda y salir sin sincronizar')
    parser.add_argument('--config', type=Path, default=PROJECT / 'config/example.json',
                        help='JSON de repositorios; por defecto config/example.json (tres raíces ficticias)')
    parser.add_argument('--apply', action='store_true', help='Aplicar copias y registrar versiones')
    parser.add_argument('--allow-external', action='store_true', help='Habilitar destinos fuera de VED-SYNC')
    parser.add_argument('--restore-projects', action='store_true',
                        help='Permitir recuperación autoritativa en SRC-VED, excluyendo VED-SYNC; nunca escribir en Windows')
    parser.add_argument('--reset-queue', action='store_true',
                        help='Respaldar y reconstruir la cola de recuperación desde el principio')
    parser.add_argument('--watch', action='store_true', help='Sondeo periódico; Ctrl+C para terminar')
    parser.add_argument('--once', action='store_true', help='Una comprobación y salir, incluso con --watch')
    parser.add_argument('--gui', action='store_true', help='Ventana permanente de indicadores')
    parser.add_argument('--json', action='store_true',
                        help='Mostrar el informe JSON sin pantalla fija')
    parser.add_argument('--quiet', action='store_true', help='Sin progreso en consola; conservar JSON y registros')
    parser.add_argument('--recover', nargs=3, metavar=('REPOSITORIO', 'RUTA', 'SHA256'),
                        help='Recuperar una versión .original verificada; simulación salvo --apply')
    args = parser.parse_args()
    if args.reset_queue and not (args.restore_projects and args.apply and args.once):
        parser.error('--reset-queue requiere --restore-projects, --apply y --once')
    if args.once and args.gui:
        parser.error('--once no admite --gui')
    if args.recover and (args.watch or args.gui):
        parser.error('--recover no admite --watch ni --gui')
    console = None if args.quiet or args.json or args.gui else Console(sys.stderr)
    json_output = args.json or args.quiet or not sys.stdout.isatty()
    try:
        options = {'apply': args.apply, 'allow_external': args.allow_external, 'console': console}
        if args.restore_projects:
            options['restore_projects'] = True
        if args.reset_queue:
            options['reset_queue'] = True
        engine = Engine(args.config, **options)
        if args.gui:
            try:
                from .gui import run
            except ImportError:
                parser.exit(2, 'La interfaz requiere Tkinter. En Ubuntu: paquete python3-tk; en Windows: Python con Tcl/Tk. El motor de consola sigue disponible.\n')
            run(engine)
        else:
            stop = threading.Event()
            while True:
                report = engine.recover(*args.recover) if args.recover else engine.run_once()
                if json_output:
                    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
                if args.once or not args.watch:
                    return 1 if any(v == 'rojo' for v in report['status'].values()) else 0
                stop.wait(engine.interval)
    except KeyboardInterrupt:
        if console is not None:
            console.fail('KeyboardInterrupt', interrupted=True)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error) as exc:
        if console is not None and console.frame:
            console.fail(type(exc).__name__)
            return 2
        parser.exit(2, f'Error: {exc}\n')
    finally:
        if console is not None:
            console.close()


if __name__ == '__main__':
    raise SystemExit(main())
