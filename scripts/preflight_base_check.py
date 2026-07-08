#!/usr/bin/env python3
"""Stale-base guard -- refuse/tell when your base is behind origin/master.

Two contexts, ONE freshness primitive (`git fetch origin master` then
`git merge-base --is-ancestor origin/master HEAD`):

  --context=preflight  (DEFAULT) -- Build SOP step-0, run BEFORE creating the
     worktree/branch. Catches the "start-stale" trap: starting a feature on a local
     base already behind origin/master (three merge-status mislabels + one rebase
     conflict). On a behind base it REFUSES and tells you `git pull origin master`.

  --context=prepr -- run right BEFORE `gh pr create`. Catches the "mid-flight" trap:
     a branch that was current when cut goes stale because master advanced WHILE work
     was in progress (this forced the PR #92 rebase). On an advanced master it TELLS
     you to `git rebase origin/master` (rebase, not a merge-style pull, keeps the
     feature branch a clean linear diff).

What the primitive means on a feature branch:
  merge-base --is-ancestor origin/master HEAD
     exit 0 -> origin/master IS an ancestor of HEAD  -> CURRENT  (base current / master
               has not advanced past the branch tip)
     exit 1 -> origin/master is NOT an ancestor       -> BEHIND   (base behind / master
               advanced -- the branch is missing commits that are on origin/master)

Design stances (both contexts, deliberate):
  * DETECT-AND-TELL ONLY. On BEHIND it prints a message and exits non-zero. It NEVER
    auto-pulls, auto-rebases, or auto-checks-out anything -- no surprising mutation.
    Fixing the base is the human's explicit action (`git pull` for start-stale,
    `git rebase` for mid-flight).
  * WARN-AND-ALLOW OFFLINE. If the fetch cannot reach origin (no network), freshness
    cannot be proven, so it prints an honest "UNVERIFIED" notice and exits 0 rather
    than bricking offline work. It does NOT claim a clean base in that case.

Scope: pure stdlib, no third-party imports, no `anthropic`. Reads git refs only;
touches no fixture, oracle, chain, or tax-semantics artifact. Produces no finding and
renders nothing in the report -- offline-replay / oracle checks do not apply to it.
It is a LOCAL step (not a CI gate); ci.yml does a fresh checkout and never runs it.
"""
import argparse
import subprocess
import sys

REMOTE = "origin"
BRANCH = "master"
REMOTE_REF = f"{REMOTE}/{BRANCH}"

# Freshness states returned by the shared primitive.
CURRENT = "current"        # origin/master is an ancestor of HEAD
BEHIND = "behind"          # origin/master is NOT an ancestor of HEAD
UNVERIFIED = "unverified"  # could not prove either way (offline / unexpected git error)


def _run_git(args):
    """Run a git subcommand, returning (returncode, stdout, stderr). Never raises on
    a non-zero git exit -- callers branch on the returncode themselves."""
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True
    )
    return proc.returncode, proc.stdout, proc.stderr


def check_freshness():
    """Fetch origin/master (ref-only) then test ancestry. Shared by both contexts.

    Returns (state, detail) where state is CURRENT / BEHIND / UNVERIFIED and detail
    carries the git error / exit code for the UNVERIFIED case. The fetch updates the
    remote-tracking ref ONLY -- no merge, no checkout, no local-branch move.
    """
    fetch_rc, _, fetch_err = _run_git(["fetch", REMOTE, BRANCH])
    if fetch_rc != 0:
        return UNVERIFIED, {"reason": "fetch", "git_error": fetch_err.strip()}

    ancestor_rc, _, ancestor_err = _run_git(
        ["merge-base", "--is-ancestor", REMOTE_REF, "HEAD"]
    )
    if ancestor_rc == 0:
        return CURRENT, {}
    if ancestor_rc == 1:
        return BEHIND, {}
    return UNVERIFIED, {"reason": "ancestor", "rc": ancestor_rc, "git_error": ancestor_err.strip()}


