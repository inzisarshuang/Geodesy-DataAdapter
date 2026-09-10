# Canonical HDF5 Schema / 标准 HDF5 Schema

## 1. Shared Root Metadata / 公共根属性

Every canonical file must record the following root attributes.

每个标准文件必须记录以下根属性。

| Attribute | Meaning |
|---|---|
| `insar_schema` | `insar_grid_timeseries/1.0` or `insar_point_timeseries/1.0` |
| `source_format` | Original producer, for example `gamma`, `mintpy`, or `psds` |
| `deformation_unit` | Explicit unit such as `m`, `cm`, or `mm` |
| `height_unit` | Explicit elevation unit, normally `m` |
| `deformation_quantity` | `cumulative_displacement` or `velocity` |
| `los_positive` | Explicit LOS sign description; never inferred |
| `crs` | EPSG, WKT, or another unambiguous CRS representation |
| `nodata_policy` | Meaning of NaN, finite nodata, mask, and zero |
| `temporal_reference` | Preserved, first, or an explicit epoch identifier |
| `spatial_reference` | Reference pixel/point description or `none` |
| `source_provenance` | Source paths or a manifest reference |
| `write_complete` | `true` only after every required block has been written and validated |

## 2. Dense Grid Time Series / 规则栅格时序

Schema identifier: `insar_grid_timeseries/1.0`.

```text
/time/date_yyyymmdd          [time]
/time/epoch_id               [time]
/data/displacement           [time, row, column]
/geometry/x                  [column]
/geometry/y                  [row]
/geometry/height             [row, column]
/geometry/valid_mask         [row, column]
/geometry/longitude          [row, column] optional
/geometry/latitude           [row, column] optional
```

`x` and `y` are pixel-centre coordinates in the root `crs`. The required
`grid_registration` root attribute is `pixel` or `gridline`; Phase 2 writers
use `pixel`. Curvilinear longitude/latitude grids are optional additions and
must occur as a pair.

`x`、`y` 是根属性 `crs` 下的像元中心坐标。必填根属性
`grid_registration` 可为 `pixel` 或 `gridline`；第二阶段写入器使用
`pixel`。曲线网格的经纬度二维数组为可选项，且必须成对出现。

The displacement dataset must be chunked. Phase 2 writes one epoch per chunk
and limits the row count so a float32 chunk remains near 1 MiB even when the
configured row ceiling is larger.

形变数据集必须分块。第二阶段每块包含一个时期，并限制行数，使 float32
块即使在配置上限较大时也维持在约 1 MiB。

The Phase 3A MintPy converter preserves `X_FIRST/Y_FIRST` as the first pixel
centres, copies deformation values in the source unit, and requires explicit
DEM and static-mask inputs. It records MintPy `REF_DATE`, `REF_Y`, and `REF_X`
without re-referencing the data.

第三阶段 A 的 MintPy 转换器将 `X_FIRST/Y_FIRST` 保留为首个像元中心，按来源
单位原样复制形变，并要求显式 DEM 与静态掩膜输入。程序记录 MintPy 的
`REF_DATE`、`REF_Y` 和 `REF_X`，但不重新参考数据。

The Phase 3B LiCSBAS converter preserves `corner_lon/corner_lat` as first pixel
centres and copies `/cum`, `/hgt`, and the finite-positive interpretation of
`/mask` by row block. `/refarea` is recorded as the spatial reference. Units,
EPSG:4326, LOS sign, nodata semantics, temporal-reference mode, and pixel
registration must be explicit in cfg because they may be absent from the HDF5.
`preserve` records an explicit source-reference description without changing
`/cum`; `date` subtracts one requested epoch by row block and records that date
as the output reference.

第三阶段 B 的 LiCSBAS 转换器将 `corner_lon/corner_lat` 保留为首像元中心，
按行块复制 `/cum`、`/hgt`，并将 `/mask` 中有限且大于零的值解释为有效。
`/refarea` 记录为空间参考。由于这些信息可能不在 HDF5 中，单位、EPSG:4326、
LOS 正号、nodata 语义、时间参考模式和像元注册方式必须在 cfg 中显式填写。
`preserve` 不改变 `/cum`，并记录显式来源参考说明；`date` 按行块减去指定时期，
并将该日期记录为输出时间参考。

