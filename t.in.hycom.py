#!/usr/bin/env python3

############################################################################
#
# MODULE:       t.in.hycom
# AUTHOR(S):    Yann Chemin
# PURPOSE:      Downloads HYCOM ESPC-D-V02 global ocean analyses and
#               forecasts (1/12 degree, 3-hourly: currents, temperature,
#               salinity, sea surface height) for an area and a period,
#               and imports each variable as a space-time raster dataset.
#               Only the requested window is transferred, through the
#               THREDDS NetCDF Subset Service. No account is needed.
#
# SPDX-License-Identifier: Unlicense
#
############################################################################

# %module
# % description: Downloads HYCOM global ocean analyses and forecasts (currents, temperature, salinity, sea surface height) and imports them as space-time raster datasets.
# % keyword: temporal
# % keyword: import
# % keyword: ocean
# % keyword: currents
# % keyword: HYCOM
# %end
# %option
# % key: variables
# % type: string
# % multiple: yes
# % required: yes
# % options: u,v,temperature,salinity,ssh
# % answer: u,v
# % description: Variables to import, one STRDS each
# % descriptions: u;Eastward water velocity (m/s);v;Northward water velocity (m/s);temperature;Water temperature (degree C);salinity;Salinity (psu);ssh;Sea surface height above geoid (m)
# %end
# %option
# % key: start
# % type: string
# % required: no
# % description: Start, YYYY-MM-DD or YYYY-MM-DDTHH (UTC)
# %end
# %option
# % key: end
# % type: string
# % required: no
# % description: End, YYYY-MM-DD (whole day) or YYYY-MM-DDTHH (UTC), inclusive
# %end
# %option
# % key: depth
# % type: double
# % required: no
# % answer: 0
# % description: Depth in metres for 3D variables (nearest model level: 0, 2, 4, 6, 8, 10, 12, 15, 20, 25, 30 ...)
# %end
# %option
# % key: product
# % type: string
# % required: no
# % options: auto,analysis,forecast
# % answer: auto
# % description: Which HYCOM product to read
# % descriptions: auto;Analysis archive up to its last time, forecast run collection after it;analysis;Analysis archive only (August 2024 to about a day ago);forecast;Forecast run collection only ("best" time series, about the last 10 days plus 8 days ahead)
# %end
# %option
# % key: area
# % type: double
# % multiple: yes
# % required: no
# % key_desc: north,west,south,east
# % description: Bounding box in WGS84 degrees (default the current region, plus one grid cell)
# %end
# %option
# % key: stride
# % type: integer
# % required: no
# % answer: 1
# % description: Keep every n-th grid cell (1 = native 0.08 x 0.04 degree)
# %end
# %option
# % key: output_prefix
# % type: string
# % required: no
# % answer: hycom
# % description: Prefix of the output STRDS names, <output_prefix>_<variable>
# %end
# %option
# % key: resample
# % type: string
# % required: no
# % options: nearest,bilinear,bicubic,lanczos,bilinear_f,bicubic_f,lanczos_f
# % answer: nearest
# % description: Resampling method used by r.import when the project is not in WGS84
# %end
# %option G_OPT_M_DIR
# % key: cache_dir
# % required: no
# % description: Directory to keep the downloaded NetCDF days in, reused by later runs (default a temporary directory)
# %end
# %flag
# % key: f
# % description: Fill land cells with the nearest sea value (for particle models near the coast)
# %end
# %flag
# % key: l
# % description: List the time coverage of the analysis and forecast products, then exit
# %end

import atexit
import datetime as dt
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import grass.script as gs