def _advance_count():
    """How many commits are on origin/master but not on HEAD (the mid-flight count)."""
    rc, out, _ = _run_git(["rev-list", "--count", f"HEAD..{REMOTE_REF}"])
    return out.strip() if rc == 0 and out.strip() else "?"


def _report_preflight(state, detail):
    """Step-0 wording. MUST stay byte-identical to the merged behaviour -- the locked
    test tests/test_preflight_base_check.py asserts these exact strings/exit codes."""
    if state == UNVERIFIED:
        if detail.get("reason") == "fetch":
            print(
                f"[WARN] Base freshness UNVERIFIED: could not `git fetch {REMOTE} {BRANCH}` "
                "(offline or origin unreachable). Proceeding without a freshness check -- "
                "verify manually if you can reach the network.\n"
                f"    git error: {detail['git_error']}"
            )
        else:
            print(
                f"[WARN] Base freshness UNVERIFIED: `git merge-base --is-ancestor {REMOTE_REF} HEAD` "
                f"exited {detail['rc']}.\n    git error: {detail['git_error']}"
            )
        return 0
    if state == CURRENT:
        print(f"[PASS] local HEAD contains {REMOTE_REF} -- base is current. Safe to start.")
        return 0
    # BEHIND
    print(
        f"[REFUSE] stale base: your local HEAD is BEHIND {REMOTE_REF}; it is "
        "missing commits that are already on the remote. Starting work here risks "
        "the stale-local-master trap (merge-status mislabels, rebase conflicts).\n"
        "\n"
        "    Fix it, then retry:\n"
        "        git pull origin master\n"
        "\n"
        "This guard REFUSES only -- it will not auto-pull, auto-rebase, or auto-"
        "checkout anything. The pull is your explicit call."
    )
    return 1


def _report_prepr(state, detail):
    """Pre-PR-open wording. Same freshness primitive, mid-flight remediation (rebase)."""
    if state == UNVERIFIED:
        if detail.get("reason") == "fetch":
            print(
                f"[WARN] Base freshness UNVERIFIED: could not `git fetch {REMOTE} {BRANCH}` "
                "(offline or origin unreachable). Cannot check whether master advanced -- "
                "verify manually before opening the PR if you can reach the network.\n"
                f"    git error: {detail['git_error']}"
            )
        else:
            print(
                f"[WARN] Base freshness UNVERIFIED: `git merge-base --is-ancestor {REMOTE_REF} HEAD` "
                f"exited {detail['rc']}.\n    git error: {detail['git_error']}"
            )
        return 0
    if state == CURRENT:
        print("[PASS] master has not advanced since you branched -- safe to open PR.")
        return 0
    # BEHIND -> master advanced mid-flight.
    n = _advance_count()
    print(
        f"[REBASE NEEDED] master advanced {n} commit(s) since you branched; your branch "
        "is missing them. Rebase onto the advanced master before opening the PR so the "
        "PR is a clean, linear diff:\n"
        "\n"
        "    git rebase origin/master\n"
        "\n"
        "This check TELLS only -- it will not auto-rebase, auto-pull, or mutate anything. "
        "Use rebase (not a merge-style pull, which would graft an extra merge commit onto "
        "your feature branch)."
    )
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Stale-base guard: refuse/tell when the base is behind origin/master."
    )
    parser.add_argument(
        "--context",
        choices=["preflight", "prepr"],
        default="preflight",
        help="preflight (default): step-0 start-stale guard (remediation: git pull). "
             "prepr: pre-PR-open mid-flight check (remediation: git rebase).",
    )
    args = parser.parse_args(argv)

    state, detail = check_freshness()
    if args.context == "prepr":
        return _report_prepr(state, detail)
    return _report_preflight(state, detail)


if __name__ == "__main__":
    sys.exit(main())
