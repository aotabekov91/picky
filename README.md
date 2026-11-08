# Picky

A **vim-plug–style plugin manager for [nara](https://github.com/aotabekov91/nara)** — declare your plugins in TOML, run one command, and Picky clones them from git, installs their pip dependencies into per-plugin isolated `site-packages/`, and loads them into the app.

If you've used [vim-plug](https://github.com/junegunn/vim-plug) or [packer.nvim](https://github.com/wbthomason/packer.nvim), Picky is the same idea for nara-based Python applications.

---

## What it does

- **Declares plugins in TOML** — a `Picks` list in your app's `config.toml`.
- **Clones from git** — `owner/repo` from GitHub (or any base URL), via GitPython.
- **Or copies/links from a local base** — for development or offline use.
- **Pins branch or commit** — `branch = "main"`, `commit = "<sha>"`.
- **Installs pip deps per-plugin** — each plugin's `requirements.txt` goes into its own `<config>/site-packages/<plugin>/` dir, so deleting a plugin wipes its deps automatically. No orphans.
- **PEP 668-friendly** — uses `pip install --target`, never touches the system Python or the app's venv.
- **Survives broken plugins** — if one plugin's deps fail to install, or its import crashes, the rest of the app keeps running. Failed plugins are logged and skipped.
- **Live pip output** — streams pip's stdout/stderr to a pluggable logger so install progress is visible.
- **Three commands**: `PickyInstall`, `PickyUpdate`, `PickyCleanup`

## Requirements

- Python 3.9+
- [nara](https://github.com/aotabekov91/nara) — the framework Picky plugs into
- [GitPython](https://pypi.org/project/GitPython/) — for git clone/pull/checkout
- [tomli](https://pypi.org/project/tomli/) — for TOML config (usually pulled in by nara)

## Installation

Picky is itself a nara plug. Install it the same way you install any other plug.

### Manual install

```bash
git clone https://github.com/aotabekov91/picky.git ~/.config/<app>/autorun/picky
```

Restart your app — Picky will be auto-loaded by nara's Plugman on next boot.

## Configuration

Picky reads its config from the `Picks` section of your app's `config.toml` (at `<config_dir>/<app>/config.toml`):

```toml
# config.toml

# Each pick is either a string or a table.
Picks = [
  "aotabekov91/leaper",                          # string form — defaults to GitHub
  { plug = "aotabekov91/nara_qt", branch = "main" },   # table form — pin branch
  { plug = "private/repo", base = "https://gitlab.com" },  # custom base
  { plug = "local/exp", base = "~/src", kind = "link" },   # local symlink
]
```

### Pick fields

| Field | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `plug` | string | yes | — | `"owner/repo"`. The repo name becomes the folder name. |
| `base` | string | no | `https://github.com` | URL or local path. If it's a local dir containing `<plug>`, copies or links instead of cloning. |
| `branch` | string | no | (default branch) | Branch to check out after clone. |
| `commit` | string | no | (latest) | Pin to a specific commit SHA. Overrides `branch` if both set. |
| `kind` | string | no | `"copy"` | Only used when `base` is a local dir. `"copy"` = `shutil.copytree`; `"link"` = `os.symlink`. |

## Declaring plugin dependencies

Each plugin declares its pip deps in a plain **`requirements.txt`** at the plugin's repo root — standard pip format:

```
# requirements.txt for myplugin

pyzmq==26.2.0
requests>=2.20
numpy<2.0
flask~=2.0
requests[socks]>=2.20                    # extras
rich>=13.0; python_version >= "3.9"      # env markers

# VCS URL — always re-installed (can't be deduped)
git+https://github.com/me/private.git@v1.0
```

When `PickyInstall` runs:

1. `PickInstaller` clones the plugin repo.
2. `RequirementInstaller` reads the `requirements.txt`.
3. pip is invoked **once per plugin**, batched, with `--target <config>/site-packages/<plugin>/`.
4. The per-plugin `site-packages/` dir is appended to `sys.path` so the plugin can `import` its deps.
5. On `PickyCleanup`, removing a plugin wipes both its source AND its deps — no orphans.

### What's supported in `requirements.txt`

| Feature | Example | Notes |
| --- | --- | --- |
| Pinned version | `pyzmq==26.2.0` | |
| Compound specifiers | `requests>=2.20`, `numpy<2.0`, `flask~=2.0` | All PEP 440 operators |
| Extras | `requests[socks]>=2.20` | |
| Environment markers | `rich>=13.0; python_version >= "3.9"` | Passed through verbatim |
| VCS URLs | `git+https://github.com/me/pkg.git@v1.0` | Always re-installed |
| Local paths | `./local/pkg` | Always re-installed |
| Comments | `# this is a comment` | Skipped |
| Inline comments | `pyzmq==26.2.0  # for messaging` | Stripped (space-`#`) |

Pip option lines starting with `-` (`--index-url`, `-r`, `-e`, etc.) are skipped — set global pip options via the `RequirementInstaller` constructor instead.

## Per-plugin site-packages isolation

Each plugin's deps live in their own directory:

```
~/.config/<app>/
├── picky/
│   ├── myplugin/              ← cloned source
│   │   ├── requirements.txt
│   │   └── src/myplugin/__init__.py
│   └── anotherplug/           ← separate clone
│       ├── requirements.txt
│       └── src/anotherplug/__init__.py
└── site-packages/
    ├── myplugin/              ← pyzmq lives here, ONLY for myplugin
    │   ├── zmq/
    │   └── pyzmq-26.2.0.dist-info
    └── anotherplug/           ← its OWN copy of any shared deps
        ├── zmq/
        └── pyzmq-26.2.0.dist-info
```

**Key behaviors:**

- `add_to_path` **appends** to `sys.path`, not inserts at index 0 — the app venv's deps take precedence. A plugin can *add* new deps but cannot *override* the app's existing ones.
- If a plugin has no `requirements.txt`, no `site-packages/<plugin>/` dir is created — no empty folders.
- `PickyCleanup` wipes both the source dir and the deps dir for any plugin not in the current `Picks` config.

## Commands

Picky exposes three `(exec)` commands in your app:

### `PickyInstall`

Clones every pick in `Picks` that isn't already on disk, installs each one's `requirements.txt`, and loads them into Plugman. Idempotent — re-running picks up newly-added `requirements.txt` entries without re-cloning.

```
PickyInstall
```

### `PickyUpdate`

Runs `git pull` on every pick that's a git repo, then reloads. Picks that fail to pull (e.g. not a git repo) are skipped with a log line.

```
PickyUpdate
```

### `PickyCleanup`

Removes any folder under `picky/` that isn't in the current `Picks` config. For each removed plugin: tears down its plugs (calls `tearup()` if defined), then wipes the source dir AND its per-plugin `site-packages/`. Orphans never linger.

```
PickyCleanup
```

## Logger abstraction

Picky's logging is pluggable via the `Logger` ABC. Three implementations ship in the box:

| Logger | Where | Use case |
| --- | --- | --- |
| `NullLogger` | `picky.log` | Default for headless / test runs. Silent — but pip failures still dump to stderr as a safety net. |
| `PrintLogger` | `picky.log` | Picky's default. Writes `[LEVEL] (stage) message` to stdout (or stderr for ERROR/WARN). |
| `QtLogger` | `picky.logger` | Emits each log line as a Qt signal. Thread-safe — use when integrating with a PyQt6 GUI. |

Swap loggers at runtime:

```python
picky.setLogger(my_custom_logger)
```

This propagates to `picky.installer.log` and `picky.req.log` too, so every layer routes through the same logger.

To write your own, subclass `Logger` and implement `log(level, stage, message, plugin=None)`. The convenience methods (`debug`, `info`, `success`, `warn`, `error`) come for free.

## Failure handling

Picky is designed so one broken plugin never crashes the whole app:

1. **pip failure propagation** — if `pip install` exits non-zero for a plugin's `requirements.txt`, `RequirementInstaller.install()` returns `None`, `PickInstaller.install()` returns `False`, and `PickyInstall` adds the plugin to a `failed` set. `loadPicks(skip=failed)` then skips loading that plugin entirely.

2. **Per-plugin load isolation** — `loadPicks()` loads each plugin independently with `try/except`. If a plugin's import fails (e.g. missing dep, syntax error), it's logged and the rest still load:

   ```
   [ERROR] [myplugin] (load) myplugin: import failed — skipped (ModuleNotFoundError: No module named 'zmq')
   [ INFO] [load] loaded 3/4 picks
   ```

3. **stderr safety net** — even with `NullLogger`, pip failures always dump the captured output to stderr. You never get a silent failure with no clue what went wrong.

## Architecture

Picky stays lean by delegating all heavy lifting to helper modules:

```
picky/
├── main.py            ← Picky(Plug) — lean orchestrator (~150 lines)
├── gitops.py          ← GitOps — stateless git wrappers (clone/pull/checkout)
├── installer.py       ← PickInstaller — per-pick install orchestration
├── requirements.py    ← RequirementInstaller — per-plugin pip --target
├── log.py             ← Logger ABC + NullLogger + PrintLogger
```

### Module responsibilities

| Module | Role |
| --- | --- |
| `main.py` | The `Picky` plug itself. Reads config, owns the `picky/` folder, loops over picks, delegates to the helpers. Exposes 4 exec commands + 2 delegated getters. |
| `gitops.py` | Pure git operations via GitPython. `clone`, `pull`, `checkout_branch`, `checkout_commit`, `is_repo`. No state. |
| `installer.py` | Per-pick install: clone/copy/link → apply branch/commit pin → install deps → run hooks (no hooks in lean version). `install()`, `update()`, `remove()`. |
| `requirements.py` | Per-plugin pip `--target` install. Reads `requirements.txt`, dedupes against already-installed dists, batches into one pip call, streams output. |
| `log.py` | Logger abstraction. `LogLevel` enum + `Logger` ABC + `NullLogger` + `PrintLogger`. |

### The data flow

```
config.toml (Picks)
    ↓
Picky.getPicks()  →  normalize to dicts with base + folder
    ↓
Picky.PickyInstall()
    ↓
PickInstaller.install(pick)
    ├─ GitOps.clone(url, path)            ← if remote
    ├─ shutil.copytree / os.symlink       ← if local base
    ├─ GitOps.checkout_branch/commit      ← if branch/commit pinned
    └─ RequirementInstaller.install(name, folder, name)
         ├─ read requirements.txt
         ├─ packages_in(target)           ← dedup check
         ├─ pip install --target <sp>/<name> <specs>
         └─ add_to_path(name)             ← sys.path.append
    ↓
Picky.loadPicks()
    ├─ for each pick: re-pin ref, add_to_path
    └─ plugman.getPlugs(folder, [name]) + loadKlasses(aset, paths)
         ← per-plugin try/except, one broken import doesn't crash the app
```

## File layout

```
picky/
├── src/picky/
│   ├── __init__.py        ← exports Picky + get_plug_class()
│   ├── main.py            ← Picky(Plug) — the plug itself
│   ├── gitops.py          ← GitOps — stateless git wrappers
│   ├── installer.py       ← PickInstaller — per-pick install
│   ├── requirements.py    ← RequirementInstaller — per-plugin pip
│   └── log.py             ← Logger ABC + NullLogger + PrintLogger
├── LICENSE
└── README.md
```

## Integration with nara

Picky is a standard nara plug. It:

- Extends `nara.Plug`.
- Uses `@tag('(exec)')` to expose `PickyInstall`, `PickyUpdate`, `PickyCleanup`, `PickyShow` as commands.
- Uses `@deleg(...)` to expose `getPickyFolder` and `getPicks` as queryable agents (other plugs can call `app.delegman.getAgent(mode=..., action='getPicks')`).
- Reads its config from the `[Picky]` section of `config.toml` (with `Picks` as a list).
- Calls `app.plugman.getPlugs()` + `app.plugman.loadKlasses()` to load installed picks.

## A real app using Picky

[ayleen](https://github.com/aotabekov91/ayleen) is a modalizer built on nara + nara_qt. Its `~/.config/ayleen/config.toml` includes:

```toml
[[Picks]]
plug = "aotabekov91/leaper"
branch = "main"

[[Picks]]
plug = "aotabekov91/table_sqlite"
```

Running `ayleen picky.install` clones all two, installs their deps into per-plugin `site-packages/`, and loads them.

## License

See [LICENSE](LICENSE).
