"""Hermetic tests for scripts/preflight_base_check.py — the step-0 stale-base guard.

These tests build throwaway local + "origin" git repositories in a temp dir and run
the guard as a subprocess with cwd pointed at the local repo. Nothing here touches the
real network or the real origin: the "remote" is a bare repo on a local path (fetch
works offline), and the offline case points the remote at a bogus path so fetch fails
deterministically.

Exit-code contract under test:
  a. BASE CURRENT  — HEAD contains origin/master           -> exit 0, stdout says PASS
  b. BASE BEHIND   — HEAD missing commits on origin/master -> non-zero, stdout carries
                     the REFUSE message telling the human to run `git pull origin master`
  c. FETCH FAILS   — cannot reach origin (offline)         -> exit 0, stdout says
                     base freshness UNVERIFIED, and does NOT claim PASS (warn-and-allow)
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "preflight_base_check.py"


def _git(cwd, *args, check=True):
    """Run a git command in cwd, capturing output. Raises on failure when check=True."""
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=check, capture_output=True, text=True
    )


def _init_repo(path):
    """git init a working repo with a self-contained identity (no global config needed)."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Preflight Test")
    _git(path, "config", "commit.gpgsign", "false")
    return path


def _commit(repo, filename, content, message):
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)


def _run_guard(cwd):
    """Invoke the guard script as a subprocess with cwd set to the repo under test."""
    return subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=str(cwd), capture_output=True, text=True
    )


class PreflightBaseCheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _build_origin_and_local(self):
        """Create a bare origin with a `master` branch and a fresh clone `local`.

        Returns (origin, seed, local). Immediately after this, local's HEAD equals
        origin/master (base is CURRENT). Advance origin via `seed` to make local behind.
        """
        origin = self.tmp / "origin.git"
        subprocess.run(
            ["git", "init", "--bare", str(origin)],
            check=True, capture_output=True, text=True,
        )
        seed = _init_repo(self.tmp / "seed")
        _commit(seed, "a.txt", "1", "c1")
        _git(seed, "remote", "add", "origin", str(origin))
        # Push explicitly to refs/heads/master so the remote branch is `master`
        # regardless of the local default-branch name.
        _git(seed, "push", "origin", "HEAD:refs/heads/master")

        local = self.tmp / "local"
        subprocess.run(
            ["git", "clone", str(origin), str(local)],
            check=True, capture_output=True, text=True,
        )
        _git(local, "config", "user.email", "test@example.com")
        _git(local, "config", "user.name", "Preflight Test")
        _git(local, "config", "commit.gpgsign", "false")
        return origin, seed, local

    def test_a_base_current_passes(self):
        """HEAD contains origin/master -> exit 0 and stdout announces PASS."""
        _, _, local = self._build_origin_and_local()
        result = _run_guard(local)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_b_base_behind_refuses(self):
        """HEAD missing commits on origin/master -> non-zero exit + REFUSE message."""
        _, seed, local = self._build_origin_and_local()
        # Advance origin ahead of local's HEAD.
        _commit(seed, "b.txt", "2", "c2")
        _git(seed, "push", "origin", "HEAD:refs/heads/master")

        result = _run_guard(local)
        self.assertNotEqual(result.returncode, 0, msg="behind base must be refused")
        self.assertIn("git pull origin master", result.stdout)

    def test_c_fetch_failure_warns_and_allows(self):
        """Fetch cannot reach origin -> exit 0, UNVERIFIED, and NOT a PASS claim."""
        local = _init_repo(self.tmp / "local_offline")
        _commit(local, "a.txt", "1", "c1")
        # Point origin at a path that is not a git repository, so fetch fails fast
        # and deterministically with no network involved.
        _git(local, "remote", "add", "origin", str(self.tmp / "does_not_exist.git"))

        result = _run_guard(local)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("UNVERIFIED", result.stdout)
        self.assertNotIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
