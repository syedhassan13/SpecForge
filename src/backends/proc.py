"""
Subprocess helper that really stops a timed-out tool.

`subprocess.run(timeout=...)` kills only the direct child. `dafny run`
starts the compiled program as a grandchild; when a candidate loops forever
that grandchild keeps the output pipes open and `run` waits for ever
(found on vb_087, see docs/devlog.md). Here the whole process tree is killed
on timeout before the pipes are drained.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys


def run_tree(cmd: list[str], cwd: str, timeout: float) -> tuple[int, str]:
    kwargs = dict(cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                  encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, (out or "") + "\n" + (err or "")
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise subprocess.TimeoutExpired(cmd, timeout)
