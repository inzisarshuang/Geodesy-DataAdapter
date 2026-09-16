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

Consumers read the one-dimensional axes through
`CanonicalGridReader.read_axis("x" | "y")` and the registration through the
read-only `grid_registration` property. The read-only `metadata` property returns
the complete validated `GridMetadata`, including units, quantity, LOS sign,
nodata policy, temporal/spatial references, and provenance. These interfaces
require an active reader context; consumers must not access the private HDF5
handle.

消费端通过 `CanonicalGridReader.read_axis("x" | "y")` 读取一维坐标轴，并通过
只读 `grid_registration` 属性读取注册方式。只读 `metadata` 属性返回完整且经过
校验的 `GridMetadata`，包括单位、形变量类型、LOS 正号、nodata 规则、时空参考和
来源信息。这些接口都要求 reader 处于活动上下文；消费端不得访问私有 HDF5 handle。

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

## 5. Defsour Point-Table Source Boundary / Defsour 点表来源边界

`DefsourPointSource` is the formal read-only boundary for headerless Defsour
snapshots. The default zero-based columns are X=0, Y=1, elevation=2, and
deformation=3; alternative distinct column assignments must be explicit. Blank
lines and lines beginning with `#` are ignored. Coordinates must be finite,
while elevation and deformation may retain NaN according to the declared nodata
policy. Blocks contain at most `chunk_points` rows and are emitted before later
rows are scanned.

`DefsourPointSource` 是无文件头 Defsour 快照的正式只读边界。默认零基列为
X=0、Y=1、高程=2、形变=3；不同且不重复的其他列配置必须显式声明。空行和以
`#` 开头的行会被忽略。坐标必须为有限值，高程与形变可根据显式 nodata 规则
保留 NaN。每个点块不超过 `chunk_points` 行，并会在扫描后续行之前返回。

`DefsourMetadata` makes the input CRS, deformation and height units, deformation
quantity, LOS sign, nodata policy, temporal/spatial references, and provenance
mandatory. `iter_blocks(target_crs=...)` performs one explicit `always_xy`
coordinate transformation. The source never scales deformation and never grids
or interpolates points; those are named output/rendering boundaries.

`DefsourMetadata` 强制声明输入 CRS、形变与高程单位、形变量类型、LOS 正号、
nodata 规则、时空参考和来源。`iter_blocks(target_crs=...)` 只在明确指定时执行
一次 `always_xy` 坐标转换。来源读取器不缩放形变，也不进行点转栅格或插值；
这些操作属于具名的输出或渲染边界。

## 6. Headered Point-Value Source / 带表头点值来源

`HeaderedPointTableSource` reads a whitespace-delimited point snapshot whose
first non-comment row is a unique header. X and Y roles default to `lon` and
`lat`; the value role is either an explicit header name or, for legacy
compatibility, the third header. Role selection always uses names rather than
assuming physical column positions. Comments, extra columns, NaN values, and
bounded iteration are supported; coordinates must remain finite.

`HeaderedPointTableSource` 读取以空白分隔的点快照，首个非注释行必须为字段名
唯一的表头。X/Y 角色默认采用 `lon`/`lat`；数值角色可显式指定字段名，也可为兼容
旧格式选用第三个表头。字段角色始终按名称选择，不假定其物理列位置。接口支持
注释、额外列、NaN 数值及受控分块，但坐标必须保持有限。

The source uses complete `PointValueMetadata`; units and a header name are not treated
as interchangeable. A descriptive header such as `deformation_cm_per_year`
helps humans audit a table, while `PointValueMetadata` remains the machine-validated
contract for unit, quantity, CRS, LOS, nodata, temporal/spatial references, and
provenance. Unlike canonical time-series `PointMetadata`, it requires no height
field and does not restrict the scientific quantity to displacement or velocity.
Explicit `target_crs` conversion uses `always_xy`; value scaling and gridding
remain separate named boundaries.

来源使用完整 `PointValueMetadata`；单位与字段名不能相互替代。类似
`deformation_cm_per_year` 的描述性字段名便于人工审查，而单位、物理量、CRS、
LOS、nodata、时空参考和来源仍由可机器校验的 `PointValueMetadata` 负责。
它不同于标准时序 `PointMetadata`，不要求高程字段，也不把科学量限制为位移或
速度。显式 `target_crs` 转换采用 `always_xy`；数值缩放和制网仍是独立具名边界。

## 7. Defsour Export Boundary / Defsour 导出边界

