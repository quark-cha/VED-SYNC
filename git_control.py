"""Control Git común para git.sh y git.bat.

Autor de la obra: Víctor Estrada Díaz, https://estradad.es/.
Licencia y condiciones: https://estradad.es/licencia.php.
"""
from __future__ import annotations

import os
import json
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import re
from datetime import datetime
from urllib.parse import quote, unquote, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parent
if ROOT.name.casefold() == 'proyecto':
    ROOT = ROOT.parent
READ_ACTIONS = {'status', 'diff', 'log'}
WRITE_ACTIONS = {'init', 'fetch', 'pull', 'add', 'commit', 'push', 'remote'}
HELP = '''Uso: ./git.sh OPERACION [--autorizar] [argumentos]
En Windows: .\\git.bat con los mismos argumentos.

Qué hace y dónde trabaja:
  Gestiona exclusivamente el Git propio de VED-SYNC, desde la carpeta del script.
  Comprueba raíz, rama, archivos pendientes y exclusiones antes de escribir.
  Si falta .git propio, pregunta si quieres crearlo en el primer arranque interactivo.
  La respuesta predeterminada es No; nunca utiliza el Git padre de SRC-VED.
  No crea repositorios en GitHub sin preguntar. init inicializa únicamente Git local.
  Si falta el destino en su cuenta, permite crearlo privado, público o no crearlo.

Operaciones:
  --help                         Mostrar esta ayuda sin ejecutar Git ni conectar.
  menu                           Abrir el menú sencillo; opción 2: subir cambios.
  avanzado                       Abrir el menú de operaciones separadas.
  status                         Mostrar proyecto, rama y resumen de cambios.
  diff                           Mostrar diferencias preparadas y sin preparar.
  log                            Mostrar los diez últimos commits.
  fetch --autorizar              Descargar referencias; no integra cambios.
  pull --autorizar               Actualizar con avance rápido; exige árbol limpio.
  add --autorizar RUTA [...]     Preparar rutas respetando .gitignore.
  commit --autorizar -m TEXTO    Crear un commit local con lo ya preparado.
  push --autorizar               Publicar la rama actual con seguimiento existente.
  push --autorizar -u REMOTO RAMA Registrar seguimiento al publicar la rama actual.
  remote --autorizar [...]      Consultar o configurar remotos del Git local.
  init --autorizar               Inicializar Git local, solo por petición expresa.

Sin argumentos: menú en una terminal; solo estado en salidas no interactivas.
La opción 2 prepara, crea el commit y publica tras pedir mensaje y confirmar con s.
Si falta la identidad, pide nombre y correo y ofrece guardarlos para este proyecto.
También permite usarlos sólo en esa ejecución. Si están configurados, los reutiliza.
Muestra COMMIT CREADO y SUBIDA COMPLETADA sólo al completar cada paso.
Si falta origin, pide la cuenta o URL del usuario que está ejecutando el proyecto.
Los tokens y claves se gestionan fuera del contenido publicable, mediante Git.
La identidad del commit (nombre y correo) sí es pública; puede usarse un noreply.
El menú avanzado muestra cada comando y pide escribir AUTORIZAR antes de escribir.
En el menú avanzado no se encadenan preparación, commit y publicación.
En subcomandos, --autorizar es la autorización explícita de esa operación.
El repositorio remoto debe llamarse como la carpeta raíz del proyecto.
La opción 10 del menú avanzado permite configurar otra cuenta o URL de origin.

Cómo preparar el primer envío (ejemplos para ejecutar manualmente):
  ./git.sh init --autorizar
  ./git.sh remote --autorizar add origin URL_DEL_REPOSITORIO_GITHUB
  ./git.sh add --autorizar .
  ./git.sh diff
  ./git.sh commit --autorizar -m "Primera versión de VED-SYNC"
  ./git.sh status
  ./git.sh push --autorizar -u origin NOMBRE_RAMA
  Sustituir la URL por la de tu repositorio y NOMBRE_RAMA por la rama mostrada.
  init solo se usa si aún no existe Git propio; configurar origin solo una vez.
  La autenticación de GitHub debe estar preparada por el usuario.

Protecciones y resultados:
  No habilita add forzado, push forzado, borrado remoto ni limpieza.
  Bloquea escrituras si hay archivos ya versionados que ahora estén excluidos.
  Excluye IDs privados, logs, tiempo.csv, temporales, .original y estados internos.
  Los ejemplos no se ejecutan al mostrar esta ayuda y no activan suscripciones.
  Si falla una comprobación u orden, se detiene y devuelve el código de error.
  Salida 0: operación completada; 2: uso o autorización inválidos; 127: falta Git.
  Otros fallos devuelven 1, 130 por interrupción o el código comunicado por Git.
Guía completa: docs/GIT.md. Arranque del sincronizador: ./run.sh --help.
'''



class GitError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


class RemoteNotFound(GitError):
    pass


def environment():
    """Caller repository overrides must not redirect a script to another checkout."""
    blocked = {'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE',
               'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
               'GIT_CEILING_DIRECTORIES', 'GIT_CONFIG', 'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM',
               'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT'}
    env = {k: v for k, v in os.environ.items()
           if k not in blocked and not k.startswith(('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_',
                                                     'GIT_TRACE', 'GCM_TRACE'))
           and k not in {'GIT_CURL_VERBOSE', 'GH_DEBUG'}}
    env['GIT_OPTIONAL_LOCKS'] = '0'
    env['GIT_PAGER'] = 'cat'
    return env


PRIVATE_NAMES = {'.gitconfig', '.git-credentials', '.netrc', '_netrc', '.ssh', '.gnupg',
                 '.aws', '.azure', '.gcm', '.password-store',
                 'credentials.json', 'credentials.yaml', 'credentials.yml',
                 'secrets.json', 'secrets.yaml', 'secrets.yml', 'id_rsa', 'id_ed25519'}
