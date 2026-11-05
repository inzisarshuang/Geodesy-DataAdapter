# Geodesy-DataAdapter

## 1. Repository Scope / 仓库定位

`Geodesy-DataAdapter` is the data-contract layer between processing repositories and downstream analysis or visualization tools. It reads supported upstream products, validates their metadata and geometry, and converts them into stable canonical grids or point tables.

`Geodesy-DataAdapter` 是处理仓库与下游分析、可视化工具之间的数据契约层。它负责读取受支持的上游产品、检查元数据和几何信息，并转换为稳定的标准栅格或点表。

This repository does not perform InSAR preprocessing, interferometric analysis, or publication plotting. Those responsibilities remain in `Geodesy-Preprocessing`, `Geodesy-Analysis`, and `Geodesy-Visualization`.

本仓库不负责 InSAR 预处理、干涉分析或最终制图；这些职责分别属于 `Geodesy-Preprocessing`、`Geodesy-Analysis` 和 `Geodesy-Visualization`。

## 2. Project Structure / 项目结构

```text
Geodesy-DataAdapter/
├── config_examples/          # Example conversion configurations / 转换配置示例
├── docs/                     # Contracts, architecture, and detailed workflows / 契约、架构与详细流程
├── src/insar_data_adapter/   # Python package / Python 包
├── tests/                    # Automated tests / 自动化测试
└── README.md                 # Repository overview / 仓库总览
```

Detailed documentation:

- [Workflows and API reference](docs/workflows_and_api.md)
- [Architecture](docs/architecture.md)
- [Data schema](docs/data_schema.md)
- [CFG contract](docs/cfg_contract.md)

## 3. Workflow Overview / 流程总览

```text
Upstream product
    -> inspect and validate metadata
    -> select a bounded format reader
    -> normalize coordinates, units, masks, and provenance
    -> write a canonical grid or point table
    -> hand the canonical product to analysis or visualization
```

The repository currently supports bounded adapters for GAMMA, MintPy, LiCSBAS, GeoTIFF, Defsour-style point sources, and documented text point tables. Exact commands, format assumptions, canonical APIs, and export options are maintained in the [workflow and API reference](docs/workflows_and_api.md).

当前仓库为 GAMMA、MintPy、LiCSBAS、GeoTIFF、Defsour 点源和已定义格式的文本点表提供受控适配器。具体命令、格式假设、标准接口和导出方式见[流程与 API 参考](docs/workflows_and_api.md)。

## 4. Dependencies And Installation / 环境与安装

Use the shared `envInSAR` environment for project work:

```bash
conda activate envInSAR
python -m pip install -e /mnt/beegfs/procesados/yiluntan/Geodesy-DataAdapter
```

Core dependencies are declared in `pyproject.toml`. Optional readers may require the Python packages associated with their source format.

项目工作统一使用 `envInSAR`。核心依赖声明在 `pyproject.toml` 中；部分可选读取器还需要相应源格式的 Python 依赖。

## 5. Quick Start / 快速开始

Inspect a source product before conversion:

```bash
insar-adapter inspect --config config_examples/inspect.cfg
insar-adapter validate --config config_examples/inspect.cfg
```

Convert a GAMMA product with an explicit configuration:

```bash
insar-adapter convert-gamma \
  --config config_examples/gamma_to_canonical.cfg
```

Use absolute paths in project CFG files when products are shared across repositories. Keep reusable defaults in the repository examples and project-specific paths in the project-level `config/` tree.

项目 CFG 可以使用绝对路径来连接不同仓库的产品；可复用默认值保留在仓库示例中，项目专用路径放在项目根目录的 `config/` 下。

## 6. Data And Output Behavior / 数据与输出行为

Adapters validate required metadata before writing output. Canonical products record geometry, coordinate reference information, units, nodata or mask rules, and source provenance so that downstream tools do not need to infer source-specific conventions.

适配器会在写出前检查必要元数据。标准产品明确记录几何、坐标参考、单位、无效值或掩膜规则以及来源信息，避免下游工具猜测源格式约定。

For a method-centric project, place normalized data under the selected method root, for example:

```text
<PROJECT>/<METHOD>/
├── CANONICAL/
└── EXPORT/
```

Conversion outputs are intentionally overwriteable: adapters are fast, deterministic transformation steps. Configure the target path explicitly when an existing product must be preserved.

转换结果允许直接覆盖，因为适配过程是快速、确定的数据变换步骤。如需保留已有产品，请在 CFG 中显式指定另一个目标路径。

## 7. Verification And Development / 验证与开发

Run focused repository checks in `envInSAR`:

```bash
conda activate envInSAR
python -m compileall -q src/insar_data_adapter
python -m pytest -q
git diff --check
```

When adding a source format, keep source-specific parsing inside its adapter and add tests for metadata validation, units, masks, coordinates, and provenance.

新增源格式时，应将专用解析逻辑限制在对应适配器中，并为元数据、单位、掩膜、坐标和来源记录补充测试。

## 8. Security / 安全说明

- Review paths and output directories before running a conversion.
- Do not commit credentials, access tokens, private URLs, or project data.
- Treat external product metadata and text tables as untrusted input and validate them before use.

- 运行转换前检查输入路径和输出目录。
- 不要提交凭据、访问令牌、私有地址或项目数据。
- 将外部产品元数据和文本表格视为不可信输入，并在使用前完成校验。

## 9. License Notice / 许可说明

No standalone license file is currently included. Confirm usage and redistribution terms before distributing this repository or derived software.

本仓库当前未包含独立许可证文件；在分发本仓库或衍生软件前，请先确认使用与再分发条款。
