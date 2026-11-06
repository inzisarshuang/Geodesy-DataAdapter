# Defsour Workflow Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate complete GAMMA, MintPy, and LiCSBAS-to-Defsour workflows from the legacy Toolbox into strict, bounded-memory, transactional DataAdapter commands.

**Architecture:** Add a source-neutral `workflows/defsour/` orchestration layer above existing read-only sources, grid/raster transforms, and the atomic Defsour writer. Each source adapter supplies validated epoch blocks and explicit metadata; shared code handles date selection, temporal reference, downsampling, reprojection, optional alignment templates, GeoTIFF creation, snapshot manifests, and whole-directory publication.

**Tech Stack:** Python 3.10+, NumPy, h5py, pyproj, rasterio, stdlib dataclasses/pathlib/json/tempfile, pytest/unittest in `envInSAR`.

**Spec:** `/mnt/beegfs/procesados/yiluntan/Geodesy-Analysis/docs/superpowers/specs/2026-11-06-gamma-postprocessing-defsour-migration-design.md`

## Global Constraints

- Run focused checks with `/home/yilun/miniconda3/envs/envInSAR/bin/python`; do not create or repair environments.
- Do not import runtime code from `GAMMA-InSAR/2-GAMMA-POST/Toolbox_InSAR`.
- Inputs are read-only; one complete export directory replaces its predecessor only after every epoch and metadata file validates.
- Read time-series inputs by epoch and bounded row/window blocks; never load an entire time cube.
- Never infer CRS, units, LOS sign, nodata/zero policy, byte order, grid registration, temporal reference, or spatial reference.
- Resolve CFG-relative paths from the CFG directory; reject malformed, duplicate, blank, and unknown keys.
- Preserve CLI > CFG > code-default precedence; all three new CLI commands require `--config`.
- Direct source-to-Defsour export remains available; canonical HDF5 is optional.
- DataAdapter may atomically replace its inexpensive generated outputs.
- Do not execute the new workflow on real Gansu data; prepare runtime CFGs for user testing.

## Review Focus

- Failure on the final epoch must leave the previous complete export directory byte-for-byte available; test this in Task 1 and each source workflow task.
- Date selection/reference combinations must reject duplicate, missing, and reference-outside-selection dates before output mutation; test this in Tasks 3-6.
- An alignment template with conflicting CRS, registration, dimensions, transform, factor, or coordinate order must fail; test this in Task 2.
- Finite zero deformation/height must remain valid unless the explicit mask/nodata policy excludes it; test this in Tasks 2 and 4-6.
- Optional Analysis `source_manifest` metadata/path disagreement must fail rather than override explicit CFG silently; test this in Tasks 3 and 4.

---

### Task 1: Add Transactional Defsour Snapshot Publication

**Files:**
- Create: `src/insar_data_adapter/workflows/__init__.py`
- Create: `src/insar_data_adapter/workflows/defsour/__init__.py`
- Create: `src/insar_data_adapter/workflows/defsour/models.py`
- Create: `src/insar_data_adapter/workflows/defsour/publication.py`
- Test: `tests/test_defsour_snapshot.py`

**Interfaces:**
- Produces: `DefsourSnapshotMetadata` and `DefsourEpochResult` frozen dataclasses.
- Produces: `publish_defsour_snapshot(output_dir: Path, build: Callable[[Path], DefsourSnapshotMetadata], *, overwrite: bool = True) -> DefsourSnapshotMetadata`.
- Publishes: epoch text files, optional GeoTIFFs/template, `README_DEFSOUR.txt`, and `defsour_manifest.json`; the manifest is written last inside staging and declares `schema_version = 1`, `status = complete`, required products, dates, point counts, metadata, and transformations.

- [ ] **Step 1: Write failing whole-snapshot atomicity tests**

Test successful absent publish, successful replacement, `overwrite = false`, a builder failure after writing several staged files, validation failure for missing/empty required products, and recovery when final directory replacement raises.