SECRET_PATTERN = re.compile(
    rb'(?:gh[pousr]_[A-Za-z0-9]{20,255}|github_pat_[A-Za-z0-9_]{20,255}'
    rb'|-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----'
    rb'|https?://[^\s/:@]+:[^\s/@]+@)', re.IGNORECASE)


def private_path(name):
    for part in name.replace('\\', '/').casefold().split('/'):
        if (part in PRIVATE_NAMES or part == '.env'
                or part.startswith('.env.') and part not in {'.env.example', '.env.sample'}
                or part.endswith(('.pem', '.key', '.p12', '.pfx'))):
            return True
    return False


def check_secret(data):
    if SECRET_PATTERN.search(data):
        raise GitError('Publicación bloqueada: se ha detectado un token, una clave privada '
                       'o una URL con credenciales. Su valor no se muestra ni se registra.', 2)


def inspect_stream(stream, size=None, *, tree=False, hash_size=20):
    remaining, overlap = size, b''
    tree_buffer = b''
    while remaining is None or remaining:
        chunk = stream.read(65536 if remaining is None else min(65536, remaining))
        if not chunk:
            if remaining:
                raise GitError('No se pudo completar la revisión de privacidad.', 2)
            break
        if remaining is not None:
            remaining -= len(chunk)
        if tree:
            tree_buffer += chunk
            while True:
                space = tree_buffer.find(b' ')
                end = tree_buffer.find(b'\0', space + 1)
                if space < 0 or end < 0 or len(tree_buffer) < end + 1 + hash_size:
                    break
                name = tree_buffer[space + 1:end].decode('utf-8', errors='replace')
                if private_path(name):
                    raise GitError('Publicación bloqueada: el historial contiene archivos '
                                   'de credenciales o configuración privada.', 2)
                tree_buffer = tree_buffer[end + 1 + hash_size:]
        else:
            check_secret(overlap + chunk)
            overlap = (overlap + chunk)[-4096:]


