# t.in.hycom

GRASS GIS addon that downloads HYCOM ESPC-D-V02 global ocean fields
(1/12 degree, 3-hourly, tides included) and imports them as space-time
raster datasets (STRDS): currents (`u`, `v`), `temperature`, `salinity`
and sea surface height (`ssh`), at a chosen depth.

- Only the requested window is transferred, one UTC day per request,
  through the THREDDS NetCDF Subset Service of `ncss.hycom.org`; no
  account is needed, and requests are cached (`cache_dir`).
- `product=auto` reads the analysis archive (August 2024 onwards) up to
  its last time and the forecast run collection (about 10 days back,
  8 days ahead) after it; `-l` lists the coverage of both.
- `-f` fills land cells from the nearest sea cell, for particle drift
  models near the coast (for example `t.oil.drift`).

See [t.in.hycom.md](t.in.hycom.md) for the manual.

## Install

```sh
g.extension t.in.hycom url=/path/to/t.in.hycom
```

or build it inside a grass-addons tree:

```sh
make -C grass-addons/src/temporal/t.in.hycom MODULE_TOPDIR=/path/to/grass
```

## Tests

```sh
python3 -m pytest tests            # offline
python3 -m pytest -m network tests # live coverage query
```

## Licence

The Unlicense (public domain), see [LICENSE](LICENSE).
