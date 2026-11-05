# Four-Repository README Structure Design

**Date:** 2026-11-05
**Status:** Approved
**Scope:** Geodesy-Preprocessing, Geodesy-Analysis, Geodesy-DataAdapter, and Geodesy-Visualization

## Intent

Give all four repositories the same first-level reading order so a user can move
between pipeline stages without relearning each README. Preserve repository-specific
scientific content and make Geodesy-DataAdapter usable as an entry document instead
of a single long API reference.

## Goals

- Use the same bilingual top-level skeleton in all four README files.
- Keep English immediately followed by Chinese.
- Retain every current DataAdapter command, API example, unit convention, and
  scientific warning.
- Move DataAdapter's detailed conversion and Python API material into one linked
  reference document under `docs/`.
- Keep changes to the other three repositories limited to headings, missing entry
  sections, and links; do not rewrite their scientific workflows.

## Non-goals

- No production code, CFG, CLI, package metadata, or scientific behavior changes.
- No attempt to make repository-specific subsections identical.
- No new license terms; the README only states the current license-file status.

## Approaches

1. **Selected: common entry skeleton plus a DataAdapter reference document.**
   This keeps each README readable while preserving the complete existing adapter
   manual in `docs/workflows_and_api.md`.
2. Keep all DataAdapter API material in README and only add shared headings. This
   minimizes file movement but leaves the core usability problem unresolved.
3. Rewrite all four README files from one strict template. This maximizes visual
   uniformity but creates unnecessary churn and risks losing mature workflow text.

## Common Top-level Skeleton

1. Repository Scope / 仓库定位
2. Project Structure / 项目结构
3. Workflow Overview / 流程总览
4. Dependencies And Installation / 环境与安装
5. Quick Start / 快速开始
6. Data And Output Behavior / 数据与输出行为
7. Verification And Development / 验证与开发
8. Security / 安全说明
9. License Notice / 许可说明

Repositories may add numbered subsections inside this skeleton. Documentation links
belong below Project Structure. Current Scope belongs inside Repository Scope or
Workflow Overview instead of becoming a competing top-level structure.

## DataAdapter Split

The DataAdapter README will explain its boundary in the four-stage pipeline, show
the source-to-canonical-to-export flow, document installation and one minimal CLI
example, summarize canonical paths and overwrite behavior, and link to the schema,
CFG contract, architecture, and detailed reference.

`docs/workflows_and_api.md` will preserve and reorganize the current detailed
material for MintPy, LiCSBAS, GAMMA, canonical grid and point APIs, Defsour,
headered point values, GeoTIFF, phase/LOS units, export, aggregation, reprojection,
and detailed verification commands.

## Verification

- Check every repository-relative Markdown link.
- Confirm the nine top-level sections exist and appear in the same order.
- Search for obsolete local repository names and old GitHub names.
- Run `git diff --check` in all four repositories.
- Commit and push only README/design/reference documentation changes, preserving
  unrelated working-tree edits.
