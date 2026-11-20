# GeoTIFF Series to Defsour Design

## Intent

Add a source-neutral workflow that converts one indexed single-band GeoTIFF
time series into one transactional Defsour snapshot. Use it for the four Hawaii
MSBAS scalar series (087 descending LOS, 124 ascending LOS, 2D EW, and 2D UD)
without adding any MSBAS-specific code to the adapter.

## Goals

- Keep one index file, one scalar time series, one cfg, and one output snapshot.
- Preserve the exact `YYYYMMDDTHHMMSS` epoch identifier and index order while
  retaining `YYYYMMDD` as the compatibility date.
- Read deformation, DEM, and mask rasters by bounded windows.
- Require explicit units, CRS, scaling, nodata/mask behavior, references, and
  provenance.
- Reuse the existing Defsour exporter, metadata, and atomic directory
  publication contracts.
- Accept one already prepared two-column list for each scalar series.

## Non-goals

- The generic converter does not interpret LOS, EW, or UD semantics.
- It does not infer displacement units or sign convention from filenames.
- It does not build a time-cube or canonical HDF5 intermediate.
- It does not search directories for unlisted epochs.

## Selected approach

`export-geotiff-defsour` consumes exactly one normalized two-column list and
has no MSBAS/component-specific parsing or branching. Preparing the Hawaii
lists from the original `MSBAS_TSOUT.txt` files is a separate, one-time data
operation performed outside this repository workflow.

Alternatives rejected:

- A full `export-msbas-defsour` workflow or an MSBAS list-splitting command
  would introduce source-specific behavior into a source-neutral workflow.
- Selecting column 3 or 4 from one combined index during conversion makes one
  list describe two datasets and obscures provenance.
- Sorting a filename glob would discard the authoritative source index order.

## Input contract

Each nonblank, non-comment normalized-list row contains exactly:

```text
YYYYMMDDTHHMMSS relative/or/absolute/path.tif
```

Epoch identifiers and paths must be unique. Relative TIFF paths resolve from
the list directory. Every listed TIFF must be a readable, single-band raster
and all deformation TIFFs must share CRS, transform, shape, registration, and
dtype compatibility. Unknown header text or extra columns are rejected.

The cfg explicitly supplies:

- normalized index, DEM, and static mask paths;
- output directory, prefix, extension, and selected epochs;
- source and output units plus deformation scale;
- explicit source CRS (validated against TIFF metadata), output CRS, and
  deformation quantity;
- mask predicate, nodata policy, time/spatial references, and provenance;
- downsampling mode/target, aggregation, chunk rows, optional GeoTIFF output,
  and overwrite policy.

The generic workflow records source values/sign as preserved and uninterpreted;
it does not label a series LOS, EW, or UD. For compatibility with the current
required metadata contract, `los_positive` is explicitly recorded as
`source_values_preserved_direction_unknown`; it is not inferred.

## Raster and validity behavior

- Rasterio windows provide bounded reads. Windows are aggregated directly into
  the smaller downsampled arrays; only those smaller arrays are materialized
  for final reprojection/export. The existing full-grid
  `prepare_defsour_epoch` API is not used on native MSBAS rasters.
- The explicit static mask defines spatial support. A deformation value of zero
  is valid inside that support, including the all-zero reference epoch.
- TIFF nodata value `0.0` is therefore not used to invalidate deformation by
  value. Non-finite deformation remains invalid.
- DEM is explicitly reprojected/resampled to the working grid using bilinear
  values and nearest-neighbour validity; finite DEM and positive static mask
  are required for output. Static-mask cells outside DEM coverage cause a
  validation failure rather than silent clipping.
- Downsampling uses the existing shared-mask mean/median semantics. CRS
  reprojection occurs at the named export boundary.
- Each output epoch is a headerless `X Y elevation deformation` point table.

## Hawaii execution configuration

Prepare four normalized lists separately beside the source data, then create
four configs/snapshots:

| Source | Generated list | Static mask | Proposed output |
|---|---|---|---|
| `msbas1d_087_dsc` | `MSBAS_TSOUT_LOS.txt` | `MSBAS_TEMP_COH_M.tif > 0` | `DATA_DEFSOURCE_LOS` |
| `msbas1d_124_asc` | `MSBAS_TSOUT_LOS.txt` | `MSBAS_TEMP_COH_M.tif > 0` | `DATA_DEFSOURCE_LOS` |
| `msbas2d_r2_005_af_coh03` | `MSBAS_TSOUT_EW.txt` | `MSBAS_TEMP_COH_M.tif > 0` | `DATA_DEFSOURCE_EW` |
| `msbas2d_r2_005_af_coh03` | `MSBAS_TSOUT_UD.txt` | `MSBAS_TEMP_COH_M.tif > 0` | `DATA_DEFSOURCE_UD` |

Proposed explicit scientific/export settings, pending user confirmation:

- source deformation unit: metres;
- output deformation unit: millimetres, scale `1000`;
- height source: `Hawaii/mintpy/DES_Hawaii/DATA_DEM_NATIVE/dem.tif`, because it
  covers the complete MSBAS extent; output height unit metres;
- output CRS: `EPSG:32605`, consistent with existing Hawaii Defsour products;
- temporal reference: preserve the MSBAS reference epoch;
- zero: valid within the positive static mask;
- target: approximately 100,000 points per epoch using mean aggregation,
  consistent with existing Hawaii Defsour snapshots;
- `date=YYYYMMDD` remains available for compatibility, while a new optional
  `epoch_id=YYYYMMDDTHHMMSS` is retained in the result model, manifest, and
  output filename to avoid losing acquisition identity;
- direction metadata: `source_values_preserved_direction_unknown`;
- spatial reference: preserve the upstream MSBAS spatial reference without
  applying a new spatial re-reference;
- overwrite: atomically replace the four named output snapshots if they
  already exist.

## Validation and tests

- Index tests cover two-column parsing, ordering, malformed rows, duplicate
  epochs/paths, and missing TIFFs.
- Synthetic GeoTIFF workflow tests cover an all-zero valid reference epoch,
  explicit mask support, DEM alignment/reprojection, unit scaling,
  downsampling, exact epoch IDs, atomic publication, and cfg rejection.
- CLI tests cover list preparation and `export-geotiff-defsour` routing.
- Existing workflows retain their current `YYYYMMDD` behavior when the new
  optional `epoch_id` is absent.
- User-facing documentation and cfg templates are bilingual, English followed
  immediately by Chinese, as required by the repository contract.
- Before full Hawaii publication, run a small selected-epoch smoke conversion,
  inspect point counts/value ranges/CRS, then run all four snapshots and verify
  manifests and product counts.

## Constraints and safety

- The converter treats TIFFs and prepared lists as read-only and never parses,
  edits, or replaces `MSBAS_TSOUT.txt`.
- Existing user edits in README and architecture documentation are preserved.
- Whole output snapshots are atomically replaced only after every selected
  epoch succeeds.
