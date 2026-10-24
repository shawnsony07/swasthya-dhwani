"""
Background Git Auto-Sync Daemon for Swasthya Dhwani.

- Monitors local changes and commits them with clean, descriptive messages.
- Ensures Claude / Anthropic co-authors are NEVER included in any commit.
- Automatically pushes local commits to `origin main`.
- Maintains repository sync in real-time.
"""

from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
import time

REPO_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = REPO_DIR / ".git_autosync.log"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {msg}"
    print(entry, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def run_git(args, capture=True):
    cmd = ["git"] + args
    res = subprocess.run(
        cmd,
        cwd=str(REPO_DIR),
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return res


def strip_claude_coauthors():
    """Checks unpushed commits and strips any Claude/Anthropic co-authors."""
    res = run_git(["log", "origin/main..HEAD", "--format=%H"])
    if res.returncode != 0 or not res.stdout.strip():
        return

    unpushed = [c.strip() for c in res.stdout.strip().splitlines() if c.strip()]
    if not unpushed:
        return

    dirty = False
    for commit in unpushed:
        msg_res = run_git(["log", "-n", "1", "--format=%B", commit])
        if re.search(r"claude|anthropic", msg_res.stdout, re.I):
            dirty = True
            break

    if not dirty:
        return

    log(f"Found {len(unpushed)} unpushed commit(s) with AI co-authors. Sanitizing...")
    rev_list = unpushed[::-1]
    base = run_git(["rev-parse", f"{rev_list[0]}^"]).stdout.strip()

    parent = base
    for c in rev_list:
        tree = run_git(["rev-parse", f"{c}^{{tree}}"]).stdout.strip()
        raw = run_git(["cat-file", "-p", c]).stdout
        header, body = raw.split("\n\n", 1)

        author_match = re.search(r"^author (.*) <(.*)> (.*)$", header, re.M)
        committer_match = re.search(r"^committer (.*) <(.*)> (.*)$", header, re.M)

        aname, aemail, adate = (
            author_match.group(1),
            author_match.group(2),
            author_match.group(3),
        )
        cname, cemail, cdate = (
            committer_match.group(1),
            committer_match.group(2),
            committer_match.group(3),
        )

        clean_lines = [
            line
            for line in body.splitlines()
            if not re.search(r"claude|anthropic", line, re.I)
        ]
        clean_body = "\n".join(clean_lines).strip() + "\n"

        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = aname
        env["GIT_AUTHOR_EMAIL"] = aemail
        env["GIT_AUTHOR_DATE"] = adate
        env["GIT_COMMITTER_NAME"] = cname
        env["GIT_COMMITTER_EMAIL"] = cemail
        env["GIT_COMMITTER_DATE"] = cdate

        cmd = ["commit-tree", tree, "-p", parent, "-m", clean_body]
        new_c = subprocess.run(
            ["git"] + cmd,
            cwd=str(REPO_DIR),
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()
        parent = new_c

    run_git(["update-ref", "refs/heads/main", parent])
    log(f"Sanitized HEAD is now {parent[:7]}")


def generate_commit_message(changed_files: list[str]) -> str:
    """Generates a structured, descriptive commit message based on changed files."""
    categories = set()
    file_details = []

    for f in changed_files:
        if f.startswith("src/swasthya/api/"):
            categories.add("api")
        elif f.startswith("src/swasthya/voice/"):
            categories.add("voice")
        elif f.startswith("src/swasthya/protocol/"):
            categories.add("protocol")
        elif f.startswith("src/swasthya/fhir/"):
            categories.add("fhir")
        elif f.startswith("src/swasthya/workflow/"):
            categories.add("workflow")
        elif f.startswith("src/swasthya/gateway/"):
            categories.add("gateway")
        elif f.startswith("dashboard/"):
            categories.add("dashboard")
        elif f.startswith("docker/"):
            categories.add("docker")
        elif f.startswith("docs/"):
            categories.add("docs")
        elif f.startswith("tests/"):
            categories.add("tests")
        else:
            categories.add("chore")
        file_details.append(f)

    prefix = "/".join(sorted(categories)) if categories else "sync"
    if len(changed_files) == 1:
        summary = f"Update {changed_files[0]}"
    else:
        summary = f"Update {prefix} components ({len(changed_files)} files modified)"

    body_lines = ["Updates to local files:"]
    for f in file_details[:10]:
        body_lines.append(f"- {f}")
    if len(file_details) > 10:
        body_lines.append(f"... and {len(file_details) - 10} more files")

    return f"{summary}\n\n" + "\n".join(body_lines)


def auto_commit_and_push():
    # 1. Check for working tree changes
    res = run_git(["status", "--porcelain"])
    status_output = res.stdout.strip()

    if status_output:
        lines = status_output.splitlines()
        changed_files = [line[3:].strip() for line in lines if line[3:].strip()]
        log(f"Detected {len(changed_files)} uncommitted file(s): {changed_files[:3]}...")

        # Stage changes
        run_git(["add", "."])

        # Re-verify something is staged
        staged = run_git(["diff", "--staged", "--name-only"]).stdout.strip()
        if staged:
            staged_files = staged.splitlines()
            msg = generate_commit_message(staged_files)
            commit_res = run_git(["commit", "-m", msg])
            if commit_res.returncode == 0:
                log(f"Committed changes: {msg.splitlines()[0]}")
            else:
                log(f"Commit warning: {commit_res.stderr.strip()}")

    # 2. Check for any unpushed commits & sanitize AI co-authors
    strip_claude_coauthors()

    # 3. Check if ahead of remote
    status = run_git(["status", "-uno"]).stdout
    if "Your branch is ahead of" in status:
        log("Branch is ahead of origin/main. Pushing to git...")
        push_res = run_git(["push", "origin", "main"])
        if push_res.returncode == 0:
            log("Successfully pushed to origin/main.")
        else:
            log(f"Push output: {push_res.stderr.strip()}")


def main():
    log("Git Auto-Sync daemon initialized and watching...")
    while True:
        try:
            auto_commit_and_push()
        except Exception as e:
            log(f"Error in sync loop: {e}")
        time.sleep(5)


if __name__ == "__main__":
    main()