`write_defsour_blocks` accepts only consecutive `DefsourPointBlock` objects in
one explicitly declared CRS. It preserves block order and writes X, Y, elevation,
and deformation as four headerless columns. It performs no source reading, unit
scaling, coordinate conversion, interpolation, masking, or re-referencing.

`write_defsour_blocks` 只接收同一显式 CRS 下连续的 `DefsourPointBlock`，保持点块
顺序，并将 X、Y、高程和形变写为四列无表头文本。接口不读取来源、不缩放单位、
不转换坐标、不插值、不生成 mask，也不重新参考。

`DefsourExportMetadata` requires CRS, deformation/height units, deformation
quantity, LOS sign, nodata policy, temporal/spatial references, and provenance.
The writer rejects missing metadata, discontinuous blocks, non-finite coordinates,
infinite values, ambiguous replacement, and formats that do not produce exactly
four numeric columns. A failed stream never replaces an existing destination.

`DefsourExportMetadata` 强制声明 CRS、形变/高程单位、形变量、LOS 正号、nodata
规则、时空参考和来源。writer 会拒绝元数据缺失、点块不连续、坐标非有限、数值为
无穷、覆盖语义不明确，以及不能生成恰好四个数值列的格式；流式写出失败时不会
替换已有目标。

`write_defsour_grid` adds only a bounded row-major grid-to-block mapping. The
caller supplies equal-shape X/Y/height/deformation/mask arrays and explicitly
chooses whether selected NaN payloads are retained; all publication guarantees
remain those of `write_defsour_blocks`. A grid with no selected cells atomically
publishes an empty epoch file for compatibility; direct block export still
rejects empty input unless `allow_empty=True` is explicit.

`write_defsour_grid` 只增加受控内存的行主序网格到点块映射。调用方提供
同形的 X/Y/高程/形变/mask 数组，并显式选择是否保留已选中的 NaN 载荷；
发布保证仍完全由 `write_defsour_blocks` 定义。
零选中像元的网格会为了兼容性原子发布空历元文件；直接点块导出仍默认
拒绝空输入，除非显式设置 `allow_empty=True`。

## 8. Grid Aggregation Boundary / 网格聚合边界

`build_defsour_valid_mask` defines the reusable pre-export validity rule. X, Y,
elevation, and deformation must all be finite; configured elevation/deformation
sentinels and false cells in an optional external mask are excluded. No implicit
sentinel exists, so finite zero coordinates, heights, and deformation remain valid.

`build_defsour_valid_mask` 定义可复用的导出前有效性规则。X、Y、高程与形变必须全部
有限；已配置的高程/形变哨兵值以及可选外部掩膜中的 false 像元被排除。接口不设
隐式哨兵值，因此有限的零坐标、零高程和零形变仍为有效值。

`aggregate_grid_array` accepts one numeric 2-D array and one equal-shape explicit
validity mask. It aggregates complete non-overlapping square windows by `mean`
or `median`, drops incomplete bottom/right edges, emits float64 NaN for windows
with no valid cells, and processes at most `block_output_rows` output rows per
temporary block. Values marked invalid never participate, even when finite.

`aggregate_grid_array` 接收一个数值二维数组和一个同形显式有效掩膜。
它以 `mean` 或 `median` 聚合完整、不重叠的方形窗口，舍弃底部/右侧不完整边缘，
无有效像元的窗口输出 float64 NaN，且每个临时块最多处理
`block_output_rows` 个输出行。标为无效的数值即使有限也绝不参与统计。

`downsample_data_grid` composes two calls to that aggregation contract using one
explicit validity mask for both elevation and deformation. Its output mask is true
only where both aggregated arrays are finite. A factor of one preserves the three
input array objects; coordinate/profile transforms and factor selection are not
part of this API.

`downsample_data_grid` 使用同一个显式有效掩膜分别调用两次上述聚合契约，处理高程
与形变；仅当两个聚合数组均为有限值时，输出掩膜才为 true。倍数为一时保留三个输入
数组对象；坐标/profile 变换与倍数选择不属于该 API。

This numerical boundary does not infer or modify units, CRS, pixel/gridline
registration, coordinates, nodata meaning, or provenance. Callers remain
responsible for recording their selected factor, method, edge policy, and all
scientific metadata at the persistent output boundary.

该数值边界不推断或修改单位、CRS、pixel/gridline 注册、坐标、nodata 语义或来源。
调用方仍必须在持久输出边界记录所选倍数、方法、边缘规则和全部科学元数据。
