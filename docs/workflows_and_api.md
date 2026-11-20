# Geodesy-DataAdapter Workflows And API / 流程与 API 参考

This document is the detailed workflow and API reference for `Geodesy-DataAdapter`. For repository scope, installation, and the shortest supported entry points, begin with the [repository README](../README.md).

本文档是 `Geodesy-DataAdapter` 的详细流程与 API 参考。仓库边界、安装方式和最短入口请先阅读[仓库 README](../README.md)。

## 1. Responsibilities / 职责

- Detect supported HDF5 layouts without loading a deformation cube.<br>识别支持的 HDF5 布局，且不读取完整形变数据立方体。
- Expose one metadata summary for MintPy, LiCSBAS, and canonical products.<br>为 MintPy、LiCSBAS 和标准产品提供统一元数据摘要。
- Validate time dimensions, spatial dimensions, date vectors, units, and source-format expectations.<br>校验时间维、空间维、日期向量、单位和预期源格式。
- Define separate canonical layouts for dense grids and sparse PS/DS points.<br>分别定义规则栅格与稀疏 PS/DS 点的标准布局。
- Parse Defsour snapshots in bounded point blocks with explicit scientific metadata and optional CRS conversion.<br>使用显式科学元数据和可选 CRS 转换，按受控点块解析 Defsour 快照。
- Export validated consecutive point blocks or masked 2-D grids to atomic four-column Defsour text without hidden transformations.<br>将已校验的连续点块或带掩膜二维网格原子导出为四列 Defsour 文本，不执行隐藏转换。
- Aggregate valid cells in complete square grid windows using bounded mean or median blocks.<br>使用受控均值或中位数分块，聚合完整方形窗口内的有效像元。
- Build Defsour grid validity from finite values, explicit sentinels, and an optional external mask without treating zero as nodata.<br>从有限值、显式哨兵值和可选外部掩膜构建 Defsour 网格有效性，不将零视为 nodata。
- Parse named headered point-value snapshots without loading complete tables.<br>按具名表头解析点值快照，且不加载完整数据表。
- Reproject and scale single-band GeoTIFFs with explicit metadata, nodata, resampling, and atomic output.<br>使用显式元数据、nodata、重采样和原子输出重投影及缩放单波段 GeoTIFF。
- Export GAMMA, MintPy, and LiCSBAS grids directly to transactional Defsour snapshots without materializing a time cube.<br>不实例化整个时间立方体，直接将 GAMMA、MintPy 和 LiCSBAS 网格导出为事务式 Defsour 快照。

Source-specific PS/DS ingestion, GRD export, canonical-to-GeoTIFF export, and direct PyGMT rendering remain deferred. GAMMA Defsour export now accepts both regular geocoded grids and explicit radar-grid longitude/latitude rasters.

特定来源的 PS/DS 接入、GRD 导出、标准产品到 GeoTIFF 导出及直接 PyGMT 渲染仍留到后续阶段。GAMMA Defsour 导出已同时支持规则地理编码网格和显式经纬度雷达网格。

Adapter 0.20 exposes strict read-only GAMMA radar primitives for parameter
shapes, explicit real/complex binary rasters, and geographic-lookup sampling.
These APIs adapt source representation only; they do not perform interferometric
analysis or define a complete radar-coordinate converter.

Adapter 0.20 提供严格只读的 GAMMA 雷达源接口，用于参数尺寸、显式实数/复数
二进制栅格及地理 lookup 抽样。这些接口只适配来源表示，不执行干涉分析，也不
构成完整的雷达坐标转换器。

## 2. Installation / 安装

转换输出保持“快速产品可覆盖”的契约：成功校验后原子替换已有目标，任何失败都保留旧文件。
`output_file` 始终优先；省略时可提供 `project_root`、`project` 和 `processing_root`，
默认写入 `<processing_root>/CANONICAL/<output_name>`。显式导出可使用
`AdapterProjectLayout.export(name)` 写入 `<processing_root>/EXPORT/`。Adapter 不拥有
`INTF`、`UNW` 或 `FIGURES` 科学目录。

