# CFG Contract / CFG 契约

## 1. Common Behavior / 公共行为

- One `snake_case = value` setting is allowed per line.<br>每行只允许一个 `snake_case = value` 参数。
- Blank lines and lines beginning with `#` are ignored.<br>忽略空行和以 `#` 开头的注释行。
- Duplicate and unknown keys are errors.<br>重复键和未知键直接报错。
- Relative paths are resolved from the cfg directory.<br>相对路径按 cfg 所在目录解析。
- Precedence is explicit CLI values, cfg values, then code defaults.<br>优先级为显式 CLI、cfg、代码默认值。

Conversion cfg files retain explicit `output_file` as the highest-priority target.
When it is omitted, `project_root`, `project = SENSOR/CASE`, and
`processing_root = SENSOR/CASE/METHOD` are required; optional `output_name`
selects the filename below `<processing_root>/CANONICAL/`. Successful conversions
atomically replace existing fast products, while failures preserve the old target.

转换 CFG 中显式 `output_file` 的优先级最高。省略时必须同时提供项目根、数据项目和
方法根，输出自动落到 `<processing_root>/CANONICAL/<output_name>`。成功时原子覆盖，
失败时保留旧目标。

## 2. Phase 1 Inspection Keys / 第一阶段检查参数

| Key | Required | Values |
|---|---:|---|
| `input_file` | yes | HDF5 path |
| `input_type` | no | `auto`, `mintpy`, `licsbas`, `standard` |
| `require_unit` | no | `true` or `false`; default `true` |

Example:

```ini
input_file = /path/to/timeseries.h5
input_type = auto
require_unit = true
```

Inspection and conversion use separate strict key sets, so an inspection cfg cannot accidentally trigger a conversion.

检查与转换使用不同的严格参数集合，因此检查 cfg 不会意外触发转换。

## 3. MintPy Grid Conversion Keys / MintPy 规则栅格转换参数

| Key | Required | Meaning / Values |
|---|---:|---|
| `timeseries_file` | yes | MintPy HDF5 with `/timeseries` and `/date` |
| `geometry_file` | yes | HDF5 containing the DEM |
| `mask_file` | yes | HDF5 containing a static non-zero-is-valid mask; may equal `geometry_file` |
| `output_file` | yes | Canonical HDF5 destination |
| `height_dataset` | no | DEM dataset; default `height` |
| `mask_dataset` | no | mask dataset; default `mask` |
| `los_positive` | yes | explicit LOS sign convention |
| `nodata_policy` | yes | explicit free-text zero, NaN, finite nodata, and mask semantics |
| `height_unit` | yes | explicit DEM unit |
| `chunk_rows` | no | positive input row-block ceiling; default `256` |
| `compression` | no | `none`, `gzip`, or `lzf`; default `gzip` |
| `compression_level` | no | integer `0`–`9`; default `4`, used by gzip |

The source must contain geocoded `X_FIRST`, `X_STEP`, `Y_FIRST`, `Y_STEP`, `EPSG`, `REF_DATE`, `REF_X`, and `REF_Y` attributes. `X_FIRST/Y_FIRST` are preserved as pixel-centre coordinates, matching MintPy's convention. Deformation is copied without unit scaling, nodata replacement, re-referencing, reprojection, or resampling. A mask that marks a non-finite DEM cell as valid is rejected instead of being silently changed.

来源必须包含地理编码属性 `X_FIRST`、`X_STEP`、`Y_FIRST`、`Y_STEP`、`EPSG`、`REF_DATE`、`REF_X` 和 `REF_Y`。依照 MintPy 约定，`X_FIRST/Y_FIRST` 原样作为像元中心坐标。形变复制过程中不进行单位缩放、nodata 替换、重新参考、重投影或重采样。若掩膜把非有限 DEM 像元标为有效，程序将报错，而不是静默修改掩膜。

## 4. LiCSBAS Grid Conversion Keys / LiCSBAS 规则栅格转换参数