def inspect_objects(repo, object_ids):
    object_ids = set(object_ids)
    if not object_ids:
        return
    process = subprocess.Popen([repo.executable, '--no-pager', '-C', str(ROOT), 'cat-file', '--batch'],
                               cwd=ROOT, env=repo.env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for oid in object_ids:
            if not re.fullmatch(r'[0-9a-f]{40,64}', oid):
                raise GitError('No se pudo verificar el contenido que se iba a publicar.', 2)
            process.stdin.write(oid.encode('ascii') + b'\n')
            process.stdin.flush()
            fields = process.stdout.readline().split()
            if len(fields) != 3 or not fields[2].isdigit():
                raise GitError('No se pudo revisar un objeto del repositorio; subida bloqueada.', 2)
            inspect_stream(process.stdout, int(fields[2]), tree=fields[1] == b'tree',
                           hash_size=len(oid) // 2)
            if process.stdout.read(1) != b'\n':
                raise GitError('No se pudo completar la revisión del repositorio.', 2)
        process.stdin.close()
        if process.wait() != 0:
            raise GitError('La revisión de privacidad no terminó correctamente.', 2)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait()
        process.stdout.close()
        if not process.stdin.closed:
            process.stdin.close()


def check_publication(repo, *, working=False, history=False):
    """Inspect local data only. Never print secret contents or query a remote."""
    if history:
        ids = repo.run('rev-list', '--objects', '--no-object-names', 'HEAD', capture=True).stdout.splitlines()
    elif working:
        names = repo.run('ls-files', '-z', '--cached', '--others', '--exclude-standard', capture=True).stdout
        for name in filter(None, names.split('\0')):
            if private_path(name):
                raise GitError('Preparación bloqueada: hay archivos privados que deben quedar fuera de Git.', 2)
            path = ROOT / name
            if path.is_symlink():
                check_secret(os.readlink(path).encode('utf-8'))
            elif path.is_file():
                with path.open('rb') as stream:
                    inspect_stream(stream)
        return
    else:
        entries = repo.run('ls-files', '--stage', '-z', capture=True).stdout
        ids = []
        for entry in filter(None, entries.split('\0')):
            metadata, name = entry.split('\t', 1)
            if private_path(name):
                raise GitError('Commit bloqueado: contiene archivos privados preparados.', 2)
            if not metadata.startswith('160000 '):
                ids.append(metadata.split()[1])
    inspect_objects(repo, ids)


def secure_access(repo):
    """Delegate secrets to a system wallet, or an ephemeral memory cache."""
    manager = next((name.removeprefix('git-credential-')
                    for name in ('git-credential-manager', 'git-credential-manager-core')
                    if shutil.which(name)), None)
    exec_path = repo.run('--exec-path', capture=True, required=False).stdout.strip()
    helper_dir = Path(exec_path) if exec_path else None
    oauth = (bool(shutil.which('git-credential-oauth'))
             or bool(helper_dir and any((helper_dir / name).is_file()
                                        for name in ('git-credential-oauth', 'git-credential-oauth.exe'))))
    options = ['-c', 'credential.helper=', '-c', 'http.followRedirects=false']
    if manager:
        store = 'wincredman' if os.name == 'nt' else 'keychain' if sys.platform == 'darwin' else 'secretservice'
        options += ['-c', 'credential.helper=' + manager, '-c', 'credential.credentialStore=' + store]
        repo.env['GCM_CREDENTIAL_STORE'] = store
        print('Acceso: Git Credential Manager y almacén protegido del sistema.', flush=True)
    elif helper_dir and (helper_dir / 'git-credential-libsecret').is_file():
        options += ['-c', 'credential.helper=libsecret']
        print('Acceso: llavero del sistema mediante libsecret.', flush=True)
    elif helper_dir and (helper_dir / 'git-credential-wincred.exe').is_file():
        options += ['-c', 'credential.helper=wincred']
        print('Acceso: Administrador de credenciales de Windows.', flush=True)
    elif os.name == 'posix':
        options += ['-c', 'credential.helper=cache --timeout=900']
        print('Acceso: memoria temporal durante 15 minutos; no se guardan tokens en archivos. '
              'Para conservarlos entre sesiones, instale Git Credential Manager o libsecret.', flush=True)
    else:
        print('Acceso: Git solicitará las credenciales sin guardarlas en archivos.', flush=True)
    if oauth and not manager:
        # Storage runs first; OAuth only runs when no stored credential is available.
        options += ['-c', 'credential.helper=oauth']
        repo.env['GIT_TERMINAL_PROMPT'] = '0'
        print('Identificación en el navegador: autorice el acceso a su cuenta. '
              'No necesita escribir ni recordar un token.', flush=True)
    elif not manager:
        print('En GitHub, el campo Password de Git espera un token de acceso. '
              'Para entrar mediante el navegador en Ubuntu, instale: '
              'sudo apt install git-credential-oauth', flush=True)
    return options


class Repository:
    def __init__(self):
        self.executable = shutil.which('git')
        if not self.executable:
            raise GitError('No se encuentra Git. Instale Git y vuelva a ejecutar el script.', 127)
        self.env = environment()
        self.confirm = False

    def run(self, *args, capture=False, required=True):
        effective = list(args)
        while effective and effective[0] == '-c':
            effective = effective[2:]
        writing = bool(effective) and (effective[0] in ('init', 'fetch', 'pull', 'add', 'commit', 'push')
                  or effective[0] == 'remote' and len(effective) > 1 and effective[1] not in ('show', 'get-url'))
        if self.confirm and writing:
            print('Operación preparada: git ' + shlex.join(args), flush=True)
            try:
                answer = input('Escriba AUTORIZAR para ejecutarla, o pulse Intro para cancelar: ')
            except EOFError:
                answer = ''
            if answer.strip() != 'AUTORIZAR':
                raise GitError('Operación cancelada. No se ha ejecutado la escritura.')
        options = []
        if effective and effective[0] in {'add', 'commit', 'push'}:
            if effective[0] == 'add':
                check_publication(self, working=True)
            elif effective[0] == 'commit':
                check_secret('\n'.join(effective[1:]).encode('utf-8'))
                check_publication(self)
            else:
                check_publication(self, history=True)
        if effective and effective[0] in {'fetch', 'pull', 'push'}:
            options = secure_access(self)
        command = [self.executable, '--no-pager', '-C', str(ROOT), *options, *args]
        if effective and effective[0] == 'push' and not capture:
            # Keep browser instructions visible while retaining only redacted diagnostics.
            process = subprocess.Popen(command, cwd=ROOT, env=self.env, text=True,
                                       encoding='utf-8', errors='replace', stderr=subprocess.PIPE)
            details = []
            diagnostic_size = 0
            try:
                for line in process.stderr:
                    safe = SECRET_PATTERN.sub(b'[SECRETO]', line.encode('utf-8')).decode('utf-8')
                    print(safe, end='', file=sys.stderr, flush=True)
                    if diagnostic_size < 65536:
                        details.append(safe)
                        diagnostic_size += len(safe)
                result = subprocess.CompletedProcess(command, process.wait(), None, ''.join(details))
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
                raise
            finally:
                process.stderr.close()
        else:
            result = subprocess.run(command, cwd=ROOT, env=self.env, text=True,
                                    encoding='utf-8', errors='replace',
                                    stdout=subprocess.PIPE if capture else None,
                                    stderr=subprocess.PIPE if capture else None)
        if required and result.returncode:
            if effective and effective[0] == 'push' and 'repository not found' in (result.stderr or '').casefold():
                raise RemoteNotFound('GitHub no encuentra el repositorio o la cuenta autorizada no tiene acceso.',
                                     result.returncode)
            raise GitError('Git no ha completado la operación; no se continuará.', result.returncode)
        return result

    def check_root(self):
        if not (ROOT / '.git').exists():
            raise GitError('No hay repositorio Git propio en VED-SYNC. No se utilizará un repositorio padre.')
        result = self.run('rev-parse', '--show-toplevel', capture=True, required=False)
        if result.returncode or Path(result.stdout.strip()).resolve() != ROOT:
            raise GitError('No se puede verificar VED-SYNC como raíz Git. Revise los metadatos .git.')

    def preview(self):
        print('Proyecto: ' + str(ROOT), flush=True)
        print('Nombre del repositorio: ' + ROOT.name, flush=True)
        result = self.run('symbolic-ref', '--quiet', '--short', 'HEAD', capture=True, required=False)
        branch = result.stdout.strip() if result.returncode == 0 else None
        if branch:
            print('Rama actual: ' + branch, flush=True)
        else:
            head = self.run('rev-parse', '--short', 'HEAD', capture=True, required=False)
            print('Rama actual: HEAD separado' + (' (' + head.stdout.strip() + ')' if head.returncode == 0 else ''), flush=True)
        print('Estado y cambios pendientes:', flush=True)
        self.run('status', '--short', '--branch')
        print('Resumen sin preparar:', flush=True)
        self.run('diff', '--stat', '--')
        print('Resumen preparado para commit:', flush=True)
        self.run('diff', '--cached', '--stat', '--')
        remotes = self.run('remote', capture=True).stdout.splitlines()
        print('Remotos configurados: ' + (', '.join(remotes) if remotes else 'ninguno'), flush=True)
        ignored = self.run('ls-files', '-z', '-ci', '--exclude-standard', capture=True).stdout
        tracked_ignored = [p for p in ignored.split('\0') if p]
        if tracked_ignored:
            print('ATENCIÓN: hay archivos ya versionados que ahora coinciden con .gitignore:', flush=True)
            for path in tracked_ignored:
                print('  ' + path, flush=True)
            print('No se retirarán del índice automáticamente. Revise GIT.md.', flush=True)
        return branch, remotes, tracked_ignored


def check_repository_url(url):
    """The remote basename must identify this project, never a copied project's URL."""
    if not url or url.startswith('-') or any(c in url for c in '\r\n\0'):
        raise GitError('URL de repositorio no válida.', 2)
    try:
        if '://' in url:
            parsed = urlsplit(url)
            if parsed.scheme not in ('https', 'ssh', 'file'):
                raise GitError('Use HTTPS o SSH para proteger el acceso al servidor.', 2)
            if parsed.password or (parsed.scheme in ('http', 'https') and parsed.username):
                raise GitError('Use una URL sin contraseñas ni tokens incrustados.', 2)
            if parsed.query or parsed.fragment:
                raise GitError('Use la URL Git del repositorio, sin parámetros ni fragmentos.', 2)
            path = parsed.path
        elif re.match(r'^(?:[^/\\\s]+@)?[^/\\:\s]+:', url) and not re.match(r'^[A-Za-z]:[/\\]', url):
            path = url.split(':', 1)[1]
        else:
            path = url
    except ValueError:
        raise GitError('URL de repositorio no válida.', 2) from None
    name = unquote(path.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1])
    if name.casefold().endswith('.git'):
        name = name[:-4]
    if name.casefold() != ROOT.name.casefold():
        raise GitError(f'El remoto corresponde a {name!r}; debe corresponder a {ROOT.name!r}, '
                       'el nombre de la carpeta padre de proyecto/.', 2)


def check_remote(repo, name, *, push=False):
    options = ['--push', '--all'] if push else ['--all']
    result = repo.run('remote', 'get-url', *options, name, capture=True, required=False)
    urls = result.stdout.splitlines() if result.returncode == 0 else []
    if not urls:
        raise GitError('No se puede determinar la URL del remoto. Elija 10 para configurarlo.')
    for url in urls:
        check_repository_url(url)


class NoCredentialRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def github_request(method, path, token, payload=None):
    """Use credentials only in TLS headers to GitHub, never in URLs or diagnostics."""
    request = Request('https://api.github.com' + path, method=method,
                      data=json.dumps(payload).encode('utf-8') if payload is not None else None,
                      headers={'Authorization': 'Bearer ' + token,
                               'Accept': 'application/vnd.github+json',
                               'Content-Type': 'application/json', 'User-Agent': 'project-git-controller'})
    try:
        with build_opener(NoCredentialRedirect()).open(request, timeout=30) as response:
            data = json.loads(response.read(1048576))
            if not isinstance(data, dict):
                raise ValueError('Unexpected response')
            return response.status, data
    except HTTPError as error:
        error.close()
        return error.code, {}
    except (URLError, OSError, ValueError):
        raise GitError('No se pudo consultar GitHub de forma segura. No se ha creado el repositorio.') from None


def git_credential(repo, options, operation, description):
    # stdout contains credentials only for fill; it must never inherit the terminal.
    result = subprocess.run([repo.executable, '--no-pager', '-C', str(ROOT), *options,
                             'credential', operation], input=description, env=repo.env,
                            cwd=ROOT, text=True, encoding='utf-8', errors='replace',
                            stdout=subprocess.PIPE)
    if result.returncode:
        raise GitError('No se pudo obtener o guardar el acceso protegido de GitHub. '
                       'No se ha creado el repositorio.', result.returncode)
    return result.stdout


def offer_github_creation(repo, remote_name):
    check_secret(ROOT.name.encode('utf-8'))
    check_publication(repo)
    check_publication(repo, history=True)
    url = repo.run('remote', 'get-url', '--push', remote_name, capture=True).stdout.strip()
    check_repository_url(url)
    parsed = urlsplit(url)
    parts = unquote(parsed.path).strip('/').split('/')
    if parsed.scheme != 'https' or parsed.hostname != 'github.com' or parsed.port not in (None, 443) or len(parts) != 2:
        raise GitError('La creación automática requiere el destino HTTPS de GitHub de este proyecto.')
    owner = parts[0]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*', owner):
        raise GitError('La cuenta del repositorio no es válida.', 2)
    print('Comprobando la cuenta autorizada y si falta el repositorio en GitHub...', flush=True)
    options = secure_access(repo)
    description = 'protocol=https\nhost=github.com\npath=' + parsed.path.strip('/') + '\n\n'
    record = git_credential(repo, options, 'fill', description)
    fields = dict(line.split('=', 1) for line in record.splitlines() if '=' in line)
    token = fields.get('password', '')
    if not token or fields.get('host') != 'github.com' or fields.get('protocol') != 'https':
        raise GitError('No se pudo verificar el acceso a GitHub; no se ha creado el repositorio.')
    status, user = github_request('GET', '/user', token)
    if status != 200 or not isinstance(user.get('login'), str):
        raise GitError('GitHub no ha validado la cuenta autorizada (HTTP ' + str(status) + ').')
    print('Cuenta autorizada en GitHub: ' + user['login'])
    if user['login'].casefold() != owner.casefold():
        raise GitError('La cuenta autorizada no es la propietaria del destino. '
                       'Use la cuenta propietaria o configure su propio origin con la opción avanzada 10.')
    # Preserve the valid credential only in the selected wallet or memory cache.
    git_credential(repo, options, 'approve', record.rstrip('\n') + '\n\n')
    repository_path = '/repos/' + quote(owner, safe='') + '/' + quote(ROOT.name, safe='')
    status, existing = github_request('GET', repository_path, token)
    if status == 200:
        print('El repositorio ya existe en su cuenta. Se reintentará la subida.')
        return True
    if status != 404:
        raise GitError('No se puede confirmar que falte el repositorio (HTTP ' + str(status) + '). '
                       'No se ha intentado crearlo.')
    print('El repositorio no existe en su cuenta: ' + owner + '/' + ROOT.name)
    try:
        answer = input('¿Lo creo? 1 Privado | 2 Público | 0 No crear [0]: ').strip().casefold()
    except EOFError:
        answer = '0'
    if answer in ('', '0', 'n', 'no'):
        print('Creación cancelada. El commit local se conserva.')
        return False
    if answer not in ('1', 'privado', '2', 'publico', 'público'):
        raise GitError('Elija 1 para privado, 2 para público o 0 para no crear.', 2)
    private = answer in ('1', 'privado')
    visibility = 'privado' if private else 'público'
    print('Se creará ' + owner + '/' + ROOT.name + ' (' + visibility + '), sin archivos iniciales.')
    status, created = github_request('POST', '/user/repos', token,
                                     {'name': ROOT.name, 'private': private, 'auto_init': False})
    if status != 201 or created.get('private') is not private:
        raise GitError('GitHub no ha confirmado la creación con la visibilidad solicitada (HTTP ' + str(status) + '). '
                       'No se continuará con la subida.')
    if str(created.get('full_name', '')).casefold() != (owner + '/' + ROOT.name).casefold():
        raise GitError('GitHub devolvió un destino distinto del solicitado; subida detenida.')
    print('[REPOSITORIO CREADO] ' + owner + '/' + ROOT.name + ' (' + visibility + ')', flush=True)
    return True


def push_branch(repo, remote_name, destination, *, set_upstream=False):
    args = ['-c', 'remote.' + remote_name + '.mirror=false', 'push']
    if set_upstream:
        args.append('--set-upstream')
    args += ['--', remote_name, 'HEAD:' + destination]
    try:
        repo.run(*args)
    except RemoteNotFound:
        if not offer_github_creation(repo, remote_name):
            raise GitError('No se ha creado el destino ni completado la subida.')
        print('Reintentando la subida al repositorio de GitHub...', flush=True)
        previous_confirmation = repo.confirm
        repo.confirm = False
        try:
            repo.run(*args)
        finally:
            repo.confirm = previous_confirmation


def preferred_remote(repo, branch, remotes):
    if branch:
        value = repo.run('config', '--get', 'branch.' + branch + '.remote', capture=True, required=False)
        if value.returncode == 0 and value.stdout.strip():
            if value.stdout.strip() not in remotes:
                raise GitError('La rama sigue un remoto no configurado; revise origin con la opción 10.')
            return value.stdout.strip()
    if 'origin' in remotes:
        return 'origin'
    if len(remotes) == 1:
        return remotes[0]
    raise GitError('Seleccione un remoto explícito; elija 10 para configurar origin.')


def validate_arguments(action, args):
    if action in READ_ACTIONS | {'init', 'fetch', 'pull'} and args:
        raise GitError('Esta operación no admite argumentos adicionales.', 2)
    if action == 'add':
        if not args or any(a.startswith('-') for a in args):
            raise GitError('Indique rutas para add; no se admiten opciones ni preparación forzada.', 2)
        for value in args:
            target = (ROOT / value).resolve()
            if target != ROOT and ROOT not in target.parents:
                raise GitError('Las rutas de add deben permanecer dentro de VED-SYNC.', 2)
            if target == ROOT / '.git' or ROOT / '.git' in target.parents:
                raise GitError('No se preparan metadatos .git como contenido.', 2)
    if action == 'commit':
        # An explicit message only: never implicitly stage tracked files via -a.
        if len(args) != 2 or args[0] not in ('-m', '--message') or not args[1].strip():
            raise GitError('Uso: commit --autorizar -m "Mensaje". Solo se confirma lo ya preparado.', 2)
    if action == 'push':
        positional = args[1:] if args and args[0] in ('-u', '--set-upstream') else args
        if args and args[0] in ('-u', '--set-upstream') and len(positional) != 2:
            raise GitError('Uso: push --autorizar -u REMOTO RAMA_ACTUAL.', 2)
        if len(positional) > 2 or any(a.startswith('-') or ':' in a or a.startswith('+') for a in positional):
            raise GitError('Push admite [-u] [REMOTO [RAMA]], sin forzar, borrar ni refspecs.', 2)
    if action == 'remote':
        if not args or args[0] not in ('add', 'remove', 'rename', 'set-url', 'get-url', 'show'):
            raise GitError('remote requiere add, remove, rename, set-url, get-url o show.', 2)
        # `remote show` is local unless the user explicitly uses fetch/pull/push.
        if args[0] == 'show' and any(a.startswith('-') for a in args[1:]):
            raise GitError('remote show no admite opciones adicionales.', 2)
        if args[0] in ('add', 'set-url'):
            if len(args) != 3 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', args[1]):
                raise GitError('Use remote add/set-url NOMBRE URL, sin opciones adicionales.', 2)
            check_repository_url(args[2])


def offer_repository_creation():
    """The first interactive launch requires an affirmative answer before init."""
    if (ROOT / '.git').exists():
        return 0
    print('No existe un repositorio Git propio en: ' + str(ROOT), flush=True)
    try:
        answer = input(f'¿Quieres crear el repositorio Git de {ROOT.name}? [s/N]: ').strip().casefold()
    except EOFError:
        answer = ''
    except KeyboardInterrupt:
        print('\nCreación cancelada.')
        return 130
    if answer not in ('s', 'si', 'sí', 'y', 'yes'):
        print('Git no creado. Se conserva el proyecto tal como está.')
        return 0
    if (ROOT / '.git').exists():
        return 0
    return main(['init', '--autorizar'])


def main(argv=None, *, confirm=False):
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (['menu'], ['--menu']) or not args and sys.stdin.isatty():
        return menu()
    if args in (['avanzado'], ['advanced']):
        return advanced_menu()
    if args and args[0] in ('--help', '-h', 'help'):
        print(HELP)
        return 0
    action = args.pop(0) if args else 'status'
    if action not in READ_ACTIONS | WRITE_ACTIONS:
        print('Operación desconocida.\n' + HELP, file=sys.stderr)
        return 2
    if action in WRITE_ACTIONS:
        if not args or args.pop(0) != '--autorizar':
            print('Esta operación requiere --autorizar. No se ha ejecutado ninguna escritura.', file=sys.stderr)
            return 2
    try:
        validate_arguments(action, args)
        if action != 'init' and not (ROOT / '.git').exists():
            if not sys.stdin.isatty():
                raise GitError('No hay repositorio Git propio en VED-SYNC. No se utilizará SRC-VED ni otro repositorio padre. '
                               'Ejecute ./proyecto/git.sh menu para decidir si quiere crearlo.')
            code = offer_repository_creation()
            if code != 0 or not (ROOT / '.git').exists():
                return code
        repo = Repository()
        repo.confirm = confirm
        if action == 'init':
            if (ROOT / '.git').exists():
                repo.check_root()
                repo.preview()
                raise GitError('El repositorio ya existe; init no se ejecutará sobre metadatos presentes.')
            print('No hay repositorio local. Se ha solicitado inicializar VED-SYNC explícitamente.', flush=True)
            repo.run('init', '.')
            return 0
        repo.check_root()
        if action == 'push':
            head = repo.run('rev-parse', '--verify', 'HEAD', capture=True, required=False)
            if head.returncode:
                raise GitError('Todavía no hay commits. Elija 6 para crear el primer commit con lo preparado; '
                               'después configure el remoto con 10 y publique con 7.')
        branch, remotes, ignored = repo.preview()
        if action in WRITE_ACTIONS and ignored:
            raise GitError('Operación bloqueada: revise los archivos versionados excluidos antes de continuar.')
        if action in ('commit', 'pull', 'push') and not branch:
            raise GitError('Operación bloqueada con HEAD separado; seleccione una rama antes de continuar.')
        if action in ('fetch', 'pull', 'push') and not remotes:
            raise GitError('No hay remoto configurado. Elija 10 para configurar origin para ' + ROOT.name + '.')
        if action == 'status':
            return 0
        if action == 'diff':
            repo.run('diff', '--', '.')
            repo.run('diff', '--cached', '--', '.')
        elif action == 'log':
            repo.run('log', '-10', '--oneline')
        elif action == 'pull':
            changes = repo.run('status', '--porcelain', capture=True).stdout
            if changes:
                raise GitError('Hay cambios pendientes. Revise y resuélvalos antes de pull; no se hará stash automático.')
            upstream = repo.run('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}', capture=True, required=False)
            if upstream.returncode:
                raise GitError('La rama no tiene seguimiento remoto; configúrelo explícitamente antes de pull.')
            check_remote(repo, preferred_remote(repo, branch, remotes))
            repo.run('pull', '--ff-only')
        elif action == 'fetch':
            remote_name = preferred_remote(repo, branch, remotes)
            check_remote(repo, remote_name)
            repo.run('fetch', remote_name)
        elif action == 'add':
            repo.run('add', '--', *args)
        elif action == 'push':
            positional = args[1:] if args and args[0] in ('-u', '--set-upstream') else args
            if positional and positional[0] not in remotes:
                raise GitError('Push requiere un nombre de remoto configurado, no una URL nueva.')
            if not positional:
                remote = repo.run('config', '--get', 'branch.' + branch + '.remote', capture=True, required=False)
                merge = repo.run('config', '--get', 'branch.' + branch + '.merge', capture=True, required=False)
                if remote.returncode or merge.returncode or remote.stdout.strip() not in remotes or not merge.stdout.strip().startswith('refs/heads/'):
                    raise GitError('Sin seguimiento remoto: indique push --autorizar -u REMOTO RAMA.')
                destination = merge.stdout.strip()
                remote_name = remote.stdout.strip()
            else:
                remote_name = positional[0]
                if len(positional) == 2 and positional[1] != branch:
                    raise GitError('Push solo publica la rama actual; no se publicará otra rama por error.')
                destination = 'refs/heads/' + branch
            # A single explicit refspec avoids push.default=matching or configured push refspecs.
            check_remote(repo, remote_name, push=True)
            options = ['--set-upstream'] if args and args[0] in ('-u', '--set-upstream') else []
            push_branch(repo, remote_name, destination, set_upstream=bool(options))
        elif action == 'remote':
            repo.run('remote', *(['show', '-n', *args[1:]] if args[0] == 'show' else args))
        else:
            repo.run(action, *args)
        return 0
    except GitError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    except (OSError, KeyboardInterrupt) as exc:
        print('Operación interrumpida.' if isinstance(exc, KeyboardInterrupt) else 'No se pudo ejecutar Git: ' + type(exc).__name__, file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1


def configure_remote():
    """Configure origin locally; the project name is derived from its own folder."""
    try:
        repo = Repository()
        repo.check_root()
        remotes = repo.run('remote', capture=True).stdout.splitlines()
        print('Proyecto: ' + str(ROOT))
        print('Repositorio GitHub: ' + ROOT.name)
        value = input('Usuario/organización de GitHub, o URL del repositorio (Intro cancela): ').strip()
        if not value:
            print('Configuración cancelada.')
            return 0
        if '://' in value or re.match(r'^[^\s]+@[^\s]+:', value):
            url = value
        else:
            owner = value.removeprefix('@')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*', owner):
                raise GitError('Indique una cuenta de GitHub o la URL del repositorio.', 2)
            url = 'https://github.com/' + owner + '/' + quote(ROOT.name, safe='') + '.git'
        check_repository_url(url)
        action = 'set-url' if 'origin' in remotes else 'add'
        code = main(['remote', '--autorizar', action, 'origin', url], confirm=True)
        if code == 0:
            print('Origin configurado. Si falta el repositorio en su cuenta de GitHub, '
                  'al publicar se preguntará si quiere crearlo.')
        return code
    except EOFError:
        print('Configuración cancelada.')
        return 0
    except KeyboardInterrupt:
        print('Configuración interrumpida.')
        return 130
    except (GitError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return exc.code if isinstance(exc, GitError) else 1


def publish_from_menu():
    """First publication explicitly sets tracking for this project's current branch."""
    try:
        repo = Repository()
        repo.check_root()
        head = repo.run('rev-parse', '--verify', 'HEAD', capture=True, required=False)
        if head.returncode:
            print('Todavía no hay commits. Elija 6 para crear el primer commit con lo preparado.')
            return 1
        remotes = repo.run('remote', capture=True).stdout.splitlines()
        if not remotes:
            answer = input('No hay remoto. ¿Quieres configurar origin para ' + ROOT.name + '? [s/N]: ').strip().casefold()
            if answer in ('s', 'si', 'sí', 'y', 'yes'):
                return configure_remote()
            return 0
        branch = repo.run('symbolic-ref', '--quiet', '--short', 'HEAD', capture=True, required=False)
        if branch.returncode:
            raise GitError('Seleccione una rama antes de publicar.')
        upstream = repo.run('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}',
                            capture=True, required=False)
        if upstream.returncode:
            name = preferred_remote(repo, branch.stdout.strip(), remotes)
            return main(['push', '--autorizar', '-u', name, branch.stdout.strip()], confirm=True)
        return main(['push', '--autorizar'], confirm=True)
    except EOFError:
        return 0
    except KeyboardInterrupt:
        return 130
    except (GitError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return exc.code if isinstance(exc, GitError) else 1


def request_missing_identity(repo):
    """Ask for missing commit identity without guessing email or changing globals."""
    identities = [repo.run('var', variable, capture=True, required=False)
                  for variable in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT')]
    for identity in identities:
        check_secret(identity.stdout.encode('utf-8'))
    print('El nombre y correo identifican al autor de cada commit y son visibles en su historial.')
    print('El correo noreply de GitHub permite ocultar su correo personal; no es una contraseña.')
    missing = any(identity.returncode for identity in identities)
    if not missing:
        author = identities[0].stdout.strip().rsplit('>', 1)[0] + '>'
        print('Se reutilizará la identidad configurada en Git: ' + author)
        return {}, False
    print('Falta la identidad para crear commits.')
    settings = {}
    for key, prompt in (
            ('user.name', 'Su nombre o alias para los commits: '),
            ('user.email', 'Correo para los commits de este proyecto: ')):
        result = repo.run('config', '--get', key, capture=True, required=False)
        if result.returncode == 0 and result.stdout.strip():
            continue
        value = input(prompt).strip()
        check_secret(value.encode('utf-8'))
        if not value or any(c in value for c in '\r\n\0<>'):
            raise GitError('Indique un nombre y un correo válidos. No se han cambiado archivos.', 2)
        if key == 'user.email' and not re.fullmatch(r'[^@\s]+@[^@\s]+', value):
            raise GitError('El correo debe tener el formato usuario@dominio. No se ha creado el commit.', 2)
        settings[key] = value
        print(key + ': ' + value)
    remember = input('¿Guardar y reutilizar estos datos sólo en este proyecto? [S/n]: ').strip().casefold()
    if remember not in ('', 's', 'si', 'sí', 'y', 'yes', 'n', 'no'):
        raise GitError('Responda s para guardar o n para usar los datos sólo esta vez.', 2)
    return settings, remember not in ('n', 'no')


def upload_changes():
    """Author's familiar workflow: prepare, commit and publish in one requested operation."""
    repo = None
    before = ''
    root_verified = False
    try:
        repo = Repository()
        repo.check_root()
        root_verified = True
        old = repo.run('rev-parse', '--verify', 'HEAD', capture=True, required=False)
        before = old.stdout.strip() if old.returncode == 0 else ''
        branch_result = repo.run('symbolic-ref', '--quiet', '--short', 'HEAD', capture=True, required=False)
        branch = branch_result.stdout.strip()
        if branch_result.returncode or not branch:
            raise GitError('Seleccione una rama antes de subir cambios.')
        ignored = repo.run('ls-files', '-z', '-ci', '--exclude-standard', capture=True).stdout
        if ignored:
            raise GitError('Hay archivos excluidos preparados o versionados. Revise la limpieza antes de subir.')
        remotes = repo.run('remote', capture=True).stdout.splitlines()
        remote_name = 'origin' if 'origin' in remotes or not remotes else preferred_remote(repo, branch, remotes)
        create_remote = not remotes
        if create_remote:
            account = input('Su cuenta de GitHub (o URL del repositorio): ').strip()
            if '://' in account or re.match(r'^[^\s]+@[^\s]+:', account):
                url = account
            elif re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*', account):
                url = 'https://github.com/' + account + '/' + quote(ROOT.name, safe='') + '.git'
            else:
                raise GitError('Indique su cuenta o la URL del repositorio de este proyecto.', 2)
            check_repository_url(url)
        else:
            check_remote(repo, remote_name)
            check_remote(repo, remote_name, push=True)
            url = repo.run('remote', 'get-url', '--push', remote_name, capture=True).stdout.strip()
        print('\nSUBIR CAMBIOS: preparar + commit + push')
        print('Proyecto: ' + str(ROOT))
        print('Destino: ' + url)
        print('Rama: ' + branch)
        identity, remember_identity = request_missing_identity(repo)
        message = input('Mensaje del commit (Intro = actualización con fecha): ').strip()
        message = message or 'Actualización ' + ROOT.name + ' - ' + datetime.now().strftime('%Y-%m-%d %H:%M')
        print('Mensaje: ' + message)
        answer = input('¿Preparar, crear el commit y subir estos cambios? [s/N]: ').strip().casefold()
        if answer not in ('s', 'si', 'sí', 'y', 'yes'):
            print('Operación cancelada.')
            return 0
        for key, value in identity.items():
            if remember_identity:
                repo.run('config', '--local', key, value)
            suffix = 'NAME' if key == 'user.name' else 'EMAIL'
            repo.env['GIT_AUTHOR_' + suffix] = value
            repo.env['GIT_COMMITTER_' + suffix] = value
        if identity:
            if remember_identity:
                print('Identidad guardada en la configuración local de Git. Se reutilizará en este proyecto.')
            else:
                print('Identidad sólo para esta ejecución; no se ha guardado en la configuración de Git.')
        if create_remote:
            repo.run('remote', 'add', remote_name, url)
        print('[1/3] Preparando archivos...', flush=True)
        repo.run('add', '--', '.')
        changed = repo.run('diff', '--cached', '--quiet', '--exit-code', capture=True, required=False)
        if changed.returncode not in (0, 1):
            raise GitError('No se pudo comprobar lo preparado.', changed.returncode)
        if changed.returncode == 1:
            print('[2/3] Creando commit...', flush=True)
            result = repo.run('commit', '-m', message, capture=True, required=False)
            if result.returncode:
                print(result.stderr or result.stdout, file=sys.stderr)
                raise GitError('No se pudo crear el commit.', result.returncode)
            head = repo.run('rev-parse', '--verify', 'HEAD', capture=True).stdout.strip()
            print('[COMMIT CREADO] ' + head[:12], flush=True)
        elif before:
            head = before
            print('[SIN CAMBIOS NUEVOS] Commit local: ' + head[:12], flush=True)
        else:
            print('[SIN COMMIT] No hay archivos que confirmar. No se ha publicado nada.')
            return 0
        print('[3/3] Subiendo a ' + url + '...', flush=True)
        push_branch(repo, remote_name, 'refs/heads/' + branch, set_upstream=True)
        print('[SUBIDA COMPLETADA] Commit ' + head[:12] + ' en ' + ROOT.name + ' / ' + branch, flush=True)
        return 0
    except EOFError:
        print('Operación cancelada.')
        return 0
    except (GitError, OSError, KeyboardInterrupt) as exc:
        print('[SUBIDA NO COMPLETADA] ' + str(exc), file=sys.stderr)
        if repo is not None and root_verified:
            current = repo.run('rev-parse', '--verify', 'HEAD', capture=True, required=False)
            if current.returncode == 0:
                label = '[COMMIT CREADO Y CONSERVADO LOCALMENTE] ' if current.stdout.strip() != before else '[COMMIT LOCAL] '
                print(label + current.stdout.strip()[:12], flush=True)
            else:
                print('[NO SE HA CREADO NINGÚN COMMIT]', flush=True)
        return 130 if isinstance(exc, KeyboardInterrupt) else exc.code if isinstance(exc, GitError) else 1


def menu():
    """Same simple menu as the author's project BATs, shared by Ubuntu and Windows."""
    if not (ROOT / '.git').exists():
        code = offer_repository_creation()
        if code != 0 or not (ROOT / '.git').exists():
            return code
    while True:
        print('\nGIT - ' + ROOT.name + '''
  1 VER ESTADO
  2 SUBIR CAMBIOS (preparar + commit + push)
  3 LIMPIEZA LOCAL
  4 INFORMACIÓN
  5 SALIR
  6 OPERACIONES AVANZADAS
''', flush=True)
        try:
            option = input('Elija una operación [1-6, Intro = salir]: ').strip()
            if option in ('', '0', '5'):
                return 0
            if option == '1':
                main(['status'])
            elif option == '2':
                upload_changes()
            elif option == '3':
                script = ROOT / 'limpieza.sh'
                if script.is_file() and os.name == 'posix':
                    subprocess.run(['bash', str(script)], cwd=ROOT, check=False)
                else:
                    print('Use la limpieza propia del proyecto; los archivos locales se conservan.')
            elif option == '4':
                print('Proyecto: ' + str(ROOT))
                print('Repositorio: ' + ROOT.name)
                print('El destino es el remoto de esta copia; si falta, se pide la cuenta o URL del usuario.')
                print('Los tokens se gestionan con Git y el almacén del sistema, fuera del proyecto.')
                print('La opción 2 prepara, crea el commit y publica. Cada resultado se indica por separado.')
            elif option == '6':
                advanced_menu()
            else:
                print('Elija una opción del 1 al 6.')
        except EOFError:
            return 0
        except KeyboardInterrupt:
            return 130


def advanced_menu():
    """A stable project can be published in explicit, individually reviewed steps."""
    if not (ROOT / '.git').exists():
        code = offer_repository_creation()
        if code != 0 or not (ROOT / '.git').exists():
            return code
    main(['status'])
    choices = {'1': ('status', False), '2': ('diff', False), '3': ('log', False),
               '4': ('pull', True), '5': ('add', True), '6': ('commit', True),
               '7': ('push', True), '8': ('fetch', True), '9': ('init', True), '10': ('remote', True)}
    while True:
        print("""
VED-SYNC: Git de este proyecto exclusivamente
  1 Estado y rama             2 Ver diferencias
  3 Ultimos commits          4 Actualizar desde remoto (avance rapido)
  5 Preparar cambios         6 Crear commit de lo preparado
  7 Publicar rama actual     8 Consultar cambios remotos (fetch)
  9 Inicializar Git propio   0 Salir
 10 Configurar origin para el repositorio de este proyecto
No se encadenan preparación, commit y publicación.
""", flush=True)
        try:
            option = input('Elija una operación: ').strip()
            if option in ('', '0'):
                return 0
            if option not in choices:
                print('Opción no válida.')
                continue
            if option in ('7', '10'):
                code = publish_from_menu() if option == '7' else configure_remote()
                print('Operación finalizada.' if code == 0 else 'La operación no se completó; revise el mensaje anterior.', flush=True)
                continue
            action, write = choices[option]
            arguments = [action, '--autorizar'] if write else [action]
            if action == 'add':
                path = input('Ruta relativa que preparar (Intro = todo el proyecto): ').strip() or '.'
                arguments.append(path)
            elif action == 'commit':
                message = input('Mensaje del commit: ')
                if not message.strip():
                    print('No se creará un commit sin mensaje.')
                    continue
                arguments.extend(['-m', message])
            code = main(arguments, confirm=write)
            print('Operación finalizada.' if code == 0 else 'La operación no se completó; revise el mensaje anterior.', flush=True)
        except EOFError:
            print('Entrada cerrada; no se ejecutarán más operaciones.')
            return 0
        except KeyboardInterrupt:
            print('Menú interrumpido; no se ejecutarán más operaciones.')
            return 130


if __name__ == '__main__':
    raise SystemExit(main())
