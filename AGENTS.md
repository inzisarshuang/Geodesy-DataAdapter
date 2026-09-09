# InSAR-Data-Adapter Coding Baseline

Read `docs/architecture.md`, `docs/data_schema.md`, and `docs/cfg_contract.md`
before changing public interfaces or scientific metadata.

- Keep source readers, the canonical data model, exporters, and CLI orchestration separate.
- Treat every input as read-only. Write outputs through a sibling temporary file and replace atomically.
- Never infer deformation units, LOS sign, CRS, nodata, byte order, registration, or references silently.
- Read large arrays by HDF5 slice, raster window, or NumPy memmap; never use an unconditional full-cube read.
- Resolve relative paths from the cfg file directory and enforce CLI > cfg > default precedence.
- Reject unknown cfg keys, inconsistent dimensions, unsupported schema versions, and ambiguous metadata.
- Preserve source provenance and record transformations at every output boundary.
- Add synthetic regression tests for every source adapter and numerical conversion.
- Keep README and user-facing documentation bilingual, with English immediately followed by Chinese.

Phase boundaries matter: do not connect downstream repositories until the relevant adapter contract and tests are stable.
