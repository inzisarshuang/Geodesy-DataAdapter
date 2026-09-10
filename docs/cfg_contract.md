# CFG Contract / CFG 契约

## 1. Common Behavior / 公共行为

- One `snake_case = value` setting is allowed per line.<br>每行只允许一个 `snake_case = value` 参数。
- Blank lines and lines beginning with `#` are ignored.<br>忽略空行和以 `#` 开头的注释行。
- Duplicate and unknown keys are errors.<br>重复键和未知键直接报错。
- Relative paths are resolved from the cfg directory.<br>相对路径按 cfg 所在目录解析。
- Precedence is explicit CLI values, cfg values, then code defaults.<br>优先级为显式 CLI、cfg、代码默认值。

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
| `overwrite` | no | `true` or `false`; default `false` |

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
| `overwrite` | no | `true` or `false`; default `false` |

Coordinates are preserved without scaling, reprojection, or resampling. In `preserve` mode deformation is copied unchanged; in `date` mode the requested epoch is subtracted from every epoch without unit scaling. Both paths are bounded-memory and record the temporal action in provenance. `refarea` must use `x_start:x_stop/y_start:y_stop` and remain inside the grid. If the HDF5 declares a unit or CRS, it must match cfg. General inspection reports missing LiCSBAS units and CRS as missing instead of assuming millimetres or EPSG:4326; use `require_unit = false` only when inspecting such a source before preparing an explicit conversion cfg.

坐标原样保留，不进行缩放、重投影或重采样。`preserve` 模式原样复制形变；`date` 模式在不缩放单位的前提下让每一期减去指定时期。两条路径均采用受控内存，并在 provenance 中记录时间操作。`refarea` 必须采用 `x_start:x_stop/y_start:y_stop` 格式且位于网格范围内。如果 HDF5 声明了单位或 CRS，它必须与 cfg 一致。通用检查会如实报告 LiCSBAS 缺失的单位和 CRS，而不再默认毫米或 EPSG:4326；仅在编写显式转换 cfg 前检查此类来源时使用 `require_unit = false`。