```bash
python -m pip install -e .
```

## 3. Inspection / 检查

```bash
insar-adapter inspect --config config/data2canonical/inspect_h5.cfg
insar-adapter validate --config config/data2canonical/inspect_h5.cfg
```

Paths in cfg files are resolved relative to the cfg location. JSON output is suitable for logs and future workflow manifests.

cfg 中的路径相对于 cfg 文件解析。JSON 输出可直接用于日志和后续工作流 manifest。

## 4. Documentation / 文档

- [`architecture.md`](architecture.md): component boundaries and phased implementation.<br>组件边界与分阶段实施方案。
- [`data_schema.md`](data_schema.md): canonical grid and point time-series schemas.<br>规则栅格与点时序标准 schema。
- [`cfg_contract.md`](cfg_contract.md): shared cfg behavior and Phase 1 keys.<br>公共 cfg 行为和第一阶段参数。

## 5. MintPy Grid Conversion / MintPy 规则栅格转换

The converter reads `/timeseries` by epoch and row block. It copies deformation values and units unchanged. A DEM, a static validity mask, LOS sign, nodata policy, and height unit must all be explicit; missing geometry is never replaced with a zero DEM.

转换器按时期和行块读取 `/timeseries`，原样保留形变值与单位。DEM、静态有效掩膜、LOS 正负号、nodata 规则及高程单位都必须显式提供；缺失的几何信息绝不会用零 DEM 代替。

```bash
insar-adapter convert-mintpy --config config/data2canonical/mintpy2canonical_h5.cfg
```

## 6. LiCSBAS Grid Conversion / LiCSBAS 规则栅格转换

LiCSBAS cumulative deformation, DEM, mask, pixel-centre coordinates, and spatial reference area are read from one HDF5 file by row block. Because many LiCSBAS files do not declare scientific conventions as HDF5 attributes, deformation/height units, CRS, LOS sign, nodata policy, temporal-reference mode, and pixel registration are mandatory cfg values. Temporal values may either be preserved with an explicit source-reference description or re-referenced by subtracting one configured date.

LiCSBAS 累积形变、DEM、mask、像元中心坐标和空间参考区从同一 HDF5 中按行块读取。由于许多 LiCSBAS 文件没有用 HDF5 属性声明科学约定，cfg 必须填写形变/高程单位、CRS、LOS 正号、nodata 规则、时间参考模式和像元注册方式。时间值既可原样保留并显式说明来源参考，也可通过减去 cfg 指定日期重新参考。

```bash
insar-adapter convert-licsbas --config config/data2canonical/licsbas2canonical_h5.cfg
```

## 7. GAMMA Geocoded Grid Conversion / GAMMA 地理编码规则栅格转换

The first GAMMA adapter accepts a `tab` of headerless deformation files, a separate one-date-per-line manifest, a real DEM, an explicit mask, and a `.par` containing a regular longitude/latitude grid. Every dtype and byte order is explicit. Binary sizes are checked before conversion and data are read through row-sliced `memmap` slices. Radar-coordinate or curvilinear inputs must be geocoded first.

首版 GAMMA adapter 接受无文件头形变文件 `tab`、逐行日期清单、真实 DEM、显式 mask，以及包含规则经纬网格的 `.par`。每种 dtype 与字节序均显式填写；转换前检查所有二进制文件大小，数据通过 `memmap` 行切片读取。雷达坐标或曲线网格输入必须先完成地理编码。

```bash
insar-adapter convert-gamma --config config/data2canonical/gamma2canonical_h5.cfg
```

## 8. Direct Source-to-Defsour / 来源直转 Defsour

Direct Defsour workflows use the source-specific CFGs under
`config/data2defsour/`:

```bash
insar-adapter export-gamma-defsour --config config/data2defsour/gamma2defsour.cfg
insar-adapter export-mintpy-defsour --config config/data2defsour/mintpy2defsour.cfg
insar-adapter export-licsbas-defsour --config config/data2defsour/licsbas2defsour.cfg
insar-adapter export-geotiff-defsour --config config/data2defsour/geotiff2defsour.cfg
```

