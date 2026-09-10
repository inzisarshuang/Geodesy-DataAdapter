# InSAR-Data-Adapter

InSAR-Data-Adapter is the data-contract layer between scientific processing systems such as GAMMA, MintPy, and future PS/DS-InSAR workflows and consumers such as PyGMT-Plotter. Phase 1 provides read-only source inspection. Phase 2 adds bounded-memory, atomic canonical grid HDF5 reading and writing. Source conversion is not implemented yet.

InSAR-Data-Adapter 是 GAMMA、MintPy、后续 PS/DS-InSAR 等科学处理系统与 PyGMT-Plotter 等消费端之间的数据契约层。第一阶段提供来源只读检查；第二阶段增加受控内存、原子发布的标准规则栅格 HDF5 读写。来源转换尚未实现。

## 1. Responsibilities / 职责

- Detect supported HDF5 layouts without loading a deformation cube.<br>识别支持的 HDF5 布局，且不读取完整形变数据立方体。
- Expose one metadata summary for MintPy, LiCSBAS, and canonical products.<br>为 MintPy、LiCSBAS 和标准产品提供统一元数据摘要。
- Validate time dimensions, spatial dimensions, date vectors, units, and source-format expectations.<br>校验时间维、空间维、日期向量、单位和预期源格式。
- Define separate canonical layouts for dense grids and sparse PS/DS points.<br>分别定义规则栅格与稀疏 PS/DS 点的标准布局。

GAMMA memmap input, MintPy/LiCSBAS conversion, PS/DS point writing, Defsour/GRD/GeoTIFF exporters, and PyGMT integration are intentionally deferred to later phases.

GAMMA memmap 输入、MintPy/LiCSBAS 转换、PS/DS 点写入、Defsour/GRD/GeoTIFF 导出及 PyGMT 接入明确留到后续阶段。

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

## 5. Canonical Grid API / 标准栅格 API

Writers accept complete epochs for moderate grids or full-column row blocks for large grids. Required geometry follows the same row-block pattern. The destination appears only after every epoch row and geometry row has been written and validated.

中等栅格可整期写入，大栅格可按全列连续行块写入；必需几何数据采用相同行块方式。只有全部时期行和几何行写入并校验成功后，目标文件才会出现。

```python
from insar_data_adapter import CanonicalGridWriter, GridMetadata

metadata = GridMetadata(
    source_format="gamma",
    deformation_unit="mm",
    deformation_quantity="cumulative_displacement",
    los_positive="toward_satellite",
    crs="EPSG:32628",
    nodata_policy="NaN is nodata; zero is valid",
    temporal_reference="20200101",
    spatial_reference="row=100,column=200,zero_based",
    source_provenance="manifest.json",
)

with CanonicalGridWriter(
    "timeseries.h5", dates, rows, columns, x, y, metadata
) as writer:
    writer.write_geometry_rows(0, height, valid_mask)
    for epoch_index, displacement in enumerate(epoch_arrays):
        writer.write_epoch(epoch_index, displacement)
```

The example uses complete arrays only for readability. Production source adapters will call `write_deformation_rows` and `write_geometry_rows` repeatedly with bounded row blocks.

示例为便于阅读使用完整数组；正式来源 Adapter 将使用受控行块反复调用 `write_deformation_rows` 和 `write_geometry_rows`。

## 6. Verification / 验证

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
```
