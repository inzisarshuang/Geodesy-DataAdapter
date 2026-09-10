# InSAR-Data-Adapter

InSAR-Data-Adapter is the data-contract layer between scientific processing systems such as GAMMA, MintPy, LiCSBAS, and future PS/DS-InSAR workflows and consumers such as PyGMT-Plotter. Phase 1 provides read-only source inspection, Phase 2 adds bounded-memory canonical grid HDF5 I/O, Phases 3A–3C add strict MintPy, LiCSBAS, and geocoded GAMMA grid conversion, and Phase 4A adds source-neutral PS/DS point HDF5 I/O.

InSAR-Data-Adapter 是 GAMMA、MintPy、LiCSBAS、后续 PS/DS-InSAR 等科学处理系统与 PyGMT-Plotter 等消费端之间的数据契约层。第一阶段提供来源只读检查，第二阶段增加受控内存的标准规则栅格 HDF5 读写，第三阶段 A–C 增加严格的 MintPy、LiCSBAS 与地理编码 GAMMA 规则栅格转换，第四阶段 A 增加与来源无关的 PS/DS 点 HDF5 读写。

## 1. Responsibilities / 职责

- Detect supported HDF5 layouts without loading a deformation cube.<br>识别支持的 HDF5 布局，且不读取完整形变数据立方体。
- Expose one metadata summary for MintPy, LiCSBAS, and canonical products.<br>为 MintPy、LiCSBAS 和标准产品提供统一元数据摘要。
- Validate time dimensions, spatial dimensions, date vectors, units, and source-format expectations.<br>校验时间维、空间维、日期向量、单位和预期源格式。
- Define separate canonical layouts for dense grids and sparse PS/DS points.<br>分别定义规则栅格与稀疏 PS/DS 点的标准布局。

Radar-coordinate GAMMA input, source-specific PS/DS ingestion, Defsour/GRD/GeoTIFF exporters, and PyGMT integration are intentionally deferred to later phases.

雷达坐标 GAMMA 输入、特定来源的 PS/DS 接入、Defsour/GRD/GeoTIFF 导出及 PyGMT 接入明确留到后续阶段。

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

## 5. MintPy Grid Conversion / MintPy 规则栅格转换

The converter reads `/timeseries` by epoch and row block. It copies deformation values and units unchanged. A DEM, a static validity mask, LOS sign, nodata policy, and height unit must all be explicit; missing geometry is never replaced with a zero DEM.

转换器按时期和行块读取 `/timeseries`，原样保留形变值与单位。DEM、静态有效掩膜、LOS 正负号、nodata 规则及高程单位都必须显式提供；缺失的几何信息绝不会用零 DEM 代替。

```bash
insar-adapter convert-mintpy --config config_examples/mintpy_to_canonical.cfg
```

## 6. LiCSBAS Grid Conversion / LiCSBAS 规则栅格转换

LiCSBAS cumulative deformation, DEM, mask, pixel-centre coordinates, and spatial reference area are read from one HDF5 file by row block. Because many LiCSBAS files do not declare scientific conventions as HDF5 attributes, deformation/height units, CRS, LOS sign, nodata policy, temporal-reference mode, and pixel registration are mandatory cfg values. Temporal values may either be preserved with an explicit source-reference description or re-referenced by subtracting one configured date.

LiCSBAS 累积形变、DEM、mask、像元中心坐标和空间参考区从同一 HDF5 中按行块读取。由于许多 LiCSBAS 文件没有用 HDF5 属性声明科学约定，cfg 必须填写形变/高程单位、CRS、LOS 正号、nodata 规则、时间参考模式和像元注册方式。时间值既可原样保留并显式说明来源参考，也可通过减去 cfg 指定日期重新参考。

```bash
insar-adapter convert-licsbas --config config_examples/licsbas_to_canonical.cfg
```

## 7. GAMMA Geocoded Grid Conversion / GAMMA 地理编码规则栅格转换

The first GAMMA adapter accepts a `tab` of headerless deformation files, a separate one-date-per-line manifest, a real DEM, an explicit mask, and a `.par` containing a regular longitude/latitude grid. Every dtype and byte order is explicit. Binary sizes are checked before conversion and data are read through row-sliced `memmap` slices. Radar-coordinate or curvilinear inputs must be geocoded first.

首版 GAMMA adapter 接受无文件头形变文件 `tab`、逐行日期清单、真实 DEM、显式 mask，以及包含规则经纬网格的 `.par`。每种 dtype 与字节序均显式填写；转换前检查所有二进制文件大小，数据通过 `memmap` 行切片读取。雷达坐标或曲线网格输入必须先完成地理编码。

```bash
insar-adapter convert-gamma --config config_examples/gamma_to_canonical.cfg
```

## 8. Canonical Grid API / 标准栅格 API

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

## 9. Canonical PS/DS Point API / 标准 PS/DS 点 API

`CanonicalPointWriter` writes static point fields in sequential point blocks and
each deformation epoch independently in sequential point blocks. Optional
quality datasets must be declared before writing with their dimensions, dtype,
unit, description, and nodata policy. `CanonicalPointReader` always requires an
explicit point range, preventing accidental full reads of very large point sets.

`CanonicalPointWriter` 按连续点块写入静态点字段，并对每个形变时期独立按连续
点块写入。可选质量字段必须在写入前声明其维度、dtype、单位、说明和 nodata
规则。`CanonicalPointReader` 始终要求显式点范围，避免意外读取超大点集。

```python
from insar_data_adapter import (
    CanonicalPointWriter,
    PointMetadata,
    PointQualitySpec,
)

quality = PointQualitySpec(
    name="temporal_coherence",
    temporal=False,
    dtype="float32",
    unit="1",
    description="Temporal coherence per point",
    nodata_policy="NaN is nodata",
)
metadata = PointMetadata(
    source_format="custom_psds",
    deformation_unit="mm",
    deformation_quantity="cumulative_displacement",
    los_positive="toward_satellite",
    crs="EPSG:32628",
    nodata_policy="NaN is nodata; zero is valid",
    temporal_reference="20200101",
    spatial_reference="point_id=10",
    source_provenance="manifest.json",
    height_unit="m",
)

with CanonicalPointWriter(
    "psds_timeseries.h5",
    dates,
    point_count,
    metadata,
    quality_specs=(quality,),
) as writer:
    for start, stop in point_blocks:
        writer.write_points(
            start,
            point_id[start:stop],
            x[start:stop],
            y[start:stop],
            height[start:stop],
            quality={"temporal_coherence": coherence[start:stop]},
        )
    for epoch in range(len(dates)):
        for start, stop in point_blocks:
            writer.write_deformation_points(
                epoch, start, displacement[epoch, start:stop]
            )
```

The complete PSI_WWQ/PSI_ZDN source mapping and cfg are intentionally assigned
to Phase 4B after read-only source inspection.

完整的 PSI_WWQ/PSI_ZDN 来源映射与 cfg 将在只读检查来源后于第四阶段 B 实现。

## 10. Verification / 验证

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
```
