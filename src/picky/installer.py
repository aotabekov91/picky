import os
import shutil
import typing as tp

from .gitops import GitOps
from .requirements import RequirementInstaller
from .log import Logger, NullLogger


class PickInstaller:

    def __init__(self, folder: str,
                 requirements: RequirementInstaller,
                 logger: tp.Optional[Logger] = None):
        self.folder = folder
        self.req = requirements
        self.log = logger or NullLogger()

    def install(self, pick: dict) -> bool:
        """Install one pick. Returns True on success, False on failure."""
        plug = pick['plug']
        base = pick['base']
        name = pick['folder']
        path = os.path.join(self.folder, name)

        if os.path.exists(path):
            self.log.debug('install', f'{name}: already present', plugin=name)
            self._apply_ref(pick, path)
            result = self.req.install(name, self.folder, name)
            if result is None:
                self.log.error('install',
                               f'{name}: requirements install failed',
                               plugin=name)
                return False
            return True

        pick_base = os.path.expanduser(base)
        if os.path.isdir(pick_base):
            ok = self._install_local(pick, pick_base, path)
        else:
            ok = self._install_remote(pick, pick_base, path)

        if not ok:
            return False

        self._apply_ref(pick, path)
        result = self.req.install(name, self.folder, name)
        if result is None:
            self.log.error('install',
                           f'{name}: requirements install failed',
                           plugin=name)
            return False
        self.log.success('install', f'{name}: installed', plugin=name)
        return True

    def _install_local(self, pick, pick_base, path) -> bool:
        plug = pick['plug']
        src = os.path.join(pick_base, plug)
        if not os.path.exists(src):
            self.log.error('install',
                           f'{pick["folder"]}: local base has no {plug}',
                           plugin=pick['folder'])
            return False
        kind = pick.get('kind', 'copy')
        if kind == 'copy':
            shutil.copytree(src, path)
        elif kind == 'link':
            os.symlink(src, path)
        else:
            self.log.error('install',
                           f'{pick["folder"]}: unknown kind {kind!r}',
                           plugin=pick['folder'])
            return False
        return True

    def _install_remote(self, pick, pick_base, path) -> bool:
        url = f"{pick_base}/{pick['plug']}"
        try:
            GitOps.clone(url, path)
            return True
        except Exception as e:
            self.log.error('install',
                           f'{pick["folder"]}: clone {url} failed: {e}',
                           plugin=pick['folder'])
            shutil.rmtree(path, ignore_errors=True)
            return False

    def _apply_ref(self, pick, path):
        branch = pick.get('branch')
        commit = pick.get('commit')
        if branch:
            GitOps.checkout_branch(path, branch)
        if commit:
            GitOps.checkout_commit(path, commit)

    def update(self, name: str) -> bool:
        """``git pull`` for the pick at ``<folder>/<name>``."""
        path = os.path.join(self.folder, name)
        if not GitOps.is_repo(path):
            self.log.debug('update', f'{name}: not a git repo, skip',
                           plugin=name)
            return False
        try:
            GitOps.pull(path)
            self.log.success('update', f'{name}: pulled', plugin=name)
            return True
        except Exception as e:
            self.log.error('update', f'{name}: pull failed: {e}',
                           plugin=name)
            return False

    def remove(self, name: str) -> None:
        """Wipe a pick's source dir AND its per-plugin site-packages."""
        path = os.path.join(self.folder, name)
        if os.path.islink(path):
            os.unlink(path)
        elif os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
        self.req.remove(name)
        self.log.info('remove', f'{name}: wiped source + site-packages',
                      plugin=name)