- [ ] **Step 2: Run and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_defsour_snapshot.py`

Expected: FAIL because the workflow package does not exist.

- [ ] **Step 3: Implement staging, validation, replacement, and rollback**

Use a sibling staging directory and backup/restore sequence equivalent to the repository's atomic file guarantee; never mutate the old directory before the new snapshot is complete.

- [ ] **Step 4: Run focused snapshot tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_defsour_snapshot.py tests/test_defsour_export.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/insar_data_adapter/workflows tests/test_defsour_snapshot.py
git commit -m "feat: publish transactional Defsour snapshots"
```

### Task 2: Add Shared Grid, Profile, Alignment, and GeoTIFF Helpers

**Files:**
- Create: `src/insar_data_adapter/workflows/defsour/grid.py`
- Create: `src/insar_data_adapter/workflows/defsour/alignment.py`
- Create: `src/insar_data_adapter/exporters/geotiff.py`
- Modify: `src/insar_data_adapter/exporters/__init__.py`
- Test: `tests/test_defsour_grid_workflow.py`
- Test: `tests/test_defsour_alignment.py`
- Test: `tests/test_geotiff_export.py`

**Interfaces:**
- Produces: `GridProfile` wrapper with explicit shape, CRS, affine transform, and pixel registration.
- Produces: `coordinate_arrays(profile: GridProfile) -> tuple[np.ndarray, np.ndarray]`.
- Produces: `select_downsample_factor(mode, *, source_profile, valid_count, factor, target_points, target_pixel_size) -> int`.
- Produces: `prepare_defsour_epoch(height, deformation, valid, source_profile, *, factor, aggregation, destination_profile=None) -> PreparedDefsourGrid`.
- Produces: `save_alignment_template(path, template)`, `load_alignment_template(path)`, and strict `DefsourAlignmentTemplate` validation.
- Produces: `write_geotiff(path, values, valid_mask, profile, *, unit, quantity, nodata=np.nan) -> Path` using a sibling temporary file.

- [ ] **Step 1: Write failing profile/factor/grid tests**

Cover factor/target-points/target-pixel-size modes, incomplete edge dropping, zero preservation, mean/median behavior, invalid cells excluded from aggregation, CRS/profile-required reprojection, and coordinate centre ordering.

- [ ] **Step 2: Run and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_defsour_grid_workflow.py`

Expected: FAIL because the shared workflow helpers do not exist.

- [ ] **Step 3: Implement shared grid preparation by composing existing APIs**

Call `build_defsour_valid_mask`, `downsample_data_grid`, and `reproject_downsampled_grid_to_profile`; do not duplicate their numerical algorithms.

- [ ] **Step 4: Write failing alignment-template tests**

Round-trip one template and reject missing fields, object arrays/pickle requirements, mismatched shape/CRS/registration/transform/factor, non-finite coordinates, and coordinate-order changes.

- [ ] **Step 5: Implement safe `.npz` alignment persistence**

Load with `allow_pickle=False`; store only numeric arrays and JSON-safe scalar metadata.

- [ ] **Step 6: Write and implement atomic GeoTIFF tests**

Assert profile, nodata, unit/quantity tags, valid mask application, overwrite behavior, and preservation of an existing file on a forced writer failure.

- [ ] **Step 7: Run all focused helper tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_defsour_grid_workflow.py tests/test_defsour_alignment.py tests/test_geotiff_export.py tests/test_grid.py tests/test_raster.py`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/insar_data_adapter/workflows/defsour src/insar_data_adapter/exporters tests/test_defsour_grid_workflow.py tests/test_defsour_alignment.py tests/test_geotiff_export.py
git commit -m "feat: add Defsour grid preparation"
```

### Task 3: Add Strict Source-specific Defsour CFG Contracts

**Files:**
- Create: `src/insar_data_adapter/workflows/defsour/config.py`
- Modify: `src/insar_data_adapter/project_layout.py`
- Test: `tests/test_defsour_config.py`
- Test: `tests/test_project_layout.py`

**Interfaces:**
- Produces: `load_gamma_defsour_config(path) -> GammaDefsourConfig`.
- Produces: `load_mintpy_defsour_config(path) -> MintPyDefsourConfig`.
- Produces: `load_licsbas_defsour_config(path) -> LiCSBASDefsourConfig`.
- Shared keys: explicit output path or project/method context, dates, prefix/extension, output CRS, four-column format, deformation scale/output unit, temporal reference, metadata fields, downsample mode/options, aggregation, chunk rows, `write_tif`, and `overwrite`.
- GAMMA-only keys: tab/dates files, parameter/DEM/mask, optional lon/lat, explicit dtypes/byte orders/nodata, `mode = native|aligned`, optional alignment template, invalid-point policy, optional Analysis source manifest.
- MintPy-only keys: time-series/geometry/mask, dataset names, optional native GeoTIFF/velocity/DEM exports.
- LiCSBAS-only keys: input file and dataset names.
- Output default: `<processing_root>/EXPORT/DEFSOUR/<source>` through `AdapterProjectLayout.defsour(source)`.

- [ ] **Step 1: Write failing strict CFG tests**

Cover every required/conditional key, relative paths, metadata non-blank rules, explicit output unit matching scale intent, date syntax/uniqueness, valid format, mode/downsample enums, numeric ranges, unknown/duplicate keys, and method-root output defaults.

- [ ] **Step 2: Run and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_defsour_config.py tests/test_project_layout.py`