All four commands select epochs, apply the explicit temporal reference and
scale, compose finite values with the configured mask, downsample/reproject,
and publish `defsour_manifest.json` last. GAMMA also supports reusable aligned
templates; MintPy can additionally publish native epoch, velocity, and DEM
GeoTIFFs. GAMMA requires an explicit source displacement unit, while MintPy
velocity output requires explicit source units and matching HDF5 grid metadata.
No command searches for sibling inputs implicitly.

The GeoTIFF command is source-neutral. Its index contains exactly one scalar
series and exactly two columns per non-comment row:

```text
YYYYMMDDTHHMMSS relative/or/absolute/epoch.tif
```

Relative TIFF paths resolve from the index directory. Units, CRS, scale,
references, DEM, positive static mask, and zero/nodata semantics remain
explicit in CFG; the command never parses a producer-specific combined list.

四个命令均按 CFG 选时期、时间参考与倍率，组合有限值和显式 mask，
再执行降采样/重投影，最后写入 `defsour_manifest.json`。GAMMA 可复用对齐
模板；MintPy 还可导出原分辨率时期、速度和 DEM GeoTIFF。命令不会自动搜索同目录输入。

GeoTIFF 命令与具体来源无关。它的索引只包含一个标量时序，每个非注释行严格为
`YYYYMMDDTHHMMSS TIFF路径` 两列；相对路径从索引目录解析。单位、CRS、倍率、
时空参考、DEM、正值静态掩膜以及零值/nodata 语义都必须在 CFG 中显式填写，
命令不会解析任何生产软件专用的多分量组合列表。

## 9. Canonical Grid API / 标准栅格 API

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

## 10. Canonical PS/DS Point API / 标准 PS/DS 点 API

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

## 11. Defsour Point Source / Defsour 点表来源

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

## 12. Headered Point-Value Source / 带表头点值来源

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

## 13. GeoTIFF Raster Adaptation / GeoTIFF 栅格适配

`convert_geotiff_raster` produces an atomic float32 GeoTIFF while preserving an
explicit record of units, quantity, LOS sign, references, provenance, scale,
and resampling. Inputs without embedded CRS are rejected unless
`source_crs_override` is explicit. The converter never invokes GMT.

`convert_geotiff_raster` 原子生成 float32 GeoTIFF，并明确记录单位、物理量、
LOS、参考、来源、比例和重采样。输入缺少内嵌 CRS 时，必须显式设置
`source_crs_override`，否则拒绝处理。转换器不会调用 GMT。

## 14. Phase and LOS Displacement Units / 相位与 LOS 形变单位

`phase_to_los_displacement` and `los_displacement_to_phase` convert numeric
arrays using an explicitly supplied radar wavelength. The convention is
`displacement = -phase * wavelength / (4*pi)`, so positive displacement is
toward the satellite. Displacement units may be `m`, `cm`, or `mm`; phase is
in radians. Wavelength is never inferred from a filename or sensor label.

`phase_to_los_displacement` 与 `los_displacement_to_phase` 使用调用方显式提供的
雷达波长转换数值数组。符号约定为
`displacement = -phase * wavelength / (4*pi)`，因此正形变表示朝向卫星。
形变单位可选 `m`、`cm` 或 `mm`；相位单位为弧度。波长绝不从文件名或传感器名称推断。

`convert_phase_binary_raster` and `convert_los_displacement_binary_raster` convert
headerless float32 grids in bounded row blocks and atomically publish a new file.
Callers must supply the grid shape and byte order; existing files are not
replaced atomically after successful validation.

`convert_phase_binary_raster` 与 `convert_los_displacement_binary_raster` 按受控行块
转换无文件头 float32 栅格，并原子发布新文件。调用方必须提供网格形状和字节序；
校验成功后会原子替换已有文件。

