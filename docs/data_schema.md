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

`epoch_id` and `point_id` are unique identities. Dates may repeat only when distinct acquisitions are intentionally preserved. `row` and `column` allow lossless reconstruction of a source grid without interpolation.

`epoch_id` 和 `point_id` 是唯一标识。只有确实保留不同观测时日期才允许重复；`row` 和 `column` 用于无插值恢复源栅格。

## 4. Non-Negotiable Conventions / 强制约定

- X is longitude/easting and Y is latitude/northing.<br>X 为经度或东向坐标，Y 为纬度或北向坐标。
- Elevation defaults to metres only when explicitly recorded as metres.<br>只有明确记录为米时，高程才按米解释。
- Unit scaling occurs exactly once at a named output boundary.<br>单位缩放只允许在明确的输出边界执行一次。
- Zero and nodata remain distinct.<br>零值与 nodata 始终区分。
- A temporal reference never substitutes for a spatial reference.<br>时间参考不能替代空间参考。
