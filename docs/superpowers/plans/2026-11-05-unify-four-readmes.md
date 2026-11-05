# Four-Repository README Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the four Geodesy stage repositories one bilingual top-level README structure and turn Geodesy-DataAdapter into a concise entry document without losing its detailed technical reference.

**Architecture:** Preserve repository-specific scientific explanations while standardizing the nine first-level sections. Move the current DataAdapter conversion and Python API manual into one linked reference file; update the other README files only where a shared section is missing or named differently.

**Tech Stack:** Markdown, Git, shell link checks, `rg`

**Spec:** `../specs/2026-11-05-readme-structure-design.md`

## Global Constraints

- The first-level section order is Repository Scope, Project Structure, Workflow Overview, Dependencies And Installation, Quick Start, Data And Output Behavior, Verification And Development, Security, and License Notice.
- Keep every README and user-facing reference bilingual, with English immediately followed by Chinese.
- Preserve every existing DataAdapter command, API example, unit convention, and scientific warning.
- Do not change production code, CFG files, CLI behavior, package metadata, or scientific behavior.
- Do not stage or commit unrelated working-tree changes or local example data.

## Review Focus

- Relative Markdown links must resolve from the README or reference file that contains them.
- DataAdapter examples moved to `docs/` must still use correct repository-relative paths.
- No detailed adapter capability may disappear during the split.
- Renumbered headings must remain continuous and unique in each README.
- Repository names and GitHub links must use the renamed local/remote identities.

---

### Task 1: Split and restructure Geodesy-DataAdapter documentation

**Files:**
- Modify: `Geodesy-DataAdapter/README.md`
- Create: `Geodesy-DataAdapter/docs/workflows_and_api.md`
- Modify: `Geodesy-DataAdapter/docs/superpowers/specs/2026-11-05-readme-structure-design.md`

**Interfaces:**
- Consumes: the current 17-section README and the approved nine-section skeleton
- Produces: a concise repository entry README and one complete detailed reference

- [ ] **Step 1:** Copy the existing detailed sections for MintPy, LiCSBAS, GAMMA, canonical grids and points, Defsour, headered points, GeoTIFF, units, export, aggregation, reprojection, and detailed verification into `docs/workflows_and_api.md`, adjusting relative links for the `docs/` location.
- [ ] **Step 2:** Rewrite README with the nine approved top-level sections, a source-to-canonical-to-export workflow, installation, one minimal CLI path, method-root output behavior, documentation links, verification, security, and current license status.
- [ ] **Step 3:** Mark the approved design status as `Approved` and verify all original README capability headings appear in either README or the detailed reference.
- [ ] **Step 4:** Run `rg -n '^## ' README.md docs/workflows_and_api.md` and a local Markdown-link existence check; expect nine ordered README sections and no missing relative file targets.
- [ ] **Step 5:** Commit only DataAdapter documentation as `docs: restructure adapter documentation`.

### Task 2: Align Geodesy-Preprocessing README headings

**Files:**
- Modify: `Geodesy-Preprocessing/README.md`

**Interfaces:**
- Consumes: the common nine-section skeleton
- Produces: the existing preprocessing guide with shared section names and order

- [ ] **Step 1:** Keep the current repository scope, structure, workflows, installation, quick start, data/log, and verification content; rename `Project Data And Logs` to `Data And Output Behavior`.
- [ ] **Step 2:** Keep Security as section 8 and add section 9 `License Notice / 许可说明` stating that no separate license file is currently bundled.
- [ ] **Step 3:** Check heading order and repository-relative Markdown links.
- [ ] **Step 4:** Run `git diff --check` and commit only README as `docs: align preprocessing readme structure`.

### Task 3: Complete Geodesy-Analysis README entry structure

**Files:**
- Modify: `Geodesy-Analysis/README.md`

**Interfaces:**
- Consumes: the common nine-section skeleton
- Produces: a complete Analysis entry guide without changing its workflow claims

- [ ] **Step 1:** Add section 1 `Repository Scope`, incorporating the existing opening and Current Scope content; renumber Project Structure through Data And Output Behavior as sections 2–6.
- [ ] **Step 2:** Add section 7 with the repository's established envInSAR test, compile, and `git diff --check` commands.
- [ ] **Step 3:** Add bilingual Security and License Notice sections without introducing new license terms.
- [ ] **Step 4:** Check heading order and links, run `git diff --check`, and commit only README as `docs: complete analysis readme structure`.

### Task 4: Align Geodesy-Visualization README headings and publish

**Files:**
- Modify: `Geodesy-Visualization/README.md`

**Interfaces:**
- Consumes: the common nine-section skeleton and the already complete Visualization guide
- Produces: the same guide with a repository-scope entry and shared numbering

- [ ] **Step 1:** Add section 1 `Repository Scope`, then renumber existing Project Structure through License Notice while retaining workflow and backend details unchanged; fold Author into Verification And Development or a subsection so the nine shared top-level sections remain exact.
- [ ] **Step 2:** Replace obsolete sibling-repository names such as `Geodesy-Data-Adapter` with `Geodesy-DataAdapter` and verify current GitHub/local names.
- [ ] **Step 3:** Run a four-repository heading-order and Markdown-link check plus `git diff --check` in every repository.
- [ ] **Step 4:** Commit only Visualization README as `docs: align visualization readme structure`.
- [ ] **Step 5:** Push each repository's `main` branch to its corrected `origin`, then confirm local `HEAD` equals `origin/main` while reporting unrelated uncommitted files separately.
