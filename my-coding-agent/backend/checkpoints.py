"""Undo support: the workspace is a small Git repo, committed around every task."""
import os
import shutil
import subprocess

from agent import WORKSPACE

GIT_DIR = os.path.join(WORKSPACE, ".git")
READY = False  # becomes True when Git is installed and the repo exists


def git(*args):
    # --git-dir and --work-tree make sure we can never touch any other repo
    cmd = ["git", f"--git-dir={GIT_DIR}", f"--work-tree={WORKSPACE}",
           "-c", "user.name=agent", "-c", "user.email=agent@local", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def setup():
    global READY
    if shutil.which("git") is None:
        return
    if not os.path.isdir(GIT_DIR):
        git("init")
        git("add", "-A")
        git("commit", "-m", "initial state", "--allow-empty")
    READY = os.path.isdir(GIT_DIR)


def save(message):
    """Commit any changes in the workspace."""
    if not READY:
        return
    git("add", "-A")
    if git("status", "--porcelain").stdout.strip():
        git("commit", "-m", message[:60])


def undo():
    """Go back one commit. Returns (worked, message)."""
    if not READY:
        return False, "Undo needs Git. Install Git and restart the backend."
    count = git("rev-list", "--count", "HEAD").stdout.strip()
    if not count.isdigit() or int(count) <= 1:
        return False, "Nothing to undo."
    git("reset", "--hard", "HEAD~1")
    return True, "Undone: the workspace is back to how it was before the last task."
