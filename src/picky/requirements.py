"""Per-plugin pip installer with isolated --target dirs.

Each plugin's deps live in ``<base_dir>/<plugin_name>/``. Removing a
plugin wipes its deps automatically.

Plugin deps are declared in a plain ``requirements.txt`` at the plugin's
repo root (standard pip format). One spec per line, comments with ``#``.
"""
import os
import sys
import site
import shutil
import subprocess
import threading

from .log import Logger, NullLogger, LogLevel


class RequirementInstaller:
    """Install each plugin's requirements.txt into its own site-packages dir."""

    _pip_lock = threading.Lock()  # pip is not thread-safe

    def __init__(self, base_dir, logger=None, pip_args=None):
        self.base_dir = base_dir
        self.log = logger or NullLogger()
        self.pip_args = list(pip_args or ['install', '-q'])
        os.makedirs(base_dir, exist_ok=True)

    # ── paths ────────────────────────────────────────────────────────────
    def target_for(self, name):
        """Return ``<base_dir>/<name>``, creating it. Use only when you're
        about to put something in it."""
        path = os.path.join(self.base_dir, name)
        os.makedirs(path, exist_ok=True)
        return path

    def add_to_path(self, name):
        """Add ``<base_dir>/<name>`` to ``sys.path`` if (and only if) it
        already exists on disk. Does NOT create the dir — callers that
        need it created should use ``target_for`` or ``install``."""
        path = os.path.join(self.base_dir, name)
        if os.path.isdir(path) and path not in sys.path:
            sys.path.append(path)
            site.addsitedir(path)

    # ── removal ──────────────────────────────────────────────────────────
    def remove(self, name):
        shutil.rmtree(os.path.join(self.base_dir, name), ignore_errors=True)

    # ── requirements discovery ───────────────────────────────────────────
    @staticmethod
    def read_requirements(folder, module):
        """Read ``<folder>/<module>/requirements.txt`` and return a list of
        pip-installable spec strings (one per non-empty, non-comment line).

        Returns ``[]`` if the file doesn't exist. Pip option lines (those
        starting with ``-``) are skipped — use the ``pip_args`` constructor
        parameter to set global pip options instead.
        """
        req_file = os.path.join(folder, module, 'requirements.txt')
        if not os.path.exists(req_file):
            return []
        specs = []
        with open(req_file, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # Skip pip option lines (--index-url, -r, -e, etc.)
                if line.startswith('-'):
                    continue
                # Strip inline comments (space+#). Preserve URL fragments
                # like ``#egg=foo`` since those have no preceding space.
                if ' #' in line:
                    line = line.split(' #', 1)[0].rstrip()
                specs.append(line)
        return specs

    @staticmethod
    def packages_in(target):
        """Set of dist names installed in a ``--target`` dir."""
        out = set()
        if not os.path.isdir(target):
            return out
        for entry in os.listdir(target):
            if not entry.endswith('.dist-info'):
                continue
            meta = os.path.join(target, entry, 'METADATA')
            if not os.path.exists(meta):
                continue
            with open(meta, encoding='utf-8', errors='replace') as f:
                for line in f:
                    if line.lower().startswith('name:'):
                        out.add(line.split(':', 1)[1].strip().lower())
                        break
        return out

    @staticmethod
    def _pkg_name_from_spec(spec):
        """Extract the canonical (lowercase, dash-separated) package name
        from a pip-installable spec string. Returns ``None`` if it can't
        be parsed (VCS URLs, local paths).

            'pyzmq==26.2.0'              → 'pyzmq'
            'requests>=2.20'             → 'requests'
            'requests[socks]>=2.20'      → 'requests'
            'flask~=2.0; python_version>="3.9"' → 'flask'
            'git+https://github.com/...' → None
            './local/pkg'                → None
        """
        if spec.startswith(('git+', 'hg+', 'svn+', 'bzr+')):
            return None
        if spec.startswith(('./', '/', '..', '\\')):
            return None
        if '://' in spec:
            return None
        name = spec
        # Strip extras
        if '[' in name:
            name = name[:name.index('[')]
        # Strip environment markers
        if ';' in name:
            name = name[:name.index(';')]
        # Strip version specifiers (check 2-char ops first)
        for op in ('==', '>=', '<=', '!=', '~=', '<', '>'):
            idx = name.find(op)
            if idx != -1:
                name = name[:idx]
                break
        name = name.strip().replace('_', '-').lower()
        return name or None

    # ── install ──────────────────────────────────────────────────────────
    def install(self, name, folder, module):
        """Install ``module``'s requirements.txt into ``name``'s site-packages.

        Returns:
        - ``[]``  — no requirements.txt, or all deps already present (success).
        - ``list`` — specs that were installed (success).
        - ``None`` — pip failed. Caller should treat the plugin as not
          properly installed and skip loading it.
        """
        specs = self.read_requirements(folder, module)
        if not specs:
            return []

        target = self.target_for(name)
        # Always make the dir importable once it exists on disk.
        self.add_to_path(name)

        present = self.packages_in(target)
        to_install = []
        for spec in specs:
            pkg_name = self._pkg_name_from_spec(spec)
            # If we can't parse the name (VCS URL, local path), always install.
            if pkg_name is None or pkg_name not in present:
                to_install.append(spec)
        if not to_install:
            self.log.debug('pip', f'{name}: all requirements satisfied',
                           plugin=name)
            return []

        cmd = self._build_cmd(to_install, target)
        with RequirementInstaller._pip_lock:
            rc = self._run(cmd, plugin=name)
        if rc != 0:
            # pip failed — do NOT pretend everything is fine.
            return None
        return to_install

    # ── pip plumbing ─────────────────────────────────────────────────────
    def _build_cmd(self, packages, target):
        cmd = [sys.executable, '-m', 'pip'] + self.pip_args
        cmd += ['--target', target,
                '--disable-pip-version-check',
                '--no-warn-script-location']
        return cmd + packages

    def _run(self, cmd, plugin=None):
        """Run a pip command, streaming its output to ``self.log``.

        Returns the pip exit code (0 = success, non-zero = failure).

        On non-zero exit, the captured pip output is ALSO written to
        stderr directly — so failures are always debuggable even when
        the plugged-in logger is silent (e.g. NullLogger).
        """
        self.log.info('pip', f'Running: {" ".join(cmd)}', plugin=plugin)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            self.log.error('pip', f'pip not found at {sys.executable}',
                           plugin=plugin)
            sys.stderr.write(f'[pip] pip not found at {sys.executable}\n')
            return 127

        captured = []
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            captured.append(line)
            method = {
                LogLevel.ERROR: self.log.error,
                LogLevel.WARN: self.log.warn,
                LogLevel.SUCCESS: self.log.success,
                LogLevel.INFO: self.log.info,
                LogLevel.DEBUG: self.log.debug,
            }[self._level(line)]
            method('pip', line, plugin=plugin)

        proc.wait()
        if proc.returncode == 0:
            self.log.success('pip', 'install OK', plugin=plugin)
        else:
            msg = f'pip exited with code {proc.returncode}'
            self.log.error('pip', msg, plugin=plugin)
            # ALWAYS surface the failure to stderr, even with NullLogger.
            sys.stderr.write(f'\n[pip:{plugin}] {msg}\n')
            sys.stderr.write(f'[pip:{plugin}] cmd: {" ".join(cmd)}\n')
            for line in captured:
                sys.stderr.write(f'[pip:{plugin}] {line}\n')
            sys.stderr.write('\n')
            sys.stderr.flush()
        return proc.returncode

    @staticmethod
    def _level(line):
        low = line.lower()
        if 'error' in low or 'failed' in low or 'could not find' in low:
            return LogLevel.ERROR
        if 'warning' in low or 'deprecated' in low:
            return LogLevel.WARN
        if 'successfully installed' in low or 'already satisfied' in low:
            return LogLevel.SUCCESS
        return LogLevel.INFO
