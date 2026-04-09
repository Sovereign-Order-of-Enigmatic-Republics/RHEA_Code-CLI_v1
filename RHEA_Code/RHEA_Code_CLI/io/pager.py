# -*- coding: utf-8 -*-
# io/pager.py
# RHEA Code CLI — Cross-platform pager support

from __future__ import annotations

import os
import pydoc
import shutil
import subprocess
import tempfile


def open_in_pager(text: str) -> str:
    less_cmd = shutil.which("less")
    if less_cmd:
        try:
            subprocess.run([less_cmd], input=text, text=True, check=False)
            return "Opened content in pager: less"
        except Exception as e:
            return f"Pager launch failed (less): {e}"

    more_cmd = shutil.which("more")
    if more_cmd:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                suffix=".txt",
            ) as tmp:
                tmp.write(text)
                tmp_path = tmp.name

            subprocess.run(f'more "{tmp_path}"', shell=True, check=False)
            return "Opened content in pager: more"
        except Exception as e:
            return f"Pager launch failed (more): {e}"
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    try:
        pydoc.pager(text)
        return "Opened content in pager: pydoc"
    except Exception as e:
        return f"No pager available. Fallback failed: {e}"