| Key | Required | Meaning / Values |
|---|---:|---|
| `input_file` | yes | LiCSBAS HDF5 containing deformation, DEM, mask, coordinates, and `refarea` |
| `output_file` | yes | canonical HDF5 destination |
| `deformation_dataset` | no | default `cum` |
| `date_dataset` | no | default `imdates` |
| `height_dataset` | no | default `hgt` |
| `mask_dataset` | no | default `mask` |
| `deformation_unit` | yes | explicit unit; no LiCSBAS default is assumed |
| `height_unit` | yes | explicit DEM unit |
| `crs` | yes | must explicitly be `EPSG:4326` for the native longitude/latitude grid |
| `los_positive` | yes | explicit LOS sign convention |
| `nodata_policy` | yes | explicit mask, NaN, finite nodata, and zero semantics |
| `temporal_reference` | yes | `preserve` or `date` |
| `source_temporal_reference` | conditional | required source-reference description for `preserve` |
| `temporal_reference_date` | conditional | required `YYYYMMDD` in `imdates` for `date` |
| `grid_registration` | yes | must be `pixel` for LiCSBAS corner coordinates |
| `chunk_rows` | no | positive input row-block ceiling; default `256` |
| `compression` | no | `none`, `gzip`, or `lzf`; default `gzip` |
| `compression_level` | no | integer `0`–`9`; default `4`, used by gzip |

Coordinates are preserved without scaling, reprojection, or resampling. In `preserve` mode deformation is copied unchanged; in `date` mode the requested epoch is subtracted from every epoch without unit scaling. Both paths are bounded-memory and record the temporal action in provenance. `refarea` must use `x_start:x_stop/y_start:y_stop` and remain inside the grid. If the HDF5 declares a unit or CRS, it must match cfg. General inspection reports missing LiCSBAS units and CRS as missing instead of assuming millimetres or EPSG:4326; use `require_unit = false` only when inspecting such a source before preparing an explicit conversion cfg.

坐标原样保留，不进行缩放、重投影或重采样。`preserve` 模式原样复制形变；`date` 模式在不缩放单位的前提下让每一期减去指定时期。两条路径均采用受控内存，并在 provenance 中记录时间操作。`refarea` 必须采用 `x_start:x_stop/y_start:y_stop` 格式且位于网格范围内。如果 HDF5 声明了单位或 CRS，它必须与 cfg 一致。通用检查会如实报告 LiCSBAS 缺失的单位和 CRS，而不再默认毫米或 EPSG:4326；仅在编写显式转换 cfg 前检查此类来源时使用 `require_unit = false`。

## 5. GAMMA Geocoded Grid Conversion / GAMMA 地理编码规则栅格转换

| Key | Required | Meaning / Values |
|---|---:|---|
| `tab_file` | yes | first token of each non-comment line is one deformation path |
| `dates_file` | yes | exactly one `YYYYMMDD` per non-comment line, matching tab order |
| `parameter_file` | yes | GAMMA `.par` with regular lon/lat grid fields |
| `height_file` | yes | real-elevation headerless binary on the same grid |
| `mask_file` | yes | headerless static mask; finite values greater than zero are valid |
| `output_file` | yes | canonical HDF5 destination |
| `*_dtype` | yes | explicit deformation, height, and mask NumPy numeric dtype |
| `*_byte_order` | yes | explicit `big`, `little`, or `native` (host byte order) for each binary role |
| `deformation_unit` | yes | explicit source/output deformation unit; values are not scaled |
| `height_unit` | yes | explicit real-elevation unit |
| `crs` | yes | must explicitly be `EPSG:4326` for `corner_lon/corner_lat` |
| `los_positive` | yes | explicit LOS sign convention |
| `nodata_policy` | no | optional source note appended to the generated mask and sentinel description |
| `deformation_nodata` | no | finite sentinel converted to NaN |
| `height_nodata` | no | finite sentinel converted to NaN and marked invalid |
| `spatial_reference` | no | known upstream reference pixel or region, for example `row=120,column=230,zero_based`; defaults to `unknown` |
| `temporal_reference` | yes | `preserve` or `date` |
| `source_temporal_reference` | conditional | required source-reference description for `preserve` |
| `temporal_reference_date` | conditional | required date from `dates_file` for `date` |
| `grid_registration` | yes | must be `pixel` |
| `chunk_rows` | no | positive row-block ceiling; default `256` |
| `compression` | no | `none`, `gzip`, or `lzf`; default `gzip` |
| `compression_level` | no | integer `0`–`9`; default `4` |

Relative paths inside `tab_file` resolve from the tab directory. The adapter rejects duplicate paths/dates, mismatched manifest lengths, wrong byte counts, false grid registration, CRS conflicts, and non-rectilinear parameter files before publishing output. Radar-coordinate data and optional reprojection remain outside Phase 3C.

`tab_file` 内的相对路径以 tab 所在目录解析。发布输出前，adapter 会拒绝重复路径/日期、清单长度不一致、错误字节数、虚假网格注册、CRS 冲突以及非规则网格参数文件。雷达坐标数据与可选重投影不属于第三阶段 C。

