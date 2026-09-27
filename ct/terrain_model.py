"""Terrain path loss: free space + ITU-R P.526 Bullington diffraction over the DEM profile.

Ray tracing (Sionna RT) handles line of sight and reflections well but only single-order edge diffraction,
which under-predicts coverage over rugged terrain. Broadcast/cellular planning therefore uses terrain-profile
methods (ITU-R P.526 / P.1812, Longley-Rice). This is the standard Bullington construction.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import RegularGridInterpolator

C = 299_792_458.0
K_EARTH = 4.0 / 3.0
R_EARTH = 6_371_000.0


class Terrain:
    def __init__(self, grid: dict):
        la, lo, z = grid["lat"][:, 0], grid["lon"][0, :], grid["z"]
        self.f = RegularGridInterpolator((la[::-1], lo), z[::-1], bounds_error=False, fill_value=None)

    def __call__(self, lat, lon):
        return self.f(np.stack([np.asarray(lat, float), np.asarray(lon, float)], axis=-1))


def j_nu(nu):
    """ITU-R P.526 knife-edge loss approximation J(nu) in dB (0 for nu <= -0.78)."""
    nu = np.asarray(nu, float)
    out = 6.9 + 20 * np.log10(np.sqrt((nu - 0.1) ** 2 + 1) + nu - 0.1)
    return np.where(nu > -0.78, out, 0.0)


def path_loss_db(terrain: Terrain, tx_lat, tx_lon, tx_h, rx_lat, rx_lon, rx_h=1.5, freq_hz=850e6, n=200):
    """Vectorized over receivers. Returns (loss_dB, los_bool, distance_m)."""
    rx_lat, rx_lon = np.atleast_1d(rx_lat).astype(float), np.atleast_1d(rx_lon).astype(float)
    lam = C / freq_hz
    s = np.linspace(0.0, 1.0, n)[None, :]
    plat = tx_lat + (rx_lat[:, None] - tx_lat) * s
    plon = tx_lon + (rx_lon[:, None] - tx_lon) * s
    dx = (rx_lon - tx_lon) * 111_320 * np.cos(np.radians(tx_lat))
    dy = (rx_lat - tx_lat) * 111_320
    d = np.maximum(np.hypot(dx, dy), 1.0)
    di = d[:, None] * s
    ground = terrain(plat, plon)
    hs = ground[:, 0] + tx_h                       # tx antenna height a.s.l.
    hr = ground[:, -1] + rx_h
    # effective heights including earth bulge
    bulge = di * (d[:, None] - di) / (2 * K_EARTH * R_EARTH)
    h = ground + bulge
    inner = slice(1, n - 1)
    # Bullington: slopes from tx to terrain and from rx to terrain
    stim = np.max((h[:, inner] - hs[:, None]) / di[:, inner], axis=1)        # max slope seen from tx
    slos = (hr - hs) / d
    los = stim < slos
    srim = np.max((h[:, inner] - hr[:, None]) / (d[:, None] - di[:, inner]), axis=1)
    db = np.clip((hr - hs + srim * d) / (stim + srim + 1e-12), 0, d)          # distance of Bullington point
    hb = hs + stim * db
    nu_los = np.max((h[:, inner] + 0 - (hs[:, None] + (hr - hs)[:, None] * di[:, inner] / d[:, None]))
                    * np.sqrt(2 * d[:, None] / (lam * di[:, inner] * (d[:, None] - di[:, inner]))), axis=1)
    nu_b = (hb - (hs + (hr - hs) * db / d)) * np.sqrt(2 * d / (lam * np.maximum(db * (d - db), 1.0)))
    nu = np.where(los, nu_los, nu_b)
    fspl = 20 * np.log10(4 * np.pi * np.hypot(d, hs - hr) / lam)
    return fspl + j_nu(nu), los, d
