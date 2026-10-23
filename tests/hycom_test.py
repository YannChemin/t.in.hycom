"""Tests of the date handling, product planning, land filling and NetCDF
reading of t.in.hycom. They make no GRASS call and, except the one marked
network, no download."""

import datetime as dt

import numpy as np
import pytest

D = dt.datetime


def test_parse_time(hycom):
    assert hycom.parse_time("2026-10-19") == D(2026, 10, 19)
    assert hycom.parse_time("2026-10-19", end=True) == D(2026, 10, 19, 21)
    assert hycom.parse_time("2026-10-19T06") == D(2026, 10, 19, 6)


def stub_coverage(
    monkeypatch, hycom, an_end, fc=(D(2026, 10, 14, 12), D(2026, 10, 28, 12))
):
    def coverage(path):
        if path.startswith("FMRC"):
            return fc
        return D(2026, 1, 1, 12), an_end

    monkeypatch.setattr(hycom, "coverage", coverage)


def test_plan_auto_splits_at_archive_end(monkeypatch, hycom):
    stub_coverage(monkeypatch, hycom, D(2026, 10, 22, 9))
    plans = hycom.plan_days(D(2026, 10, 21), D(2026, 10, 23, 21), "auto", "u")
    kinds = [(p[0], p[1], p[5]) for p in plans]
    assert kinds[0] == (D(2026, 10, 21), D(2026, 10, 21, 21), "analysis")
    assert kinds[1] == (D(2026, 10, 22), D(2026, 10, 22, 9), "analysis")
    assert kinds[2] == (D(2026, 10, 22, 12), D(2026, 10, 22, 21), "forecast")
    assert kinds[3] == (D(2026, 10, 23), D(2026, 10, 23, 21), "forecast")
    assert plans[0][2] == "ESPC-D-V02/u3z/2026"
    assert plans[0][3] == "water_u"
    assert plans[2][2].startswith("FMRC_ESPC-D-V02_uv3z")


def test_plan_forecast_clips_partial_first_day(monkeypatch, hycom):
    stub_coverage(monkeypatch, hycom, D(2026, 10, 22, 9))
    monkeypatch.setattr(hycom.gs, "warning", lambda msg: None)
    plans = hycom.plan_days(D(2026, 10, 14), D(2026, 10, 15, 21), "forecast", "v")
    assert plans[0][0] == D(2026, 10, 14, 12)
    assert all(p[5] == "forecast" for p in plans)


def test_plan_forecast_outside_fails(monkeypatch, hycom):
    stub_coverage(monkeypatch, hycom, D(2026, 10, 22, 9))

    def fatal(msg):
        raise RuntimeError(msg)

    monkeypatch.setattr(hycom.gs, "fatal", fatal)
    with pytest.raises(RuntimeError, match="outside the forecast collection"):
        hycom.plan_days(D(2026, 10, 1), D(2026, 10, 2), "forecast", "u")


def test_ssh_is_2d(hycom):
    assert hycom.ANALYSIS["ssh"][2] is False
    assert hycom.FORECAST["u"][2] is True


def test_fill_nearest(hycom):
    a = np.array([[1.0, np.nan, np.nan], [np.nan, np.nan, 5.0]], np.float32)
    f = hycom.fill_nearest(a)
    assert np.isfinite(f).all()
    assert f[0, 1] == 1.0
    assert f[1, 1] == 5.0
    assert np.isnan(hycom.fill_nearest(np.full((2, 2), np.nan))).all()


def test_read_day_flips_and_wraps(tmp_path, hycom):
    xr = pytest.importorskip("xarray")
    lat = np.array([25.0, 25.04, 25.08])
    lon = np.array([359.92, 360.0, 360.08])
    t = np.array(["2026-10-19T00", "2026-10-19T03"], dtype="datetime64[ns]")
    u = np.arange(2 * 1 * 3 * 3, dtype=np.float32).reshape(2, 1, 3, 3)
    u[0, 0, 0, 0] = np.nan
    ds = xr.Dataset(
        {"water_u": (("time", "depth", "lat", "lon"), u)},
        coords={"time": t, "depth": [0.0], "lat": lat, "lon": lon},
    )
    nc = tmp_path / "u.nc"
    ds.to_netcdf(nc)
    times, stack, gt = hycom.read_day(nc, "water_u", fill=False)
    assert times == [D(2026, 10, 19, 0), D(2026, 10, 19, 3)]
    assert stack.shape == (2, 3, 3)
    # Row 0 is now the northern latitude.
    assert stack[0, 0, 1] == u[0, 0, 2, 1]
    assert np.isnan(stack[0, 2, 0])
    assert gt[0] == pytest.approx(-0.12, abs=1e-6)
    assert gt[1] == pytest.approx(0.08, abs=1e-6)
    assert gt[3] == pytest.approx(25.10, abs=1e-6)
    assert gt[5] == pytest.approx(-0.04, abs=1e-6)
    _, filled, _ = hycom.read_day(nc, "water_u", fill=True)
    assert np.isfinite(filled).all()


@pytest.mark.network
def test_forecast_coverage_live(hycom):
    a, b = hycom.coverage(hycom.FORECAST["u"][0])
    assert b > a
    assert (b - a).days >= 7