`convert_phase_geotiff_to_los_displacement` and
`convert_los_displacement_geotiff_to_phase` scale a GeoTIFF without changing its
CRS or grid. They require `GeoTiffValueMetadata` with units matching the chosen
conversion direction and preserve nodata as NaN.

`convert_phase_geotiff_to_los_displacement` 与
`convert_los_displacement_geotiff_to_phase` 对 GeoTIFF 缩放但不改变 CRS 或网格。
它们要求 `GeoTiffValueMetadata` 的单位与转换方向一致，并将 nodata 保留为 NaN。

```python
from insar_data_adapter import (
    phase_to_los_displacement,
    los_displacement_to_phase,
    convert_phase_binary_raster,
    convert_los_displacement_binary_raster,
)

los_mm = phase_to_los_displacement(phase_radians, wavelength_m=0.05546576)
phase_radians = los_displacement_to_phase(los_mm, wavelength_m=0.05546576)
convert_phase_binary_raster(
    "pair.quad.geo.unw",
    "pair.quad.geo.mm",
    shape=(rows, columns),
    wavelength_m=0.05546576,
    byte_order="big",
)
convert_los_displacement_binary_raster(
    "pair.quad.geo.mm",
    "pair.quad.geo.phase",
    shape=(rows, columns),
    wavelength_m=0.05546576,
    input_unit="mm",
    byte_order="big",
)
```

```python
from insar_data_adapter import (
    GeoTiffValueMetadata,
    convert_phase_geotiff_to_los_displacement,
    convert_los_displacement_geotiff_to_phase,
)

metadata = GeoTiffValueMetadata(
    input_unit="rad",
    output_unit="mm",
    value_quantity="cumulative_los_displacement",
    los_positive="toward_satellite",
    nodata_policy="NaN is nodata; zero is valid",
    temporal_reference="source interferogram",
    spatial_reference="source GeoTIFF grid",
    source_provenance="pair.quad.geo.tif",
)
convert_phase_geotiff_to_los_displacement(
    "pair.quad.geo.tif",
    "pair.quad.geo.mm.tif",
    wavelength_m=0.05546576,
    metadata=metadata,
)
phase_metadata = GeoTiffValueMetadata(
    input_unit="mm",
    output_unit="rad",
    value_quantity="unwrapped_phase",
    los_positive="toward_satellite",
    nodata_policy="NaN is nodata; zero is valid",
    temporal_reference="source interferogram",
    spatial_reference="source GeoTIFF grid",
    source_provenance="pair.quad.geo.mm.tif",
)
convert_los_displacement_geotiff_to_phase(
    "pair.quad.geo.mm.tif",
    "pair.quad.geo.phase.tif",
    wavelength_m=0.05546576,
    metadata=phase_metadata,
)
```

对于 GAMMA 无头 float32 栅格，`shape` 必须填写该输入文件真实的行列数；
`byte_order` 必须与文件字节序一致。以上波长仅为调用示例，实际转换请传入该数据
对应的雷达波长。

## 15. Defsour Export / Defsour 导出

`write_defsour_blocks` atomically writes validated, consecutive point blocks as
four-column headerless Defsour text. `write_defsour_grid` applies the same writer
to matching 2-D arrays in bounded row blocks. Complete scientific metadata is
mandatory, and neither API performs hidden source conversion.

`write_defsour_blocks` 将已校验且连续的点块原子写为四列无表头 Defsour 文本；
`write_defsour_grid` 将同一契约按受控行块应用于同形二维数组。两个接口都强制
提供完整科学元数据，不执行任何隐藏的来源转换。

`infer_deformation_unit_label` preserves compatibility labels for explicit
scales from metres (`1` → `m`, `100` → `cm`, and `1000` → `mm`). Other scales
receive an honest `scaled_from_m_by_<factor>` label. It does not scale values or
replace explicit scientific metadata.

