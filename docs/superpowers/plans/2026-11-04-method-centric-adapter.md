# Method-Centric Data Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Adapter overwrite behavior internally consistent and support method-root canonical/export defaults without taking ownership of scientific processing paths.

**Architecture:** Adapter conversions remain explicit, source-read-only, bounded-memory operations. Existing targets are atomically replaced after validation; optional project context derives `CANONICAL` and `EXPORT` defaults while direct library calls keep explicit output paths.

**Tech Stack:** Python 3.11, NumPy, h5py, Rasterio, pathlib, unittest/pytest

**Spec:** `../Geodesy-2Analysis/docs/superpowers/specs/2026-11-04-method-centric-project-layout-design.md`

## Global Constraints

- Never mutate source products.
- Always stage, validate, and atomically replace generated outputs.
- Preserve explicit units, LOS sign, CRS, nodata, temporal reference, and provenance.
- Do not infer wavelength or units from sensor names.
- Use envInSAR for focused tests.

## Review Focus

- Existing outputs must remain intact when conversion fails.
- Source and destination identity or overlap must be rejected.
- Method-root defaults must remain inside the declared case.
- Phase conversion metadata units must match conversion direction.
- Existing direct callers with explicit output paths must remain compatible.

---

### Task 1: Resolve overwrite contract drift

**Files:**
- Modify: `tests/test_phase_conversion.py`
- Modify: tests for canonical, GeoTIFF, Defsour, MintPy, LiCSBAS, and GAMMA writers
- Modify: `README.md`
- Modify: `docs/cfg_contract.md`
- Modify: `src/insar_data_adapter/converters/phase.py` only if tests expose inconsistent behavior

**Interfaces:**
- Retains: public converter signatures with `overwrite: bool = True`
- Produces: consistent documentation that default calls atomically replace existing outputs

- [ ] **Step 1:** Change the stale phase test to assert successful default replacement and add a failure-preserves-old-output assertion.
- [ ] **Step 2:** Run `test_phase_conversion.py` and confirm the current contradictory expectation is removed without weakening failure safety.
- [ ] **Step 3:** Align all overwrite-default tests and bilingual documentation.
- [ ] **Step 4:** Run focused conversion/writer tests.
- [ ] **Step 5:** Commit as `fix: align adapter atomic overwrite contract`.

### Task 2: Optional method-root output derivation

**Files:**
- Create: `src/insar_data_adapter/project_layout.py`
- Create: `tests/test_project_layout.py`
- Modify: `src/insar_data_adapter/config.py`
- Modify: `src/insar_data_adapter/__init__.py`
- Modify: relevant `config_examples/*.cfg`

**Interfaces:**
- Produces: `AdapterProjectLayout.bind(project_root, project, processing_root)`
- Produces: `.canonical(name)` and `.export(name)` paths
- Existing explicit `output_file` remains authoritative

- [ ] **Step 1:** Add failing tests for `CANONICAL`, `EXPORT`, containment, explicit-output precedence, and paths outside the case.
- [ ] **Step 2:** Run the new test and confirm import failure.
- [ ] **Step 3:** Implement the optional layout and config parsing without changing direct converter APIs.
- [ ] **Step 4:** Add required CFG path-contract comments to conversion examples.
- [ ] **Step 5:** Run config and project-layout tests.
- [ ] **Step 6:** Commit as `feat: add adapter method-root output defaults`.

### Task 3: Verification and public documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/cfg_contract.md`

**Interfaces:**
- Documents: Adapter owns `CANONICAL` and `EXPORT`, not `INTF`, `UNW`, or `FIGURES`

- [ ] **Step 1:** Update architecture examples and public API examples with method-root use and explicit-output compatibility.
- [ ] **Step 2:** Run focused tests, `compileall`, and `git diff --check`.
- [ ] **Step 3:** Commit as `docs: describe adapter method-root integration`.