Expected: FAIL because loaders/layout method do not exist.

- [ ] **Step 3: Implement frozen configs and layout method**

Reuse the existing strict line parser where practical; keep source-specific allowed-key sets separate so one source cannot accept another source's options.

- [ ] **Step 4: Add optional Analysis manifest disagreement tests**

Assert incomplete status, wrong method, date/path/grid/unit disagreement, traversal paths, and bad digest fail; omission leaves GAMMA as a generic raw-input workflow.

- [ ] **Step 5: Run focused config tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_defsour_config.py tests/test_project_layout.py tests/test_config.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insar_data_adapter/workflows/defsour/config.py src/insar_data_adapter/project_layout.py tests/test_defsour_config.py tests/test_project_layout.py
git commit -m "feat: define Defsour workflow configs"
```

### Task 4: Migrate GAMMA-to-Defsour

**Files:**
- Create: `src/insar_data_adapter/workflows/defsour/gamma.py`
- Modify: `src/insar_data_adapter/sources/gamma.py`
- Modify: `src/insar_data_adapter/sources/gamma_radar.py`
- Test: `tests/test_gamma_defsour_workflow.py`

**Interfaces:**
- Produces: `export_gamma_defsour(config: GammaDefsourConfig) -> DefsourSnapshotMetadata`.
- Supports regular geocoded GAMMA grids and explicit radar-grid lon/lat coordinates, `native` and `aligned` modes, masks/mask intersection, explicit temporal reference, all three downsample modes, optional GeoTIFF, and alignment-template creation/reuse.
- Optional `source_manifest` validates Analysis output but does not replace explicit CFG metadata.

- [ ] **Step 1: Write a failing native synthetic workflow test**

Use two small big-endian epochs with explicit DEM/mask/grid and assert dates, temporal reference, scaling, zero preservation, point order/count, GeoTIFF, README, manifest transformations, and no source mutation.

- [ ] **Step 2: Run and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_defsour_workflow.py`

Expected: FAIL because `export_gamma_defsour` does not exist.

- [ ] **Step 3: Implement native epoch-bounded export**

Read one epoch at a time through memmap/source rows, apply explicit temporal reference without materializing a cube, prepare the grid, write staged Defsour/GeoTIFF, and return complete snapshot metadata.

- [ ] **Step 4: Add and implement aligned-mode tests**

First export creates a template; a second differently located grid reuses it. Reject template conflicts and test `export_invalid_points` row skeleton semantics.

- [ ] **Step 5: Add failure/transaction/manifest-validation tests**

Force a second-epoch error and assert the old snapshot remains; cover duplicate dates, wrong byte counts, finite nodata, mask intersection, and optional Analysis manifest disagreement.

