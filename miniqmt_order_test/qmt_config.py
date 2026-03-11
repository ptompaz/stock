from __future__ import annotations

import os


def get_qmt_path(*, default: str = r"F:\stock\qmt\userdata_mini") -> str:
    v = os.environ.get("QMT_PATH")
    if v is None:
        return default
    v = str(v).strip()
    if not v:
        return default
    return v
