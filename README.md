# InSAR-Data-Adapter

InSAR-Data-Adapter is the data-contract layer between scientific processing systems such as GAMMA, MintPy, LiCSBAS, and future PS/DS-InSAR workflows and consumers such as PyGMT-Plotter. It provides bounded source readers, canonical grid/point HDF5, strict conversions, safe grid geometry, and explicit Defsour plus headered point-table ingestion.

InSAR-Data-Adapter 是 GAMMA、MintPy、LiCSBAS、后续 PS/DS-InSAR 等科学处理系统与 PyGMT-Plotter 等消费端之间的数据契约层，提供受控来源读取、标准栅格/点 HDF5、严格转换、安全网格几何，以及显式的 Defsour 和带表头点表读取。

## 1. Responsibilities / 职责

- Detect supported HDF5 layouts without loading a deformation cube.<br>识别支持的 HDF5 布局，且不读取完整形变数据立方体。
- Expose one metadata summary for MintPy, LiCSBAS, and canonical products.<br>为 MintPy、LiCSBAS 和标准产品提供统一元数据摘要。
- Validate time dimensions, spatial dimensions, date vectors, units, and source-format expectations.<br>校验时间维、空间维、日期向量、单位和预期源格式。
- Define separate canonical layouts for dense grids and sparse PS/DS points.<br>分别定义规则栅格与稀疏 PS/DS 点的标准布局。
- Parse Defsour snapshots in bounded point blocks with explicit scientific metadata and optional CRS conversion.<br>使用显式科学元数据和可选 CRS 转换，按受控点块解析 Defsour 快照。
- Parse named headered point-value snapshots without loading complete tables.<br>按具名表头解析点值快照，且不加载完整数据表。

Radar-coordinate GAMMA input, source-specific PS/DS ingestion, Defsour/GRD/GeoTIFF exporters, and direct PyGMT rendering are intentionally deferred to later phases.

雷达坐标 GAMMA 输入、特定来源的 PS/DS 接入、Defsour/GRD/GeoTIFF 导出及直接 PyGMT 渲染明确留到后续阶段。

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

Readers expose dates and dimensions through `reader.summary`, complete validated
scientific metadata through `reader.metadata`, X/Y coordinates through
`read_axis`, grid registration through `grid_registration`, and values through
bounded `read_epoch` row slices. These public interfaces are sufficient for a
plotting consumer without exposing the underlying HDF5 handle.

Reader 通过 `reader.summary` 提供日期与维度，通过 `reader.metadata` 提供完整且
经过校验的科学元数据，通过 `read_axis` 提供 X/Y 坐标，通过
`grid_registration` 提供网格注册方式，并通过 `read_epoch` 的受控行切片提供数值。
绘图消费端可完全使用这些公共接口，无需访问底层 HDF5 handle。

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

## 10. Defsour Point Source / Defsour 点表来源

`DefsourPointSource` reads a headerless point snapshot without loading the
complete table. The default columns are X, Y, elevation, and deformation. All
scientific semantics are mandatory in `DefsourMetadata`; optional coordinate
conversion is requested explicitly from `iter_blocks`, and deformation values
are never scaled implicitly.

`DefsourPointSource` 在不载入完整点表的情况下读取无文件头快照。默认列依次为
X、Y、高程和形变。所有科学语义必须通过 `DefsourMetadata` 显式声明；坐标转换
只能由 `iter_blocks` 显式请求，形变值不会被隐式缩放。

```python
from insar_data_adapter import DefsourMetadata, DefsourPointSource

metadata = DefsourMetadata(
    input_crs="EPSG:32605",
    deformation_unit="cm",
    deformation_quantity="cumulative_displacement",
    height_unit="m",
    los_positive="toward_satellite",
    nodata_policy="NaN is nodata; zero is valid",
    temporal_reference="20160512",
    spatial_reference="none",
    source_provenance="LiCSBAS_ASC/D20160512",
)

with DefsourPointSource("D20160512", metadata) as source:
    for block in source.iter_blocks(target_crs="EPSG:4326"):
        consume(block.x, block.y, block.height, block.deformation)
```

## 11. Headered Point-Value Source / 带表头点值来源

`HeaderedPointTableSource` reads named X, Y, and scientific value roles in
bounded blocks. The default role names are `lon` and `lat`; callers should name
the value field explicitly, while omission preserves the existing convention
that the third header is the plotted value. Extra columns are retained in the
source file but are not loaded.

`HeaderedPointTableSource` 按受控分块读取具名 X、Y 和科学数值角色。默认坐标
字段为 `lon` 与 `lat`；调用者应显式填写数值字段名，省略时则兼容现有“第三个
表头为绘图值”约定。来源文件可保留额外字段，但读取器不会加载它们。

```python
from insar_data_adapter import HeaderedPointTableSource, PointValueMetadata

metadata = PointValueMetadata(
    source_format="headered_text_points",
    value_unit="cm/yr",
    value_quantity="velocity",
    los_positive="toward_satellite",
    crs="EPSG:4326",
    nodata_policy="NaN is nodata; zero is valid",
    temporal_reference="velocity interval in source manifest",
    spatial_reference="none",
    source_provenance="points.txt",
)

with HeaderedPointTableSource(
    "points.txt", metadata, value_column="deformation_cm_per_year"
) as source:
    for block in source.iter_blocks():
        consume(block.x, block.y, block.value)
```

## 12. Verification / 验证

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
```
