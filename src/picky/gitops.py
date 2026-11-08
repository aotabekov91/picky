import git


class GitOps:
    """All GitPython calls live here. Picky never imports ``git`` directly."""

    @staticmethod
    def clone(url, path):
        return git.Repo.clone_from(url, path)

    @staticmethod
    def open(path):
        """Return a ``git.Repo`` for ``path`` or ``None`` if not a repo."""
        try:
            repo = git.Repo(path)
            return None if repo.bare else repo
        except git.exc.InvalidGitRepositoryError:
            return None
        except git.exc.NoSuchPathError:
            return None

    @staticmethod
    def is_repo(path):
        return GitOps.open(path) is not None

    @staticmethod
    def pull(path):
        """Pull from every remote. Returns list of fetch info."""
        repo = git.Repo(path)
        info = []
        for remote in repo.remotes:
            info.append(remote.pull())
        return info

    @staticmethod
    def checkout_branch(path, branch):
        """Check out a branch by name."""
        repo = GitOps.open(path)
        if repo is None:
            return False
        try:
            repo.git.checkout(branch)
            return True
        except git.exc.GitCommandError:
            return False

    @staticmethod
    def checkout_commit(path, commit):
        """Check out a specific commit SHA. Returns True if found."""
        repo = GitOps.open(path)
        if repo is None:
            return False
        for head in repo.iter_commits():
            if head.hexsha == commit:
                repo.git.checkout(head)
                return True
        return False