The adapter records nodata rules from the mask and any configured sentinel values. A known spatial reference is copied into the HDF5 metadata; omitting it records `unknown`.

程序根据显式掩膜和指定的哨兵值记录 nodata 规则。已知参考像元或区域时可用 `spatial_reference` 记录；省略时写入 `unknown`。

## 6. Canonical Point API and Future CFG / 标准点 API 与后续 CFG

Phase 4A exposes a source-neutral Python API, not a conversion command, because
no PSI_WWQ/PSI_ZDN source contract has yet been selected. Consequently it adds
no cfg keys. Phase 4B will first inspect those source products, document every
unit, sign, reference, nodata, identity, coordinate, and quality-field mapping,
and only then add a strict source-specific cfg and conversion command.

第四阶段 A 只提供与来源无关的 Python API，不提供转换命令，因为尚未确定
PSI_WWQ/PSI_ZDN 的来源契约，所以本阶段不增加 cfg 参数。第四阶段 B 将先检查
这些来源产品，明确记录单位、正负号、参考、nodata、点标识、坐标及质量字段的
每一项映射，再增加严格的来源 cfg 与转换命令。

## 7. Direct Defsour Workflow Keys / 直接 Defsour 工作流参数

The four source workflows require an explicit `output_dir` (or complete
method-root context), epoch selection, source/output CRS, deformation scale and matching
output unit, deformation quantity, height unit, LOS convention, nodata policy,
temporal/spatial reference, provenance, and one downsample mode. Optional
controls include `aggregation` (default `mean`), `chunk_rows` (default 128),
`write_tif` (default `false`), and `overwrite` (default `true`).

四种来源均必须显式填写输出目录（或完整 method-root 上下文）、时期、
源/目标 CRS、倍率与对应输出单位、物理量、高程单位、LOS 符号、nodata、
时空参考、来源及降采样方式。聚合方式、行块大小、是否写出 GeoTIFF 和是否覆盖
均可选，默认分别为 `mean`、128、`false` 和 `true`。

Boolean settings accept `true/yes/1/on` and `false/no/0/off` without case sensitivity. Select `factor`, `target_points`, or `target_pixel_size` and fill the corresponding numeric field. Pixel size uses the original grid axis unit. For GAMMA with explicit longitude and latitude binaries, it uses the output CRS unit after coordinate transformation.

开关可用 `true/yes/1/on` 或 `false/no/0/off`，不区分大小写。从 `factor`、`target_points` 和 `target_pixel_size` 中选一种方式，并填写同名数值项。像元尺寸采用原网格坐标单位。GAMMA 提供逐像元经纬度时，采用变换后的输出 CRS 单位。

- GAMMA additionally requires tab/date/parameter/DEM/mask paths and explicit
  binary dtype/byte order plus `source_unit`. Radar grids add paired
  longitude/latitude rasters with their own dtype/order. `mode = aligned`
  requires an alignment template; irregular native grids cannot write a
  GeoTIFF until aligned to a regular grid.
- MintPy requires explicit time-series, geometry, and mask files plus dataset
  names. Native epoch/velocity/DEM GeoTIFFs are opt-in; `native_only = true`
  requires native epoch GeoTIFF output. Velocity export also requires
  `velocity_source_unit` and matching unit/grid metadata in the velocity HDF5.
- LiCSBAS requires the input HDF5, dataset names including `refarea_dataset`,
  and `source_unit`. A declared source unit/CRS must agree with CFG.
- Indexed GeoTIFF uses `epochs = all` or comma-separated `YYYYMMDDTHHMMSS`
  identifiers in place of `dates`. Give each scalar series a separate two-column
  `index_file` and output directory. Supply `height_file`, `mask_file`,
  `mask_mode = positive` and `source_unit`. Indexed TIFF paths are resolved
  from the index directory, and selected epochs retain index order.<br>
  带索引 GeoTIFF 使用 `epochs = all` 或逗号分隔的完整时间戳代替 `dates`。
  每个标量时序用独立的两列索引和输出目录。填写 DEM、掩膜、`mask_mode = positive`
  和源单位。索引中的 TIFF 相对路径按索引目录解析，选中时期沿用索引顺序。

Relative paths written in the CFG resolve from its directory. The output directory is staged as a
sibling and replaced only after every declared product, README, and manifest
validates. See `config/data2defsour/` for complete bilingual templates.

CFG 中填写的相对路径以 CFG 所在目录为基准。输出先在同级临时目录完整生成和校验，
然后才替换旧目录。完整中英文模板位于 `config/data2defsour/`。
