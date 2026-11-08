import os
import typing as tp

from nara import Plug, tag, deleg

from .gitops import GitOps
from .installer import PickInstaller
from .requirements import RequirementInstaller
from .log import Logger, NullLogger, PrintLogger

class Picky(Plug):

    base = 'https://github.com'

    def setup(self):
        super().setup()
        # Print to stdout/stderr by default so pip output is visible in
        # interactive use. Swap for NullLogger or an EmitterLogger via
        # setLogger() in production / GUI contexts.
        self.log: Logger = PrintLogger()
        self.addPicksFolder()
        self.req = RequirementInstaller(
            base_dir=self._site_packages_dir(),
            logger=self.log,
        )
        self.installer = PickInstaller(self.folder, self.req, self.log)
        self.loadPicks()

    def setLogger(self, logger: Logger):
        """Swap the logger post-setup."""
        self.log = logger
        self.installer.log = logger
        self.req.log = logger

    def addPicksFolder(self):
        config_folder = self.app.configman.configFolder()
        path = os.path.join(config_folder, 'picky')
        self.folder = self.app.createFolder(path)

    def _site_packages_dir(self):
        config_folder = self.app.configman.configFolder()
        return os.path.join(config_folder, 'site-packages')

    def loadPicks(self, picks: tp.List[dict] = [],
                  skip: tp.FrozenSet[str] = frozenset()) -> None:
        """Re-apply branch/commit pins + ensure deps importable + load plugs. """
        picks = picks or self.getPicks()
        modules = []
        for pick in picks:
            name = pick['folder']
            if name in skip:
                self.log.warn('load', f'{name}: skipped (install failed)',
                              plugin=name)
                continue
            path = os.path.join(self.folder, name)
            if not os.path.exists(path):
                continue
            modules.append(name)
            if GitOps.is_repo(path):
                if pick.get('branch'):
                    GitOps.checkout_branch(path, pick['branch'])
                if pick.get('commit'):
                    GitOps.checkout_commit(path, pick['commit'])
            self.req.add_to_path(name)
        if not modules:
            return
        # Load each plugin independently so one broken import doesn't
        # take down the whole app.
        loaded = 0
        for name in modules:
            try:
                aset, paths = self.app.plugman.getPlugs(self.folder, [name])
                self.app.plugman.loadKlasses(aset, paths)
                loaded += 1
            except Exception as e:
                self.log.error('load',
                               f'{name}: import failed — skipped ({e})',
                               plugin=name)
        self.log.info('load', f'loaded {loaded}/{len(modules)} picks')

    @deleg('getPickyFolder@(normal){Picky}')
    def getFolder(self):
        return self.folder

    @deleg('getPicks@(normal){Picky}')
    def getPicks(self):
        """Normalize the ``Picks`` config list to dicts with base+folder."""
        plugs = []
        picks = self.m_config.get('Picks', []) or []
        for pick in picks:
            if isinstance(pick, str):
                pick = dict(plug=pick)
            if 'base' not in pick:
                pick['base'] = self.base
            plug = pick.get('plug')
            if not plug or '/' not in plug:
                continue
            pick['folder'] = plug.split('/')[1]
            plugs.append(pick)
        return plugs

    @tag('(exec)')
    def PickyInstall(self):
        # Track which picks failed to install (e.g. pip couldn't install
        # their requirements.txt) so loadPicks can skip them instead of
        # crashing on the missing-import.
        failed = set()
        for pick in self.getPicks():
            if not self.installer.install(pick):
                failed.add(pick['folder'])
        self.loadPicks(skip=frozenset(failed))

    @tag('(exec)')
    def PickyUpdate(self):
        failed = set()
        for pick in self.getPicks():
            if not self.installer.update(pick['folder']):
                failed.add(pick['folder'])
        self.loadPicks(skip=frozenset(failed))

    @tag('(exec)')
    def PickyCleanup(self):
        keep = [p['folder'] for p in self.getPicks()]
        for repo in os.listdir(self.folder):
            if repo.startswith('.') or repo in keep:
                continue
            pick_path = os.path.join(self.folder, repo)
            plugs = self.app.plugman.getPlug(path=pick_path) or []
            for plug in plugs:
                if plug and hasattr(plug, 'tearup'):
                    try:
                        plug.tearup()
                    except Exception as e:
                        self.log.warn('cleanup',
                                      f'{repo}: tearup failed: {e}',
                                      plugin=repo)
            self.installer.remove(repo)