- [ ] **Step 6: Run focused GAMMA tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_defsour_workflow.py tests/test_gamma_conversion.py tests/test_gamma_radar.py tests/test_defsour_snapshot.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/insar_data_adapter/workflows/defsour/gamma.py src/insar_data_adapter/sources/gamma.py src/insar_data_adapter/sources/gamma_radar.py tests/test_gamma_defsour_workflow.py
git commit -m "feat: migrate GAMMA Defsour export"
```

### Task 5: Migrate MintPy-to-Defsour

**Files:**
- Create: `src/insar_data_adapter/workflows/defsour/mintpy.py`
- Modify: `src/insar_data_adapter/sources/mintpy.py`
- Test: `tests/test_mintpy_defsour_workflow.py`

**Interfaces:**
- Produces: `export_mintpy_defsour(config: MintPyDefsourConfig) -> DefsourSnapshotMetadata`.
- Supports selected dates, explicit temporal reference/scaling/CRS, mask and DEM, downsampled Defsour/GeoTIFF, optional native epoch GeoTIFFs, optional native velocity and DEM GeoTIFFs, and `native_only`.

- [ ] **Step 1: Write failing synthetic HDF5 workflow tests**

Assert REF_DATE/reference pixel preservation, selected/explicit reference dates, mask and NaN handling, output units, Defsour point order, native/downsampled products, velocity/DEM exports, and bounded epoch reads.

- [ ] **Step 2: Run and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_mintpy_defsour_workflow.py`

Expected: FAIL because `export_mintpy_defsour` does not exist.

- [ ] **Step 3: Implement MintPy workflow from existing source APIs**

Use explicit configured geometry/mask/velocity inputs; do not auto-discover sibling files or read the full time-series dataset.

- [ ] **Step 4: Add transaction and invalid-input tests**

Cover source attribute conflicts, missing dataset, date errors, reference outside selection, finite zeros, final-epoch failure, and native-only incompatible options.

- [ ] **Step 5: Run focused MintPy tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_mintpy_defsour_workflow.py tests/test_mintpy_conversion.py tests/test_defsour_snapshot.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insar_data_adapter/workflows/defsour/mintpy.py src/insar_data_adapter/sources/mintpy.py tests/test_mintpy_defsour_workflow.py
git commit -m "feat: migrate MintPy Defsour export"
```

### Task 6: Migrate LiCSBAS-to-Defsour

**Files:**
- Create: `src/insar_data_adapter/workflows/defsour/licsbas.py`
- Modify: `src/insar_data_adapter/sources/licsbas.py`
- Test: `tests/test_licsbas_defsour_workflow.py`

**Interfaces:**
- Produces: `export_licsbas_defsour(config: LiCSBASDefsourConfig) -> DefsourSnapshotMetadata`.
- Supports selected dates, explicit units/LOS/nodata/CRS, LiCSBAS mask/DEM/refarea, temporal reference/scaling, downsampling/reprojection, Defsour, and optional GeoTIFF.

- [ ] **Step 1: Write failing synthetic LiCSBAS workflow tests**

Assert `/cum`, `/imdates`, `/hgt`, `/mask`, coordinates, refarea, selected dates, temporal reference, explicit scaling, output order/count, GeoTIFF and manifest metadata.

- [ ] **Step 2: Run and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_licsbas_defsour_workflow.py`

Expected: FAIL because `export_licsbas_defsour` does not exist.

- [ ] **Step 3: Implement LiCSBAS workflow from the bounded source**

Read one epoch and row blocks, compose the shared grid/export helpers, and publish one snapshot.

- [ ] **Step 4: Add transaction and invalid-input tests**

Cover malformed refarea, metadata conflicts, date/reference errors, mask/shape mismatch, zeros, and a late failure preserving the old snapshot.

- [ ] **Step 5: Run focused LiCSBAS tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_licsbas_defsour_workflow.py tests/test_licsbas_conversion.py tests/test_defsour_snapshot.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/insar_data_adapter/workflows/defsour/licsbas.py src/insar_data_adapter/sources/licsbas.py tests/test_licsbas_defsour_workflow.py
git commit -m "feat: migrate LiCSBAS Defsour export"
```

### Task 7: Expose CLI Commands, Reorganize Configs, and Prepare Gansu Handoff

**Files:**
- Modify: `src/insar_data_adapter/cli.py`
- Modify: `src/insar_data_adapter/__init__.py`
- Move: `config_examples/gamma_to_canonical.cfg` -> `config/data2canonical/gamma2canonical_h5.cfg`
- Move: `config_examples/mintpy_to_canonical.cfg` -> `config/data2canonical/mintpy2canonical_h5.cfg`
- Move: `config_examples/licsbas_to_canonical.cfg` -> `config/data2canonical/licsbas2canonical_h5.cfg`
- Move: `config_examples/inspect.cfg` -> `config/data2canonical/inspect_h5.cfg`
- Create: `config/data2defsour/{gamma2defsour,mintpy2defsour,licsbas2defsour}.cfg`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/cfg_contract.md`
- Modify: `docs/workflows_and_api.md`
- Create: `tests/test_defsour_cli.py`
- Modify: `tests/test_config.py`
- Create: `../Gansu_Jishishan_LT1/config/data2canonical/gamma2canonical_h5.cfg`
- Create: `../Gansu_Jishishan_LT1/config/data2defsour/gamma2defsour.cfg`
- Create: `../Gansu_Jishishan_LT1/config/data2defsour/REAL_DATA_TESTING.md`

