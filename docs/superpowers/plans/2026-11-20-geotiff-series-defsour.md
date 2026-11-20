# GeoTIFF Series to Defsour Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded-memory, config-driven conversion from one indexed single-band GeoTIFF time series to one transactional Defsour snapshot.

**Architecture:** A source-neutral list/raster reader validates epochs and profiles. A new Defsour workflow streams source windows into downsampled grids and reuses existing reprojection, export, metadata, and atomic publication components; preparing Hawaii lists remains a separate one-time data operation outside the adapter.

**Tech Stack:** Python 3.10+, NumPy, Rasterio, pyproj, affine, pathlib/dataclasses/tempfile, pytest in `envInSAR`.

**Spec:** `docs/superpowers/specs/2026-11-20-geotiff-series-defsour-design.md`

## Global Constraints

- Inputs are read-only; the adapter never parses, splits, edits, or replaces `MSBAS_TSOUT.txt`.
- Never infer units, CRS, sign, nodata behavior, references, or mask semantics silently.
- One normalized list contains exactly one scalar time series and preserves source order.
- Read native deformation, DEM, and mask rasters by bounded Rasterio windows; never materialize a native 4400×4733 time cube.
- Resolve relative paths from the cfg/list file that owns them and reject unknown cfg keys.
- Preserve existing GAMMA, MintPy, and LiCSBAS behavior when `epoch_id` is absent.
- User-facing documentation and cfg templates are bilingual, English immediately followed by Chinese.
- Do not alter the user's existing README/architecture edits beyond narrow additions required for this feature.

## Review Focus

- A real zero inside a positive static mask must survive even when the TIFF declares nodata `0.0` (Task 4 test).
- A DEM that fails to cover any positive-mask cell must fail instead of silently dropping it (Task 3 test).
- Duplicate exact timestamps or TIFF paths must be rejected before publication (Task 2 test).
- Different CRS/transform/shape in a later epoch must abort the complete snapshot atomically (Task 4 test).
- Two acquisitions on one calendar date must remain distinct through `epoch_id` while legacy date-only workflows remain unchanged (Task 1 test).

---

### Task 1: Exact epoch identity in snapshot metadata

**Files:**
- Modify: `src/insar_data_adapter/workflows/defsour/models.py`
- Modify: `src/insar_data_adapter/workflows/defsour/publication.py`
- Test: `tests/test_defsour_snapshot.py`

**Interfaces:**
- Consumes: existing `DefsourEpochResult(date, defsour_path, point_count, geotiff_path)` calls.
- Produces: optional `DefsourEpochResult.epoch_id: str | None`; manifest epoch entries include `epoch_id`, while top-level `dates` remains `YYYYMMDD`.

- [ ] **Step 1: Write failing compatibility and exact-identity tests**

Add tests asserting legacy construction still serializes `epoch_id: null`, exact `20240101T123456` is accepted, malformed IDs are rejected, and two epochs with the same date but distinct exact IDs are allowed while duplicate effective identities are rejected.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_defsour_snapshot.py`

- [ ] **Step 3: Implement the optional identity field and manifest serialization**

Extend `DefsourEpochResult` without changing existing positional argument meaning. Validate `epoch_id` with `\d{8}T\d{6}` plus calendar/time parsing. Make snapshot uniqueness use `epoch_id` when present and date otherwise.

- [ ] **Step 4: Run focused and legacy workflow-model tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_defsour_snapshot.py tests/test_gamma_defsour_workflow.py tests/test_mintpy_defsour_workflow.py tests/test_licsbas_defsour_workflow.py`

- [ ] **Step 5: Commit only Task 1 files**

```bash
git add src/insar_data_adapter/workflows/defsour/models.py src/insar_data_adapter/workflows/defsour/publication.py tests/test_defsour_snapshot.py
git commit -m "feat: preserve exact Defsour epoch identity"
```

### Task 2: Generic GeoTIFF series index

