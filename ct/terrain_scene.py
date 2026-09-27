"""Build a Sionna RT scene (terrain mesh + UE measurement surface) from a Copernicus 30 m DEM.

Coordinates: local East-North-Up metres around (lat0, lon0); z = elevation above sea level.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from plyfile import PlyData, PlyElement

M_PER_DEG_LAT = 111_320.0


def enu(lat, lon, lat0, lon0):
    x = (np.asarray(lon) - lon0) * M_PER_DEG_LAT * np.cos(np.radians(lat0))
    y = (np.asarray(lat) - lat0) * M_PER_DEG_LAT
    return x, y


COP_URL = "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{t}_DEM/Copernicus_DSM_COG_10_{t}_DEM.tif"


def dem_tiles(south: float, west: float, north: float, east: float, data_dir: Path) -> list[Path]:
    """Copernicus GLO-30 1x1 degree tiles covering the bbox (named by their south-west corner);
    downloads any that are missing."""
    import math
    import urllib.request
    out = []
    for la in range(math.floor(south), math.floor(north - 1e-9) + 1):
        for lo in range(math.floor(west), math.floor(east - 1e-9) + 1):
            t = f"{'N' if la >= 0 else 'S'}{abs(la):02d}_00_{'W' if lo < 0 else 'E'}{abs(lo):03d}_00"
            f = Path(data_dir) / f"dem_{t}.tif"
            if not f.exists():
                urllib.request.urlretrieve(COP_URL.format(t=t), f)
            out.append(f)
    return out


def load_dem(tif, south: float, west: float, north: float, east: float, step: int):
    """Elevation grid (rows north->south) with pixel-centre lat/lon, mosaicking as many tiles as the
    bbox needs. `tif` may be one path, a list of paths, or a data directory (tiles fetched on demand).

    Note: an earlier version read a single tile with a window that extended past the tile edge;
    rasterio silently clipped the read while the coordinates were computed for the unclipped window,
    misregistering the terrain. Mosaicking with explicit bounds (and tests/test_terrain.py) prevents that.
    """
    from rasterio.merge import merge
    if isinstance(tif, (list, tuple)):
        paths = list(tif)
    elif Path(tif).is_dir():
        paths = dem_tiles(south, west, north, east, Path(tif))
    else:
        paths = [Path(tif)]
    srcs = [rasterio.open(p) for p in paths]
    # snap the bounds outward to the tiles' pixel grid so no resampling happens (values stay exact)
    import math
    t0 = srcs[0].transform
    rx, ry, x0, y0 = t0.a, -t0.e, t0.c, t0.f
    west = x0 + math.floor((west - x0) / rx + 1e-9) * rx
    east = x0 + math.ceil((east - x0) / rx - 1e-9) * rx
    north = y0 - math.floor((y0 - north) / ry + 1e-9) * ry
    south = y0 - math.ceil((y0 - south) / ry - 1e-9) * ry
    try:
        z, tr = merge(srcs, bounds=(west, south, east, north), nodata=-9999)
    finally:
        for s in srcs:
            s.close()
    z = z[0].astype(np.float64)
    if (z == -9999).any():
        raise ValueError("bbox not fully covered by DEM tiles: " + ", ".join(map(str, paths)))
    z = z[::step, ::step]
    rows, cols = np.indices(z.shape)
    lon = tr.c + (cols * step + 0.5) * tr.a
    lat = tr.f + (rows * step + 0.5) * tr.e
    return lat, lon, z


def grid_mesh_ply(path: Path, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> int:
    """Triangulated height-field. Returns number of triangles."""
    ny, nx = z.shape
    verts = np.zeros(nx * ny, dtype=[("x", "f4"), ("y", "f4"), ("z", "f4")])
    verts["x"], verts["y"], verts["z"] = x.ravel(), y.ravel(), z.ravel()
    idx = np.arange(nx * ny).reshape(ny, nx)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel()
    # orientation: normals pointing up (+z); rows go north->south (y decreasing)
    tris = np.concatenate([np.stack([a, c, b], 1), np.stack([b, c, d], 1)])
    faces = np.empty(len(tris), dtype=[("vertex_indices", "i4", (3,))])
    faces["vertex_indices"] = tris
    PlyData([PlyElement.describe(verts, "vertex"), PlyElement.describe(faces, "face")], text=False).write(str(path))
    return len(tris)


def build(out_dir: Path, tif: Path, bbox, lat0, lon0, terrain_step=2, ue_step=4, ue_height=1.5):
    """bbox = (south, west, north, east). Writes scene.xml, terrain.ply, ue_surface.ply."""
    out_dir.mkdir(parents=True, exist_ok=True)
    lat, lon, z = load_dem(tif, *bbox, step=terrain_step)
    x, y = enu(lat, lon, lat0, lon0)
    n_t = grid_mesh_ply(out_dir / "terrain.ply", x, y, z)
    lat2, lon2, z2 = load_dem(tif, *bbox, step=ue_step)
    x2, y2 = enu(lat2, lon2, lat0, lon0)
    n_u = grid_mesh_ply(out_dir / "ue_surface.ply", x2, y2, z2 + ue_height)
    (out_dir / "scene.xml").write_text(f"""<scene version="2.1.0">
  <!-- medium-dry ground at sub-GHz (ITU-R P.527): eps_r ~ 15, sigma ~ 0.005 S/m -->
  <bsdf type="radio-material" id="mat-ground">
    <float name="relative_permittivity" value="15.0"/>
    <float name="conductivity" value="0.005"/>
    <float name="thickness" value="10.0"/>
  </bsdf>
  <shape type="ply" id="terrain">
    <string name="filename" value="terrain.ply"/>
    <ref id="mat-ground" name="bsdf"/>
  </shape>
</scene>
""")
    np.savez(out_dir / "grid.npz", lat=lat, lon=lon, z=z, lat_ue=lat2, lon_ue=lon2, z_ue=z2, lat0=lat0, lon0=lon0)
    return {"terrain_triangles": n_t, "ue_triangles": n_u, "terrain_shape": z.shape, "ue_shape": z2.shape}