**Interfaces:**
- Adds CLI subcommands `export-gamma-defsour`, `export-mintpy-defsour`, and `export-licsbas-defsour`, each requiring `--config`.
- Repository has one config tree named `config/`; `config_examples/` is removed.
- Canonical and `data2defsour` are direct categories with no redundant repository/stage layer.

- [ ] **Step 1: Write failing CLI/config-path tests**

Patch each workflow call and assert command dispatch, nonzero error behavior, success summary, required `--config`, new packaged paths, and absence of old names/references.

- [ ] **Step 2: Run and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_defsour_cli.py tests/test_config.py`

Expected: FAIL on missing commands and old config layout.

- [ ] **Step 3: Implement CLI dispatch and public exports**

Print output directory, dates, point counts, manifest, and optional GeoTIFF/template counts without dumping large data.

- [ ] **Step 4: Move/rename repository configs and update packaging/docs**

Every example uses bilingual path-contract comments, explicit scientific metadata, portable placeholder paths, and the exact CLI command.

- [ ] **Step 5: Add Gansu runtime CFG and handoff guide**

Point to the delivered GAMMA `mb` manifest/products when available by path, but do not execute conversion. Document expected `EXPORT/DEFSOUR/GAMMA` products and comparison checks.

- [ ] **Step 6: Run the complete focused DataAdapter gate**

Run:

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/python -m compileall -q src/insar_data_adapter
/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q \
  tests/test_defsour_export.py tests/test_defsour_snapshot.py \
  tests/test_defsour_grid_workflow.py tests/test_defsour_alignment.py \
  tests/test_geotiff_export.py tests/test_defsour_config.py \
  tests/test_gamma_defsour_workflow.py tests/test_mintpy_defsour_workflow.py \
  tests/test_licsbas_defsour_workflow.py tests/test_defsour_cli.py \
  tests/test_project_layout.py tests/test_config.py
git diff --check
```

Expected: compile succeeds, selected tests PASS, diff check silent.

- [ ] **Step 7: Commit repository changes**

```bash
git add src config tests docs README.md pyproject.toml
git commit -m "feat: expose source-to-Defsour workflows"
```

Leave Gansu project edits for its own repository/explicit handoff, as in the Analysis plan.

### Task 8: Final DataAdapter Review and Delivery Check

**Files:**
- Review only: all files changed by Tasks 1-7

**Interfaces:**
- Consumes all prior tasks and the Analysis handoff.
- Produces a final report distinguishing synthetic/software verification from pending user real-data acceptance.

- [ ] **Step 1: Audit legacy independence and bounded access**

Run `rg` to prove no imports or runtime paths reference `Toolbox_InSAR`; inspect each epoch loop to ensure no `dataset[...]` full-cube read.

- [ ] **Step 2: Audit snapshot and metadata contracts**

Confirm every command publishes one complete manifest, transformation provenance, explicit units/CRS/references/nodata, and no partial-file completion signal.

- [ ] **Step 3: Run the final focused verification once**

Repeat Task 7 Step 6 and record exact results; do not add unrelated environment tests.

- [ ] **Step 4: Verify no real data products were written**

Only code, tests, configs, and documentation may change in the repositories/project during implementation.

- [ ] **Step 5: Record delivery status**

List the three CLI commands and Gansu CFGs, state that real-data output comparison is pending the user's run, and retain legacy Toolbox entry points.
