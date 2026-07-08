#!/usr/bin/env python3
"""Step-0 stale-base guard -- refuse to start work on a base behind origin/master.

Motivation: a recurring "stale-local-master" trap (three merge-status mislabels + one
rebase conflict) came from starting a feature on a local base that was already behind
origin/master. This guard is the Build SOP's step-0: run it at the start of a task,
BEFORE creating the worktree/branch, to catch that case early.

What it does (and only this):
  1. `git fetch origin master`  -- updates the remote-tracking ref origin/master ONLY.
     No merge, no checkout, no local-branch move. It reads the remote's tip; it does
     not mutate your working tree or any local branch.
  2. `git merge-base --is-ancestor origin/master HEAD`
        exit 0  -> origin/master IS an ancestor of HEAD (base is current, or ahead) -> PASS
        exit 1  -> origin/master is NOT an ancestor of HEAD (base is BEHIND)         -> REFUSE

Design stances (deliberate):
  * REFUSE ONLY. On a behind base it prints a message and exits non-zero. It NEVER
    auto-pulls, auto-rebases, or auto-checks-out anything -- no surprising mutation.
    Fixing the base is the human's explicit action: `git pull origin master`.
  * WARN-AND-ALLOW OFFLINE. If the fetch cannot reach origin (no network), freshness
    cannot be proven, so the guard prints an honest "UNVERIFIED" notice and exits 0
    rather than bricking offline work. It does NOT claim PASS in that case.

Scope: pure stdlib, no third-party imports, no `anthropic`. Reads git refs only;
touches no fixture, oracle, chain, or tax-semantics artifact. Produces no finding and
renders nothing in the report -- offline-replay / oracle checks do not apply to it.
"""
import subprocess
import sys

REMOTE = "origin"
BRANCH = "master"
REMOTE_REF = f"{REMOTE}/{BRANCH}"


def _run_git(args):
    """Run a git subcommand, returning (returncode, stdout, stderr). Never raises on
    a non-zero git exit -- callers branch on the returncode themselves."""
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True
    )
    return proc.returncode, proc.stdout, proc.stderr


def main() -> int:
    # 1. Refresh the remote-tracking ref only. This is a read of origin's tip; it does
    #    not merge, checkout, or move any local branch.
    fetch_rc, _, fetch_err = _run_git(["fetch", REMOTE, BRANCH])
    if fetch_rc != 0:
        # Offline / unreachable origin: warn-and-allow. We cannot prove freshness, so
        # we say so honestly and do NOT claim PASS.
        print(
            f"[WARN] Base freshness UNVERIFIED: could not `git fetch {REMOTE} {BRANCH}` "
            "(offline or origin unreachable). Proceeding without a freshness check -- "
            "verify manually if you can reach the network.\n"
            f"    git error: {fetch_err.strip()}"
        )
        return 0

    # 2. Is origin/master contained in HEAD? Exit 0 => ancestor (current/ahead).
    #    Exit 1 => not an ancestor (behind). Any other code => an unexpected git error.
    ancestor_rc, _, ancestor_err = _run_git(
        ["merge-base", "--is-ancestor", REMOTE_REF, "HEAD"]
    )
    if ancestor_rc == 0:
        print(f"[PASS] local HEAD contains {REMOTE_REF} -- base is current. Safe to start.")
        return 0
    if ancestor_rc == 1:
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

    # Unexpected git failure (e.g. REMOTE_REF missing) -- surface it, don't mislabel.
    print(
        f"[WARN] Base freshness UNVERIFIED: `git merge-base --is-ancestor {REMOTE_REF} HEAD` "
        f"exited {ancestor_rc}.\n    git error: {ancestor_err.strip()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