The Phase 3C GAMMA converter accepts only regular geocoded longitude/latitude
grids. It validates every headerless binary size from explicit per-role dtype
and byte order, then reads deformation, DEM, and mask through row-sliced
`memmap`. A configured finite deformation or DEM sentinel is converted to NaN
and recorded. Temporal `preserve` and `date` modes match the LiCSBAS contract.

第三阶段 C 的 GAMMA 转换器仅接受规则地理编码经纬网格。程序根据分别显式填写
的 dtype 和字节序检查每个无文件头二进制文件大小，再通过按行 `memmap` 读取
形变、DEM 与 mask。显式配置的有限形变或 DEM 哨兵值会转换为 NaN 并记录。
时间 `preserve` 与 `date` 模式和 LiCSBAS 契约一致。

## 3. Sparse PS/DS Point Time Series / 稀疏 PS/DS 点时序

Schema identifier: `insar_point_timeseries/1.0`.

```text
/time/date_yyyymmdd          [time]
/time/epoch_id               [time]
/data/displacement           [time, point]
/points/point_id             [point]
/points/x                    [point]
/points/y                    [point]
/points/height               [point]
/points/row                  [point] optional
/points/column               [point] optional
/points/velocity             [point] optional
/quality/*                   [point] or [time, point] optional
```

`point_id` is a non-negative signed-int64 identity stored in globally strictly
increasing order. This ordering permits uniqueness validation by bounded point
blocks instead of loading the entire identity vector. `x`, `y`, and `height`
must be finite numeric values. `row` and `column` are optional non-negative
integer zero-based fields, must occur together, and allow lossless reconstruction
of a source grid without interpolation. `velocity` is optional; when present it
must declare `unit`, `description`, `nodata_policy`, and `dimensions=point`
instead of inheriting the cumulative-displacement unit.

`epoch_id` is a unique integer acquisition identity. Dates use `YYYYMMDD`; a
repeated date is valid only when distinct acquisitions are intentionally retained.

`point_id` 是非负 signed-int64 标识，且必须全局严格递增。借助这一顺序，可以按
受控点块验证唯一性，而不必加载完整标识向量。`x`、`y` 和 `height` 必须是有限
数值。可选的 `row` 与 `column` 必须同时存在且为非负零基整数，用于无插值恢复
源栅格。`velocity` 为可选字段；存在时必须声明 `unit`、`description`、
`nodata_policy` 和 `dimensions=point`，不能直接继承累计形变单位。

`epoch_id` 是唯一的整数观测标识。日期采用 `YYYYMMDD`；只有明确保留不同观测时，
才允许出现重复日期。

Point-scale datasets are chunked. `/data/displacement` and time-varying quality
fields use one epoch per chunk. Writers accept only sequential point blocks for
the static fields and independently sequential blocks for each epoch, so
completion tracking is O(time), not O(time×point). Readers require an explicit,
non-empty half-open point range and never default to reading every point.

点尺度数据集均采用分块存储。`/data/displacement` 与时变质量字段每块只包含一个
时期。静态字段必须按连续点块顺序写入，每个时期也独立按连续点块顺序写入，因而
完成度跟踪只需 O(time)，而非 O(time×point)。读取时必须显式指定非空的左闭右开
点范围，接口不会默认读取全部点。

Every `/quality/*` field is a flat, valid identifier and a real numeric dataset.
Its shape is exactly `[point]` or `[time, point]`, and it must declare non-empty
`unit`, `description`, `nodata_policy`, and `dimensions` attributes. The
`dimensions` value is exactly `point` or `time,point` and must match its shape.

每个 `/quality/*` 都必须使用扁平合法字段名和实数数值 dtype，其形状只能是
`[point]` 或 `[time, point]`。字段必须显式填写非空的 `unit`、`description`、
`nodata_policy` 与 `dimensions` 属性；`dimensions` 只能是与形状对应的 `point`
或 `time,point`。

## 4. Non-Negotiable Conventions / 强制约定

- X is longitude/easting and Y is latitude/northing.<br>X 为经度或东向坐标，Y 为纬度或北向坐标。
- Elevation defaults to metres only when explicitly recorded as metres.<br>只有明确记录为米时，高程才按米解释。
- Unit scaling occurs exactly once at a named output boundary.<br>单位缩放只允许在明确的输出边界执行一次。
- Zero and nodata remain distinct.<br>零值与 nodata 始终区分。
- A temporal reference never substitutes for a spatial reference.<br>时间参考不能替代空间参考。