NCSS = "https://ncss.hycom.org/thredds/ncss/grid"
# Analysis archive, one aggregation per year and variable group; forecast
# run collection ("best" time series of the latest runs).
ANALYSIS = {
    "u": ("ESPC-D-V02/u3z/{year}", "water_u", True),
    "v": ("ESPC-D-V02/v3z/{year}", "water_v", True),
    "temperature": ("ESPC-D-V02/t3z/{year}", "water_temp", True),
    "salinity": ("ESPC-D-V02/s3z/{year}", "salinity", True),
    "ssh": ("ESPC-D-V02/ssh/{year}", "surf_el", False),
}
FORECAST = {
    "u": ("FMRC_ESPC-D-V02_uv3z/FMRC_ESPC-D-V02_uv3z_best.ncd", "water_u", True),
    "v": ("FMRC_ESPC-D-V02_uv3z/FMRC_ESPC-D-V02_uv3z_best.ncd", "water_v", True),
    "temperature": (
        "FMRC_ESPC-D-V02_ts3z/FMRC_ESPC-D-V02_ts3z_best.ncd",
        "water_temp",
        True,
    ),
    "salinity": (
        "FMRC_ESPC-D-V02_ts3z/FMRC_ESPC-D-V02_ts3z_best.ncd",
        "salinity",
        True,
    ),
    "ssh": ("FMRC_ESPC-D-V02_ssh/FMRC_ESPC-D-V02_ssh_best.ncd", "surf_el", False),
}
META = {
    "u": ("Eastward water velocity", "m s-1"),
    "v": ("Northward water velocity", "m s-1"),
    "temperature": ("Water temperature", "degree C"),
    "salinity": ("Salinity", "psu"),
    "ssh": ("Sea surface height above geoid", "m"),
}
GRID_DEG = (0.08, 0.04)  # Native lon, lat spacing of the archive grid.

TMP_RASTERS = []
TMP_DIR = None


def cleanup():
    if TMP_RASTERS:
        gs.run_command(
            "g.remove", type="raster", name=TMP_RASTERS, flags="f", quiet=True
        )
    if TMP_DIR and os.path.isdir(TMP_DIR):
        shutil.rmtree(TMP_DIR, ignore_errors=True)


