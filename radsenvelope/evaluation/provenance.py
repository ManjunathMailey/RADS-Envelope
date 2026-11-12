"""Run provenance stored in every results JSON: time, git commit, prompt hashes, model."""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from radsenvelope.extraction import llm

ROOT = Path(__file__).resolve().parents[2]


def git_commit() -> dict:
    def run(*args):
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain", "--untracked-files=no"))}


def run_meta() -> dict:
    from .baselines import SYSTEM_DIRECT
    return {"generated_at": datetime.now().isoformat(timespec="seconds"), "git": git_commit(), "model": llm.MODEL,
            "prompt_hash": llm.prompt_hash(), "b1_prompt_hash": llm.prompt_hash(SYSTEM_DIRECT)}