**Files:**
- Create: `src/insar_data_adapter/sources/geotiff_series.py`
- Modify: `src/insar_data_adapter/sources/__init__.py`
- Create: `tests/test_geotiff_series_source.py`

**Interfaces:**
- Produces: immutable `GeoTIFFSeriesEpoch(epoch_id: str, date: str, path: Path)` and `read_geotiff_series_index(index_file: str | Path) -> tuple[GeoTIFFSeriesEpoch, ...]`.

- [ ] **Step 1: Write failing generic-list tests**

Assert two-column parsing, relative-path resolution from the list directory, comment/blank handling, exact order, duplicate epoch/path rejection, malformed/extra columns, and missing/non-file TIFF rejection.

- [ ] **Step 2: Run the list tests and verify failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_geotiff_series_source.py`

- [ ] **Step 3: Implement the strict generic-list reader**

Parse exactly `epoch_id path`, resolve relative paths from the list directory,
and preserve input order without any MSBAS-specific filename interpretation.

- [ ] **Step 4: Run the focused suite**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_geotiff_series_source.py`

- [ ] **Step 5: Commit only Task 2 files**

```bash
git add src/insar_data_adapter/sources/geotiff_series.py src/insar_data_adapter/sources/__init__.py tests/test_geotiff_series_source.py
git commit -m "feat: read indexed GeoTIFF series"
```

### Task 3: GeoTIFF Defsour configuration and windowed grid preparation

**Files:**
- Modify: `src/insar_data_adapter/workflows/defsour/config.py`
- Create: `src/insar_data_adapter/workflows/defsour/geotiff_series.py`
- Create: `tests/test_geotiff_defsour_config.py`
- Create: `tests/test_geotiff_defsour_windows.py`

**Interfaces:**
- Produces: frozen `GeoTIFFDefsourConfig(DefsourWorkflowConfig)` with `index_file`, `height_file`, `mask_file`, `source_unit`, `mask_mode`, and exact-epoch selection.
- Produces: `load_geotiff_defsour_config(config_file: str | Path) -> GeoTIFFDefsourConfig`.
- Produces internal `_prepare_static_grid(...)` and `_prepare_epoch_grid(...)` helpers returning small `PreparedDefsourGrid`-compatible arrays/profile.

- [ ] **Step 1: Write failing strict-cfg tests**

Test path resolution, explicit source CRS/unit, metre-to-millimetre compatibility, `mask_mode=positive`, exact epoch selection, unknown keys, missing required files/metadata, and all three downsampling modes.

- [ ] **Step 2: Run cfg tests and verify failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_geotiff_defsour_config.py`

- [ ] **Step 3: Implement config types and loader**

Reuse shared validation where semantics match, but keep exact epoch selection separate from the legacy `dates` parser.

- [ ] **Step 4: Write failing synthetic window tests**

Create small GeoTIFF fixtures and assert bounded window reads, positive-mask validity, bilinear DEM/nearest validity alignment, mean and median shared-mask aggregation, real zero preservation despite source nodata `0.0`, factor cropping, and failure when the DEM lacks positive-mask coverage.

- [ ] **Step 5: Implement windowed static and epoch preparation**

Use `WarpedVRT` to expose DEM/mask on the source grid. Read at most `chunk_rows` native rows, aggregate directly to downsampled arrays, then reuse the existing small-grid reprojection APIs.

- [ ] **Step 6: Run focused grid/config tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_geotiff_defsour_config.py tests/test_geotiff_defsour_windows.py tests/test_defsour_grid_workflow.py tests/test_defsour_alignment.py`

- [ ] **Step 7: Commit only Task 3 files**

```bash
git add src/insar_data_adapter/workflows/defsour/config.py src/insar_data_adapter/workflows/defsour/geotiff_series.py tests/test_geotiff_defsour_config.py tests/test_geotiff_defsour_windows.py
git commit -m "feat: prepare GeoTIFF Defsour grids by window"
```

### Task 4: Transactional GeoTIFF-series workflow