def http_get(url, retries=5, timeout=300):
    """GET with retries; returns bytes. NCSS answers 400 with a message
    for a request outside the dataset."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "t.in.hycom"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                body = e.read().decode("utf-8", "replace")[:300]
                raise ValueError("HTTP {} {}".format(e.code, body.strip()))
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        time.sleep(min(60, 5 * 2**attempt))
    raise OSError("{} failed after {} attempts: {}".format(url, retries, last))


def parse_time(text, end=False):
    """YYYY-MM-DD (start of day, or its last 3-hourly time for an end) or
    YYYY-MM-DDTHH, as a naive UTC datetime."""
    try:
        if "T" in text:
            return dt.datetime.strptime(text[:13], "%Y-%m-%dT%H")
        d = dt.datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        gs.fatal(
            "Cannot read the date <{}>; use YYYY-MM-DD or YYYY-MM-DDTHH".format(text)
        )
    return d + dt.timedelta(hours=21) if end else d


def coverage(path):
    """(begin, end) of a dataset from its NCSS dataset.xml."""
    xml = http_get("{}/{}/dataset.xml".format(NCSS, path)).decode("utf-8", "replace")
    m = re.search(r"<TimeSpan>\s*<begin>([^<]+)</begin>\s*<end>([^<]+)</end>", xml)
    if not m:
        raise ValueError("no TimeSpan in {}".format(path))
    conv = [dt.datetime.strptime(v[:19], "%Y-%m-%dT%H:%M:%S") for v in m.groups()]
    return conv[0], conv[1]


def default_area():
    info = gs.parse_command("g.region", flags="bg")
    n, w, s, e = (float(info[k]) for k in ("ll_n", "ll_w", "ll_s", "ll_e"))
    # One native cell of margin so that interpolation reaches the edges.
    return [n + GRID_DEG[1], w - GRID_DEG[0], s - GRID_DEG[1], e + GRID_DEG[0]]


def plan_days(t0, t1, product, var):
    """List of (day_start, day_end, dataset_path, nc_var, is_3d, product)
    covering [t0, t1], one request per UTC day and product."""
    plans = []
    fc_cov = an_end = None
    if product in ("auto", "forecast"):
        fc_cov = coverage(FORECAST[var][0])
    day = dt.datetime(t0.year, t0.month, t0.day)
    while day <= t1:
        a = max(day, t0)
        b = min(day + dt.timedelta(hours=21), t1)
        if product in ("auto", "analysis"):
            path = ANALYSIS[var][0].format(year=day.year)
            if an_end is None or an_end[0] != day.year:
                try:
                    an_end = (day.year, coverage(path)[1])
                except (ValueError, OSError) as e:
                    if product == "analysis":
                        gs.fatal("No analysis archive for {}: {}".format(day.year, e))
                    an_end = (day.year, dt.datetime(1900, 1, 1))
        use_analysis = product == "analysis" or (
            product == "auto" and an_end and b <= an_end[1]
        )
        if product == "auto" and not use_analysis and a <= an_end[1] < b:
            # Day straddling the end of the archive: split it.
            path = ANALYSIS[var][0].format(year=day.year)
            plans.append(
                (a, an_end[1], path, ANALYSIS[var][1], ANALYSIS[var][2], "analysis")
            )
            a = an_end[1] + dt.timedelta(hours=3)
        if use_analysis:
            path = ANALYSIS[var][0].format(year=day.year)
            plans.append((a, b, path, ANALYSIS[var][1], ANALYSIS[var][2], "analysis"))
        else:
            if fc_cov is None or b < fc_cov[0] or a > fc_cov[1]:
                gs.fatal(
                    "{:%Y-%m-%d %H}h is outside the forecast collection ({} to {}); "
                    "use product=analysis for older dates".format(
                        a, *(fc_cov or ("?", "?"))
                    )
                )
            if a < fc_cov[0]:
                gs.warning(
                    "The forecast collection starts at {}; {:%Y-%m-%d} is only "
                    "partly covered".format(fc_cov[0], day)
                )
            plans.append(
                (
                    max(a, fc_cov[0]),
                    min(b, fc_cov[1]),
                    FORECAST[var][0],
                    FORECAST[var][1],
                    FORECAST[var][2],
                    "forecast",
                )
            )
        day += dt.timedelta(days=1)
    return plans


def fetch(plan, area, depth, stride, cache_dir):
    """Downloads one day as NetCDF (cached); returns its path."""
    a, b, path, ncvar, is3d, prod = plan
    n, w, s, e = area
    key = "{}_{}_{:%Y%m%dT%H}_{:%Y%m%dT%H}_{:.3f}_{:.3f}_{:.3f}_{:.3f}_d{:g}_s{}.nc".format(
        prod, ncvar, a, b, n, w, s, e, depth if is3d else 0, stride
    )
    out = Path(cache_dir) / key
    if out.exists() and out.stat().st_size > 0:
        return out
    q = [
        ("var", ncvar),
        ("north", "{:.4f}".format(n)),
        ("west", "{:.4f}".format(w)),
        ("south", "{:.4f}".format(s)),
        ("east", "{:.4f}".format(e)),
        ("horizStride", str(stride)),
        ("time_start", "{:%Y-%m-%dT%H:%M:%SZ}".format(a)),
        ("time_end", "{:%Y-%m-%dT%H:%M:%SZ}".format(b)),
        ("accept", "netcdf4"),
    ]
    if is3d:
        q.append(("vertCoord", "{:g}".format(depth)))
    url = "{}/{}?{}".format(NCSS, path, urllib.parse.urlencode(q))
    data = http_get(url)
    if data[:4] not in (b"\x89HDF", b"CDF\x01", b"CDF\x02"):
        gs.fatal("HYCOM answered with something else than NetCDF for {}".format(url))
    tmp = out.with_name("." + out.name)
    tmp.write_bytes(data)
    tmp.replace(out)
    return out


def fill_nearest(arr):
    """Replaces NaN cells by the value of the nearest valid cell."""
    import numpy as np
    from scipy import ndimage

    bad = np.isnan(arr)
    if not bad.any() or bad.all():
        return arr
    idx = ndimage.distance_transform_edt(
        bad, return_distances=False, return_indices=True
    )
    return arr[tuple(idx)]


def read_day(nc, ncvar, fill):
    """Returns (times, stack[t, row, col] north-up, geotransform)."""
    import numpy as np
    import xarray as xr

    with xr.open_dataset(nc, decode_times=True) as ds:
        da = ds[ncvar]
        for dim in ("depth", "lev"):
            if dim in da.dims:
                da = da.isel({dim: 0})
        lat = da["lat"].values
        lon = da["lon"].values
        lon = np.where(lon > 180, lon - 360, lon)
        vals = da.values.astype(np.float32)
        times = [
            dt.datetime.fromtimestamp(
                int(t.astype("datetime64[s]").astype(int)), dt.timezone.utc
            ).replace(tzinfo=None)
            for t in da["time"].values
        ]
    if vals.ndim == 2:
        vals = vals[None]
    if lat[0] < lat[-1]:
        vals = vals[:, ::-1, :]
        lat = lat[::-1]
    if fill:
        vals = np.stack([fill_nearest(v) for v in vals])
    dx = float(np.mean(np.diff(lon))) if lon.size > 1 else GRID_DEG[0]
    dy = float(np.mean(np.diff(lat))) if lat.size > 1 else -GRID_DEG[1]
    gt = (float(lon[0]) - dx / 2, dx, 0.0, float(lat[0]) - dy / 2, 0.0, dy)
    return times, vals, gt


def write_tif(path, stack, gt):
    import numpy as np
    from osgeo import gdal, osr

    gdal.UseExceptions()
    nodata = -9999.0
    nb, rows, cols = stack.shape
    dst = gdal.GetDriverByName("GTiff").Create(
        str(path), cols, rows, nb, gdal.GDT_Float32, options=["INTERLEAVE=BAND"]
    )
    dst.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    dst.SetProjection(srs.ExportToWkt())
    for i in range(nb):
        band = dst.GetRasterBand(i + 1)
        band.SetNoDataValue(nodata)
        band.WriteArray(
            np.where(np.isnan(stack[i]), nodata, stack[i]).astype(np.float32)
        )
    dst.FlushCache()
    dst = None


def import_variable(
    var, prefix, plans, area, depth, stride, cache_dir, fill, resample, overwrite
):
    strds = "{}_{}".format(prefix, var)
    rows = []
    seen = set()
    for k, plan in enumerate(plans):
        nc = fetch(plan, area, depth, stride, cache_dir)
        times, stack, gt = read_day(nc, plan[3], fill)
        keep = [i for i, t in enumerate(times) if t not in seen]
        if not keep:
            continue
        times = [times[i] for i in keep]
        stack = stack[keep]
        seen.update(times)
        tmp = "tmp_t_in_hycom_{}_{}_{}".format(os.getpid(), var, k)
        tif = Path(TMP_DIR) / (tmp + ".tif")
        write_tif(tif, stack, gt)
        imported = (
            [tmp]
            if len(times) == 1
            else ["{}.{}".format(tmp, i + 1) for i in range(len(times))]
        )
        TMP_RASTERS.extend(imported)
        gs.run_command(
            "r.import",
            input=str(tif),
            output=tmp,
            resample=resample,
            extent="input",
            quiet=True,
            overwrite=True,
        )
        tif.unlink()
        for name_tmp, t in zip(imported, times):
            name = "{}_{:%Y%m%d%H}".format(strds, t)
            gs.run_command(
                "g.rename", raster=(name_tmp, name), quiet=True, overwrite=overwrite
            )
            TMP_RASTERS.remove(name_tmp)
            gs.run_command(
                "r.support",
                map=name,
                units=META[var][1],
                title="HYCOM ESPC-D-V02 {} {} {:%Y-%m-%d %H} UTC".format(
                    plan[5], META[var][0].lower(), t
                ),
                source1="HYCOM ESPC-D-V02 via {}".format(NCSS),
                source2=plan[2],
            )
            gs.raster_history(name)
            rows.append("{}|{:%Y-%m-%d %H:%M:%S}".format(name, t))
        gs.percent(k + 1, len(plans), 1)
    if not rows:
        gs.fatal("No HYCOM field was imported for <{}>".format(var))
    gs.run_command(
        "t.create",
        output=strds,
        type="strds",
        temporaltype="absolute",
        semantictype="mean",
        overwrite=overwrite,
        quiet=True,
        title="HYCOM ESPC-D-V02 {}{}".format(
            META[var][0].lower(),
            ", depth {:g} m".format(depth) if ANALYSIS[var][2] else "",
        ),
        description="{} [{}], HYCOM ESPC-D-V02 1/12 degree global, "
        "3-hourly{}".format(
            META[var][0],
            META[var][1],
            ", land filled by nearest sea value" if fill else "",
        ),
    )
    maps_file = Path(TMP_DIR) / "{}_register.txt".format(strds)
    maps_file.write_text("\n".join(rows) + "\n")
    gs.run_command("t.register", input=strds, file=str(maps_file), quiet=True)
    gs.message(
        "Created space-time raster dataset <{}> with {} maps".format(strds, len(rows))
    )


def main():
    global TMP_DIR
    options, flags = gs.parser()
    atexit.register(cleanup)
    TMP_DIR = tempfile.mkdtemp(prefix="t_in_hycom_")

    if flags["l"]:
        for label, table in (("analysis", ANALYSIS), ("forecast", FORECAST)):
            for var, (path, ncvar, _) in table.items():
                path = path.format(year=dt.datetime.now(dt.timezone.utc).year)
                try:
                    a, b = coverage(path)
                    print(
                        "{}|{}|{}|{:%Y-%m-%dT%H}|{:%Y-%m-%dT%H}".format(
                            label, var, path, a, b
                        )
                    )
                except (ValueError, OSError) as e:
                    print("{}|{}|{}|unavailable: {}".format(label, var, path, e))
        return 0

    if not options["start"] or not options["end"]:
        gs.fatal("Options start and end are required (except with -l)")
    t0 = parse_time(options["start"])
    t1 = parse_time(options["end"], end=True)
    if t1 < t0:
        gs.fatal(
            "End <{}> is before start <{}>".format(options["end"], options["start"])
        )
    if options["area"]:
        area = [float(v) for v in options["area"].split(",")]
        if len(area) != 4 or area[0] <= area[2] or area[3] <= area[1]:
            gs.fatal(
                "Area must be north,west,south,east with north > south and east > west"
            )
    else:
        area = default_area()
    stride = int(options["stride"])
    if stride < 1:
        gs.fatal("Stride must be 1 or more")
    depth = float(options["depth"])
    cache_dir = options["cache_dir"] or TMP_DIR
    os.makedirs(cache_dir, exist_ok=True)
    overwrite = gs.overwrite()

    variables = options["variables"].split(",")
    for var in variables:
        strds = "{}_{}".format(options["output_prefix"], var)
        exists = gs.read_command(
            "t.list", type="strds", where="name='{}'".format(strds), quiet=True
        ).strip()
        if not overwrite and exists:
            gs.fatal("STRDS <{}> exists; use --overwrite".format(strds))
    for var in variables:
        gs.message("Planning <{}> ...".format(var))
        plans = plan_days(t0, t1, options["product"], var)
        gs.message(
            "Downloading and importing {} day(s) of <{}> ...".format(len(plans), var)
        )
        import_variable(
            var,
            options["output_prefix"],
            plans,
            area,
            depth,
            stride,
            cache_dir,
            flags["f"],
            options["resample"],
            overwrite,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
