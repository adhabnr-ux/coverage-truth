"""Shared helpers for Coverage Truth: FCC claims (H3 res-9), Ookla tiles (quadkey z16), schools."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import h3
import mercantile
import numpy as np
import pandas as pd
import shapefile  # pyshp

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WORK = ROOT / "work"
WORK.mkdir(exist_ok=True)

PROVIDERS = {130077: "AT&T", 130403: "T-Mobile", 131425: "Verizon", 131208: "Smith Bagley (Cellular One)"}
H3_RES = 9


def load_fcc_claims(zip_path: Path) -> pd.DataFrame:
    """Read only the attribute table (.dbf) of an FCC BDC mobile-broadband H3 shapefile zip."""
    with zipfile.ZipFile(zip_path) as z:
        dbf_name = next(n for n in z.namelist() if n.endswith(".dbf"))
        reader = shapefile.Reader(dbf=io.BytesIO(z.read(dbf_name)))
        fields = [f[0] for f in reader.fields[1:]]
        rows = reader.records()
    df = pd.DataFrame(rows, columns=fields)
    df["providerid"] = df["providerid"].astype(int)
    return df


def tile_cells(quadkey: str) -> list[str]:
    """H3 res-9 cells whose centers fall in an Ookla z16 tile (~600 m)."""
    t = mercantile.quadkey_to_tile(quadkey)
    b = mercantile.bounds(t)
    poly = h3.LatLngPoly([(b.south, b.west), (b.south, b.east), (b.north, b.east), (b.north, b.west)])
    cells = h3.polygon_to_cells(poly, H3_RES)
    if not cells:  # tiny tile edge case: use the cell of the tile center
        cells = [h3.latlng_to_cell((b.south + b.north) / 2, (b.west + b.east) / 2, H3_RES)]
    return list(cells)


def point_cell(lat: float, lon: float) -> str:
    return h3.latlng_to_cell(lat, lon, H3_RES)


def disk(cell: str, k: int) -> list[str]:
    return list(h3.grid_disk(cell, k))