**Files:**
- Modify: `src/insar_data_adapter/workflows/defsour/geotiff_series.py`
- Modify: `src/insar_data_adapter/workflows/defsour/__init__.py`
- Create: `tests/test_geotiff_defsour_workflow.py`

**Interfaces:**
- Consumes: Task 2 index reader, Task 3 config/preparation, existing `write_defsour_grid`, `write_geotiff`, and `publish_defsour_snapshot`.
- Produces: `export_geotiff_defsour(config: GeoTIFFDefsourConfig) -> DefsourSnapshotMetadata`.

- [ ] **Step 1: Write failing end-to-end synthetic workflow tests**

Assert exact index order, selected epochs, `date` plus `epoch_id`, output names, metre-to-millimetre scaling exactly once, all-zero reference epoch point retention, about-target point selection, output CRS, manifest/provenance, optional GeoTIFFs, and complete atomic replacement.

- [ ] **Step 2: Add failure-atomicity tests**

Assert a later epoch with changed shape/transform/CRS, duplicate identity, or unreadable raster leaves an existing output snapshot untouched.

- [ ] **Step 3: Run workflow tests and verify failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_geotiff_defsour_workflow.py`

- [ ] **Step 4: Implement `export_geotiff_defsour`**

Validate output/input separation and every epoch profile, prepare static grids once, stream each selected epoch, scale once at export, write exact-ID filenames, record source values/sign as preserved/uninterpreted, and publish only after all epochs validate.

- [ ] **Step 5: Run all Defsour workflow tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_*defsour* tests/test_geotiff_series_source.py`

- [ ] **Step 6: Commit only Task 4 files**

```bash
git add src/insar_data_adapter/workflows/defsour/geotiff_series.py src/insar_data_adapter/workflows/defsour/__init__.py tests/test_geotiff_defsour_workflow.py
git commit -m "feat: export GeoTIFF series to Defsour"
```

### Task 5: CLI, template, packaging, and bilingual documentation

**Files:**
- Modify: `src/insar_data_adapter/cli.py`
- Create: `config/data2defsour/geotiff2defsour.cfg`
- Modify: `pyproject.toml`
- Modify narrowly: `README.md`
- Modify narrowly: `docs/architecture.md`
- Modify narrowly: `docs/workflows_and_api.md`
- Modify: `tests/test_defsour_cli.py`
- Modify: `tests/test_config.py` or add assertions to `tests/test_geotiff_defsour_config.py`

**Interfaces:**
- Produces CLI command `export-geotiff-defsour --config PATH`.

- [ ] **Step 1: Write failing CLI and packaged-config tests**

Assert argument requirements, dispatch, summary output with exact IDs, strict config-tree membership, and inclusion of the new cfg in package data.

- [ ] **Step 2: Run CLI tests and verify failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_defsour_cli.py tests/test_geotiff_defsour_config.py`

- [ ] **Step 3: Implement CLI routing and the bilingual cfg template**

Add only the source-neutral export command.

- [ ] **Step 4: Add narrow bilingual documentation**

Document one-list/one-conversion behavior, exact list grammar, required scientific metadata, explicit mask handling for real zero values, and both commands without rewriting unrelated user-edited sections.

- [ ] **Step 5: Run the complete suite**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Inspect the final diff and confirm no Hawaii conversion outputs exist**

Run: `git status --short` and `git diff --check`.

Expected: only intended source/tests/template/docs plus the spec/plan are changed; no files under `Hawaii/MSBAS` are created.

- [ ] **Step 7: Commit only Task 5 and design/plan files**

```bash
git add src/insar_data_adapter/cli.py config/data2defsour/geotiff2defsour.cfg pyproject.toml README.md docs/architecture.md docs/workflows_and_api.md tests/test_defsour_cli.py tests/test_geotiff_defsour_config.py docs/superpowers/specs/2026-11-20-geotiff-series-defsour-design.md docs/superpowers/plans/2026-11-20-geotiff-series-defsour.md
git commit -m "docs: publish GeoTIFF Defsour workflow"
```
