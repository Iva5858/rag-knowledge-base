"""VaultSync: auto-commit and push the Obsidian vault after every write."""

import logging
import subprocess
from pathlib import Path

from config import Config, get_config
from models.schema import KnowledgeEntry

logger = logging.getLogger(__name__)


class VaultSync:
    """Commits and pushes a new Obsidian note to a remote git repository.

    Uses subprocess + system git so that existing credential helpers
    (HTTPS PAT stored in the keychain, SSH agent, etc.) work transparently.
    Failures are logged and swallowed — a sync error must never fail an ingestion.
    """

    def __init__(self, config: Config | None = None) -> None:
        cfg = config or get_config()
        self._vault = cfg.obsidian.resolved_vault_path
        self._enabled = cfg.obsidian.vault_sync_enabled
        self._remote = cfg.obsidian.git_remote
        self._check_setup()

    def _check_setup(self) -> None:
        """Warn at startup if sync is enabled but the vault isn't a git repository."""
        if not self._enabled:
            return
        if not self._remote:
            logger.warning(
                "VaultSync: vault_sync_enabled=true but git_remote is empty — "
                "set obsidian.git_remote in config.yaml to enable push."
            )
            self._enabled = False
            return
        if not (self._vault / ".git").exists():
            logger.warning(
                "VaultSync: %s is not a git repository — "
                "run 'git init' in the vault and configure the remote. Sync disabled.",
                self._vault,
            )
            self._enabled = False

    def commit_and_push(self, entry: KnowledgeEntry) -> None:
        """Stage all vault changes, commit, and push (F-V1 through F-V4).

        Runs synchronously — call via asyncio.to_thread from async contexts.
        Logs and returns on any failure without raising (F-V4).
        """
        if not self._enabled:
            return

        commit_msg = f"Add: {entry.title} [{entry.date[:10]}]"  # F-V2

        try:
            self._git("add", "-A")

            stdout = self._git("commit", "-m", commit_msg, check=False)
            if "nothing to commit" in stdout:
                logger.debug("VaultSync: nothing to commit")
                return

            self._git("push")
            logger.info("VaultSync: pushed — %s", commit_msg)

        except Exception as exc:
            logger.error("VaultSync: failed (%s) — ingestion continues", exc)

    def _git(self, *args: str, check: bool = True) -> str:
        """Run a git command inside the vault directory."""
        cmd = ["git", "-C", str(self._vault), *args]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        combined = result.stdout + result.stderr
        if check and result.returncode != 0:
            raise RuntimeError(
                f"`{' '.join(cmd)}` failed (exit {result.returncode}):\n{combined.strip()}"
            )
        return combined
