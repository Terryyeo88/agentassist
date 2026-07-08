"""Hermetic tests for `preflight_base_check.py --context=prepr` -- the mid-flight
staleness check run right before PR-open.

Complements tests/test_preflight_base_check.py (the locked start-stale test, which
this file must NOT touch). Same hermetic shape: build a throwaway local + "origin"
git repo in a temp dir (the "remote" is a bare repo on a local path; the offline case
points the remote at a bogus path so fetch fails deterministically). No real network.

The mid-flight trap: a feature branch that was current when cut goes stale because
master advanced WHILE work was in progress. `prepr` mode detects that and TELLS the
human to `git rebase origin/master` (NOT `git pull`, which would graft a merge commit
onto the feature branch). Detect-and-tell only -- it never rebases/pulls/mutates.

Cases:
  a. MASTER ADVANCED -- origin/master has a commit the branch tip lacks -> non-zero
     exit; stdout names `git rebase origin/master` + the N-commit count; NOT "git pull".
  b. NOT ADVANCED    -- origin/master is an ancestor of HEAD -> exit 0, prepr PASS
     ("safe to open PR").
  c. FETCH FAILS     -- cannot reach origin (offline) -> exit 0, UNVERIFIED, and does
     NOT falsely claim safe-to-PR (warn-and-allow).
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "preflight_base_check.py"


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=check, capture_output=True, text=True
    )


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Prepr Test")
    _git(path, "config", "commit.gpgsign", "false")
    return path


def _commit(repo, filename, content, message):
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)


def _run_prepr(cwd):
    """Invoke the guard in prepr mode with cwd set to the repo under test."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--context=prepr"],
        cwd=str(cwd), capture_output=True, text=True,
    )


class PreprStalenessCheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _origin_and_feature_branch(self):
        """Bare origin at c1; a `local` clone with a feature commit c2 on top.

        Immediately after this, local HEAD (c2) CONTAINS origin/master (c1) -> NOT
        advanced. Call _advance_origin() to push a new master commit the branch lacks.
        Returns (origin, seed, local).
        """
        origin = self.tmp / "origin.git"
        subprocess.run(
            ["git", "init", "--bare", str(origin)],
            check=True, capture_output=True, text=True,
        )
        seed = _init_repo(self.tmp / "seed")
        _commit(seed, "a.txt", "1", "c1")
        _git(seed, "remote", "add", "origin", str(origin))
        _git(seed, "push", "origin", "HEAD:refs/heads/master")

        local = self.tmp / "local"
        subprocess.run(
            ["git", "clone", str(origin), str(local)],
            check=True, capture_output=True, text=True,
        )
        _git(local, "config", "user.email", "test@example.com")
        _git(local, "config", "user.name", "Prepr Test")
        _git(local, "config", "commit.gpgsign", "false")
        # Feature work on top of the branch point -> models a real feature branch.
        _commit(local, "feature.txt", "wip", "c2 feature work")
        return origin, seed, local

    def _advance_origin(self, seed):
        """Push a new commit to origin/master that the feature branch does not have."""
        _commit(seed, "b.txt", "2", "c3 someone-else's merge")
        _git(seed, "push", "origin", "HEAD:refs/heads/master")

    def test_a_master_advanced_tells_rebase(self):
        """origin/master advanced past the branch tip -> non-zero + rebase remediation."""
        _, seed, local = self._origin_and_feature_branch()
        self._advance_origin(seed)

        result = _run_prepr(local)
        self.assertNotEqual(result.returncode, 0, msg="advanced master must be flagged")
        self.assertIn("git rebase origin/master", result.stdout)
        self.assertNotIn("git pull", result.stdout)  # pull would graft a merge commit
        self.assertIn("1", result.stdout)  # N = one commit advanced

    def test_b_not_advanced_safe_to_pr(self):
        """origin/master is an ancestor of HEAD -> exit 0 + prepr PASS (safe to open PR)."""
        _, _, local = self._origin_and_feature_branch()
        result = _run_prepr(local)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("safe to open pr", result.stdout.lower())

    def test_c_fetch_failure_warns_and_allows(self):
        """Fetch cannot reach origin -> exit 0, UNVERIFIED, NOT a false safe-to-PR."""
        local = _init_repo(self.tmp / "local_offline")
        _commit(local, "a.txt", "1", "c1")
        _git(local, "remote", "add", "origin", str(self.tmp / "does_not_exist.git"))

        result = _run_prepr(local)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("UNVERIFIED", result.stdout)
        self.assertNotIn("safe to open pr", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
