# InSAR-Data-Adapter

InSAR-Data-Adapter is the data-contract layer between scientific processing systems such as GAMMA, MintPy, and future PS/DS-InSAR workflows and consumers such as PyGMT-Plotter. Phase 1 provides read-only HDF5 detection, metadata inspection, strict validation, and the canonical schema specification. It does not yet convert or rewrite scientific data.

InSAR-Data-Adapter 是 GAMMA、MintPy、后续 PS/DS-InSAR 等科学处理系统与 PyGMT-Plotter 等消费端之间的数据契约层。第一阶段仅提供 HDF5 格式识别、元数据检查、严格校验和标准 schema 说明，暂不转换或重写科学数据。

## 1. Responsibilities / 职责

- Detect supported HDF5 layouts without loading a deformation cube.<br>识别支持的 HDF5 布局，且不读取完整形变数据立方体。
- Expose one metadata summary for MintPy, LiCSBAS, and canonical products.<br>为 MintPy、LiCSBAS 和标准产品提供统一元数据摘要。
- Validate time dimensions, spatial dimensions, date vectors, units, and source-format expectations.<br>校验时间维、空间维、日期向量、单位和预期源格式。
- Define separate canonical layouts for dense grids and sparse PS/DS points.<br>分别定义规则栅格与稀疏 PS/DS 点的标准布局。

Conversion writers, GAMMA memmap input, Defsour/GRD/GeoTIFF exporters, and PyGMT integration are intentionally deferred to later phases.

转换写入器、GAMMA memmap 输入、Defsour/GRD/GeoTIFF 导出及 PyGMT 接入明确留到后续阶段。

## 2. Installation / 安装

```bash
python -m pip install -e .
```

## 3. Inspection / 检查

```bash
insar-adapter inspect --config config_examples/inspect.cfg
insar-adapter validate --config config_examples/inspect.cfg
```

Paths in cfg files are resolved relative to the cfg location. JSON output is suitable for logs and future workflow manifests.

cfg 中的路径相对于 cfg 文件解析。JSON 输出可直接用于日志和后续工作流 manifest。

## 4. Documentation / 文档

- [`docs/architecture.md`](docs/architecture.md): component boundaries and phased implementation.<br>组件边界与分阶段实施方案。
- [`docs/data_schema.md`](docs/data_schema.md): canonical grid and point time-series schemas.<br>规则栅格与点时序标准 schema。
- [`docs/cfg_contract.md`](docs/cfg_contract.md): shared cfg behavior and Phase 1 keys.<br>公共 cfg 行为和第一阶段参数。

## 5. Verification / 验证

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
```
