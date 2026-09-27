"""Decode the compact slot strings produced by tools/fcc_inpage_extract.js back into H3 res-9 claims."""
from __future__ import annotations

import re

import h3
import pandas as pd


def rle_decode(s: str) -> str:
    return "".join(ch * (int(n) if n else 1) for n, ch in re.findall(r"(\d*)(\D)", s))


def child_id(res7: str, d8: int, d9: int) -> str:
    v = int(res7, 16)
    v = (v & ~(0xF << 52)) | (9 << 52)                 # resolution field -> 9
    v = (v & ~(0x3F << 18)) | (d8 << 21) | (d9 << 18)  # digits 8 and 9
    return format(v, "x")


def decode(res7_list: list[str], encoded: dict[int, str]) -> pd.DataFrame:
    """encoded = {env: rle_string}. Returns h3, env, claimed_min_rsrp, lat, lon."""
    rows = []
    for env, enc in encoded.items():
        s = rle_decode(enc)
        assert len(s) == 49 * len(res7_list), (len(s), len(res7_list))
        for slot, ch in enumerate(s):
            if ch == ".":
                continue
            k, r = divmod(slot, 49)
            cell = child_id(res7_list[k], r // 7, r % 7)
            if not h3.is_valid_cell(cell):
                continue
            lat, lon = h3.cell_to_latlng(cell)
            rows.append((cell, env, -(ord(ch) - 65 + 50), lat, lon))
    return pd.DataFrame(rows, columns=["h3", "env", "claimed_min_rsrp", "lat", "lon"])
