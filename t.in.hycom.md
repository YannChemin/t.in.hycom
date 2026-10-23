## DESCRIPTION

*t.in.hycom* downloads ocean fields of the HYCOM ESPC-D-V02 global
ocean prediction system (US Navy, distributed by
[HYCOM.org](https://www.hycom.org)) and imports each requested variable
as a space-time raster dataset (STRDS). The system runs at 1/12 degree
(0.08 x 0.04 degree, about 8 x 4.5 km at 25 degrees of latitude) with
3-hourly output, and includes tides.

Only the requested window is transferred: the module asks the THREDDS
NetCDF Subset Service (NCSS) of `ncss.hycom.org` for one variable, one
depth, the area and one UTC day at a time, so that each request stays
small and is cached for later runs. No account or key is needed.

### Variables

| Variable | HYCOM name | Unit | Dimensions |
|---|---|---|---|
| u | water_u | m/s | 3D (depth) |
| v | water_v | m/s | 3D (depth) |
| temperature | water_temp | degree C | 3D (depth) |
| salinity | salinity | psu | 3D (depth) |
| ssh | surf_el | m | 2D |

The **depth** option selects the model level for the 3D variables (0 m,
the surface, by default; the levels are 0, 2, 4, 6, 8, 10, 12, 15, 20,
25, 30 m and deeper). Each variable becomes the STRDS
*<output_prefix>_<variable>*, with one map per 3-hourly time step named
*<output_prefix>_<variable>_YYYYMMDDHH*.

### Products

HYCOM publishes two products, chosen by **product**:

- **analysis**: the analysis archive, one aggregation per year from
  August 2024, lagging real time by about one day.
- **forecast**: the forecast model run collection, as its "best" time
  series: the analysis part of the recent runs followed by the latest
  run's forecast, about 10 days back and 8 days ahead. It rolls daily.
- **auto** (default): the archive up to its last time, the forecast
  collection after it. A day that straddles the end of the archive is
  split between the two.

Use **-l** to print the time coverage of every variable in both
products.

### Land cells

HYCOM marks land cells as no data. With **-f**, every land cell takes
the value of the nearest sea cell before import. This is what particle
tracking models need near the coast, where the 1/12 degree grid leaves
coastal sea without a value; leave it off for maps and statistics.

## NOTES

The archive aggregation answers slowly (several minutes per day of data
on 23 October 2026); the forecast collection answers in under a minute
per day. For recent periods, **product=forecast** is much faster.

The area defaults to the current region plus one HYCOM cell on each
side, so that the imported maps cover the region after reprojection.
In a projected project, **resample=bilinear** gives smoother current
fields than the default nearest neighbour.

The download cache (**cache_dir**) holds one NetCDF file per variable
and day, named after the product, variable, period, area, depth and
stride; a later run with the same request reuses it.

Without **--overwrite**, the module stops before downloading anything if
an output STRDS already exists.

## EXAMPLES

Surface currents of the southern Arabian Gulf for a week, with land
filled for a drift model, in a UTM project:

```sh
g.region n=2965000 s=2745000 w=200000 e=500000 res=1000
t.in.hycom -f variables=u,v start=2026-10-14 end=2026-10-21 \
    product=forecast area=26.8,54.0,24.8,57.0 resample=bilinear \
    cache_dir=$HOME/RSDATA/hycom
t.rast.list hycom_u
```

Coverage of the two products:

```sh
t.in.hycom -l
```

## SEE ALSO

*[t.in.ecmwf](t.in.ecmwf.md),
[t.in.era5](t.in.era5.md),
[t.oil.drift](t.oil.drift.md),
[t.rast.list](https://grass.osgeo.org/grass-stable/manuals/t.rast.list.html),
[t.register](https://grass.osgeo.org/grass-stable/manuals/t.register.html)*

## REFERENCES

- HYCOM consortium: [ESPC-D-V02 global analysis and
  forecast](https://www.hycom.org/dataserver/espc-d-v02).
- Metzger, E. J. et al. (2017). Operational implementation design for
  the Earth System Prediction Capability (ESPC). NRL report.

## AUTHORS

Yann Chemin
