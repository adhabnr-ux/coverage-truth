"""Unit tests: DEM mosaicking/registration, propagation model, H3 slot codec, DBF reader, site inference."""
import json
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import pytest
import rasterio

from ct.common import DATA
from ct.inpage import child_id, decode, rle_decode
from ct.physics_check import Config, haversine_km, infer_sites, strong_threshold
from ct.terrain_model import Terrain, j_nu, path_loss_db
from ct.terrain_scene import load_dem

HAVE_DEM = (DATA / "dem_N33_00_W110_00.tif").exists() and (DATA / "dem_N33_00_W111_00.tif").exists()


@pytest.mark.skipif(not HAVE_DEM, reason="DEM tiles not downloaded")
def test_dem_mosaic_is_registered_across_tile_edge():
    """Regression test for the clipped-window bug: every grid value must equal the source tile's value."""
    lat, lon, z = load_dem(DATA, 33.70, -110.10, 33.97, -109.94, step=1)
    rng = np.random.default_rng(0)
    for _ in range(200):
        i, j = rng.integers(0, z.shape[0]), rng.integers(0, z.shape[1])
        tile = "dem_N33_00_W111_00.tif" if lon[i, j] < -110 else "dem_N33_00_W110_00.tif"
        with rasterio.open(DATA / tile) as src:
            v = next(src.sample([(lon[i, j], lat[i, j])]))[0]
        assert abs(v - z[i, j]) < 1e-3, (lat[i, j], lon[i, j], v, z[i, j])


def test_knife_edge_reference_values():
    assert j_nu(-1.0) == 0.0
    assert abs(float(j_nu(0.0)) - 6.03) < 0.05          # ITU-R P.526: J(0) ~ 6 dB
    assert abs(float(j_nu(1.0)) - 13.9) < 0.2


def flat_terrain(h=1000.0):
    lat = np.linspace(34.5, 33.5, 400)[:, None] * np.ones((1, 400))
    lon = np.ones((400, 1)) * np.linspace(-111.0, -110.0, 400)[None, :]
    return Terrain(dict(lat=lat, lon=lon, z=np.full((400, 400), h)))


def test_flat_terrain_short_link_is_free_space():
    t = flat_terrain()
    loss, los, d = path_loss_db(t, 34.0, -110.5, 30.0, [34.01], [-110.5], 1.5, 850e6)
    fspl = 20 * np.log10(4 * np.pi * np.hypot(d[0], 28.5) * 850e6 / 299_792_458.0)
    assert los[0] and abs(loss[0] - fspl) < 0.5


def test_earth_bulge_blocks_long_low_link():
    t = flat_terrain()
    loss, los, _ = path_loss_db(t, 34.0, -110.9, 10.0, [34.0], [-110.35], 1.5, 850e6)  # ~50 km, 10 m mast
    assert not los[0]


def test_ridge_adds_diffraction_loss():
    lat = np.linspace(34.5, 33.5, 400)[:, None] * np.ones((1, 400))
    lon = np.ones((400, 1)) * np.linspace(-111.0, -110.0, 400)[None, :]
    z = np.full((400, 400), 1000.0)
    z[:, 195:205] = 1300.0                                # 300 m ridge in the middle
    flat, _, _ = path_loss_db(flat_terrain(), 34.0, -110.8, 30.0, [34.0], [-110.2], 1.5, 850e6)
    ridge, los, _ = path_loss_db(Terrain(dict(lat=lat, lon=lon, z=z)), 34.0, -110.8, 30.0, [34.0], [-110.2], 1.5, 850e6)
    assert not los[0] and ridge[0] - flat[0] > 15


def test_h3_slot_codec_matches_h3_library():
    parent = h3.latlng_to_cell(33.8, -109.97, 7)
    kids = sorted(h3.cell_to_children(parent, 9))
    mine = set()
    for d8 in range(7):
        for d9 in range(7):
            mine.add(child_id(parent, d8, d9))
    assert set(kids) == mine
    assert rle_decode("3.w2s") == "...wss"
    s = ["."] * 49
    s[0] = "w"                                            # -104 dBm at slot 0
    enc = "w48."
    d = decode([parent], {0: enc})
    assert len(d) == 1 and d.claimed_min_rsrp.iloc[0] == -104 and d.h3.iloc[0] == child_id(parent, 0, 0)


def test_site_inference_recovers_synthetic_tower():
    tower = (35.0, -110.0)
    rng = np.random.default_rng(1)
    rows = []
    for cell in h3.grid_disk(h3.latlng_to_cell(*tower, 9), 25):
        la, lo = h3.cell_to_latlng(cell)
        dkm = haversine_km(*tower, la, lo)
        level = -60 if dkm < 0.6 else -80 if dkm < 1.5 else -100
        rows.append((cell, 0, level, la, lo))
    c = pd.DataFrame(rows, columns=["h3", "env", "claimed_min_rsrp", "lat", "lon"])
    sites, thr = infer_sites(c, Config(name="t", bbox=(34.8, -110.2, 35.2, -109.8), strong_min_cells=5))
    assert thr == -60 and len(sites) == 1
    assert haversine_km(*tower, sites.lat[0], sites.lon[0]) < 0.2


def test_strong_threshold_rule():
    c = pd.DataFrame(dict(claimed_min_rsrp=[-50] * 5 + [-60] * 50 + [-100] * 500))
    assert strong_threshold(c, 40) == -60


def test_fast_dbf_reader_matches_pyshp(tmp_path):
    import shapefile
    from ct.fcc_dbf import read_dbf
    w = shapefile.Writer(dbf=str(tmp_path / "t.dbf"))
    w.field("providerid", "N", 10)
    w.field("minsignal", "N", 6)
    w.field("environmnt", "N", 2)
    w.field("h3_res9_id", "C", 15)
    recs = [(130077, -104, 0, "8948cc0017bffff"), (131208, -50, 1, "8948cc01087ffff")]
    for r in recs:
        w.record(*r)
    w.close()
    df = read_dbf(tmp_path / "t.dbf")
    assert df.values.tolist() == [list(r) for r in recs]


def test_statewide_robust_contradictions_are_rare():
    """Guards the headline number against silent pipeline changes (needs work/ tables)."""
    p = Path(__file__).resolve().parents[1] / "work" / "tiles_vs_claims.parquet"
    if not p.exists():
        pytest.skip("run ct.statewide first")
    t = pd.read_parquet(p)
    r = t[t.robust & (t.claim_frac == 1)]
    assert 0 < r.contradiction.mean() < 0.01
