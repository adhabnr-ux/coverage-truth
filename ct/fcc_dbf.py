"""Fast fixed-width reader for FCC BDC mobile H3 .dbf attribute tables (millions of rows)."""
from __future__ import annotations
import struct
from pathlib import Path
import numpy as np
import pandas as pd


def read_dbf(path: Path, columns=None) -> pd.DataFrame:
    raw = np.memmap(path, dtype=np.uint8, mode="r")
    nrec, hlen, rlen = struct.unpack("<IHH", bytes(raw[4:12]))
    fields, off, pos = [], 1, 32
    while raw[pos] != 0x0D:
        name = bytes(raw[pos:pos + 11]).split(b"\0")[0].decode()
        ftype, flen = chr(raw[pos + 11]), int(raw[pos + 16])
        fields.append((name, ftype, off, flen)); off += flen; pos += 32
    recs = raw[hlen:hlen + nrec * rlen].reshape(nrec, rlen)
    out = {}
    for name, ftype, off, flen in fields:
        if columns and name not in columns:
            continue
        col = np.ascontiguousarray(recs[:, off:off + flen]).view(f"S{flen}").ravel()
        s = pd.Series(col).str.decode("latin-1").str.strip()
        out[name] = pd.to_numeric(s, errors="coerce") if ftype in "NF" else s
    return pd.DataFrame(out)