`infer_deformation_unit_label` 保留从米缩放时的兼容标签（`1` → `m`、`100` →
`cm`、`1000` → `mm`）。其他倍率使用诚实的 `scaled_from_m_by_<factor>` 标签；
它不缩放数值，也不能代替显式科学元数据。

```python
from insar_data_adapter import DefsourExportMetadata, write_defsour_blocks

metadata = DefsourExportMetadata(
    crs="EPSG:32628",
    deformation_unit="cm",
    deformation_quantity="cumulative_displacement",
    height_unit="m",
    los_positive="toward_satellite",
    nodata_policy="NaN is nodata; zero is valid",
    temporal_reference="20240101",
    spatial_reference="radar row 20 column 30, zero-based",
    source_provenance="validated processing manifest",
)
result = write_defsour_blocks(blocks, "D20240101", metadata)
```

## 16. Grid Aggregation / 网格聚合

`build_defsour_valid_mask` combines finite X/Y/elevation/deformation checks,
optional explicit DEM/deformation sentinels, and an optional external mask.
Finite zero remains valid unless zero is explicitly configured as a sentinel.

`build_defsour_valid_mask` 组合 X/Y/高程/形变有限性检查、可选的显式
DEM/形变哨兵值和可选外部掩膜。除非将零显式设为哨兵值，有限零始终有效。

`aggregate_grid_array` computes `mean` or `median` from explicitly valid cells
in complete `factor × factor` windows. Incomplete bottom/right edges are dropped,
empty windows become NaN, output is float64, and `block_output_rows` bounds
temporary memory. The operation does not alter units, CRS, or registration.

`aggregate_grid_array` 只对完整的 `factor × factor` 窗口中显式有效的像元
计算 `mean` 或 `median`。底部/右侧不完整边缘会被舍弃，空窗口输出 NaN，
输出为 float64，`block_output_rows` 限制临时内存。该操作不改变单位、CRS 或注册方式。

`downsample_data_grid` applies that same explicit validity mask to elevation and
deformation, then marks an output cell valid only when both aggregated values are
finite. A factor of one returns the original arrays without copying. Factor
selection, coordinate generation, CRS changes, and output publication remain
caller responsibilities.

`downsample_data_grid` 对高程和形变使用同一个显式有效掩膜，并且仅在两个聚合值
均为有限数时将输出像元标为有效。倍数为一时直接返回原数组，不产生副本。倍数选择、
坐标生成、CRS 变换和产品发布仍由调用方负责。

## 17. Profile-Aware Raster Reprojection / Profile 驱动的栅格重投影

`reproject_static_grid_to_profile` maps one static numeric grid and its explicit
validity mask between caller-supplied Rasterio profiles. Numeric values use
bilinear resampling, validity uses nearest-neighbour resampling, and output is
float32 with NaN outside the resulting valid area. The API does not infer CRS,
nodata, units, registration, or profiles, and it performs no file I/O.

`reproject_static_grid_to_profile` 根据调用方显式提供的 Rasterio profile，重投影
一个静态数值网格及其有效掩膜。数值采用双线性重采样，有效掩膜采用最近邻重采样；
输出为 float32，结果有效区之外为 NaN。该 API 不推断 CRS、nodata、单位、注册方式
或 profile，也不执行文件 I/O。

`reproject_downsampled_grid_to_profile` applies the same explicit-profile
contract to DEM and deformation grids sharing one validity mask. Both numeric
grids use bilinear resampling, while validity uses nearest-neighbour resampling;
a destination cell is valid only when both numeric results are finite. For the
legacy aligned-grid path, incomplete georeferencing is accepted only when the
source and destination shapes match, and independent copies are returned.

`reproject_downsampled_grid_to_profile` 将同一显式 profile 契约用于共用有效掩膜的
DEM 与形变网格。两个数值网格均采用双线性重采样，有效掩膜采用最近邻重采样；仅当
两个数值结果均有限时目标像元才有效。旧的对齐网格路径允许 profile 缺少地理参考，
但源/目标形状必须一致，并返回三个独立副本。

## 18. Verification / 验证

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
```
