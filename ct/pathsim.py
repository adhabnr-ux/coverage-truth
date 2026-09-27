"""Deterministic Sionna RT path computation from towers to receiver points over terrain (CPU/LLVM)."""

from __future__ import annotations

import time
from pathlib import Path

import mitsuba as mi
import numpy as np

mi.set_variant("llvm_ad_mono_polarized")
import drjit as dr  # noqa: E402
import sionna.rt as rt  # noqa: E402

from .terrain_scene import enu  # noqa: E402


def elev_lookup(grid, lat, lon):
    """Bilinear interpolation on the terrain-mesh grid (same surface the ray tracer sees)."""
    from scipy.interpolate import RegularGridInterpolator
    la, lo, z = grid["lat"][:, 0], grid["lon"][0, :], grid["z"]
    f = RegularGridInterpolator((la[::-1], lo), z[::-1], bounds_error=False, fill_value=None)
    return f(np.stack([np.asarray(lat, float), np.asarray(lon, float)], axis=-1))


def path_gain(scene_dir: Path, towers, rx_lat, rx_lon, rx_height=1.5, freq_hz=850e6, max_depth=2,
              diffraction=True, samples=1_000_000, batch=4000):
    """Returns path gain in dB [num_tx, num_rx] (sum of path powers), and runtime."""
    grid = dict(np.load(scene_dir / "grid.npz"))
    lat0, lon0 = float(grid["lat0"]), float(grid["lon0"])
    rx_lat, rx_lon = np.asarray(rx_lat), np.asarray(rx_lon)
    rx_x, rx_y = enu(rx_lat, rx_lon, lat0, lon0)
    rx_z = elev_lookup(grid, rx_lat, rx_lon) + rx_height
    out = np.full((len(towers), len(rx_lat)), -300.0)
    t0 = time.time()
    for k, t in enumerate(towers):
        tx, ty = enu(t["lat"], t["lon"], lat0, lon0)
        tz = float(elev_lookup(grid, [t["lat"]], [t["lon"]])[0]) + t["height_m"]
        for s in range(0, len(rx_lat), batch):
            scene = rt.load_scene(str(scene_dir / "scene.xml"))
            scene.frequency = freq_hz
            scene.tx_array = rt.PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
            scene.rx_array = rt.PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
            scene.add(rt.Transmitter(name="tx", position=[float(tx), float(ty), tz]))
            idx = range(s, min(s + batch, len(rx_lat)))
            for i in idx:
                scene.add(rt.Receiver(name=f"rx{i}", position=[float(rx_x[i]), float(rx_y[i]), float(rx_z[i])]))
            paths = rt.PathSolver()(scene, max_depth=max_depth, los=True, specular_reflection=True,
                                    diffraction=diffraction, refraction=False, samples_per_src=samples,
                                    synthetic_array=True)
            a_re, a_im = paths.a
            a = np.asarray(a_re.numpy()) + 1j * np.asarray(a_im.numpy())   # [rx, rx_ant, tx, tx_ant, paths]
            p = (np.abs(a) ** 2).reshape(a.shape[0], -1).sum(axis=1)
            out[k, s:s + len(idx)] = 10 * np.log10(np.maximum(p, 1e-30))
    return out, time.time() - t0
