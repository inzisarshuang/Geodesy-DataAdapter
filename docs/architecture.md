# Architecture / 架构

## 1. Boundary / 边界

The adapter owns data identification, scientific metadata validation, bounded-memory access, canonical HDF5 writing, and explicit export. It does not perform InSAR inversion, atmospheric correction, phase linking, or figure composition.

Adapter 负责数据识别、科学元数据校验、受控内存访问、标准 HDF5 写入和显式导出；不负责 InSAR 反演、大气改正、相位链接或图件排版。

```text
GAMMA / MintPy / PS-DS-InSAR
              │
              ▼
       source adapters
              │
              ▼
      canonical data API
              │
       ┌──────┼────────┐
       ▼      ▼        ▼
     HDF5   GRD/TIF  Defsour
       │
       ▼
 PyGMT / Matplotlib / analysis
```

## 2. Component Rules / 组件规则

- `model.py` contains format-neutral summaries only.<br>`model.py` 只保存与来源无关的摘要模型。
- `hdf5.py` detects and inspects HDF5 metadata without reading full arrays.<br>`hdf5.py` 识别并检查 HDF5 元数据，不读取完整数组。
- `sources/` modules own read-only MintPy, LiCSBAS, GAMMA, Defsour, headered point-table, and PS/DS access; bounded sources are implemented for the current grid formats and both point-table layouts.<br>`sources/` 模块分别负责只读 MintPy、LiCSBAS、GAMMA、Defsour、带表头点表和 PS/DS 访问；当前规则栅格格式及两种点表布局均已有受控分块来源。
- `canonical.py` owns bounded-memory canonical grid reading and atomic writing; `points.py` provides the equivalent sparse-point contract.<br>`canonical.py` 负责受控内存的标准栅格读取和原子写入；`points.py` 提供对应的稀疏点数据契约。
- `converters/` copies validated sources into the canonical schema; future `exporters/` own exchange formats.<br>`converters/` 将已校验来源复制到标准 schema；后续 `exporters/` 负责交换格式。
- Plotting repositories consume the public API and must not duplicate source-format parsing.<br>绘图仓库只消费公共 API，不再重复解析源格式。

## 3. Phases / 阶段

1. Define contracts and implement read-only HDF5 inspection and validation.<br>定义契约，实现只读 HDF5 检查与校验。
2. Implement canonical grid HDF5 readers/writers with atomic, chunked output (complete).<br>实现标准规则栅格 HDF5 读写和原子分块输出（已完成）。
3. Implement source adapters in bounded subphases: MintPy grid (3A complete), LiCSBAS grid (3B complete), and geocoded GAMMA memmap (3C complete).<br>按受控子阶段实现来源适配：MintPy 规则栅格（3A 已完成）、LiCSBAS 规则栅格（3B 已完成）及地理编码 GAMMA memmap（3C 已完成）。
4. Implement PS/DS support in bounded subphases: canonical point HDF5 I/O (4A complete), then source-specific PSI_WWQ/PSI_ZDN adapters (4B).<br>按受控子阶段实现 PS/DS：标准点 HDF5 读写（4A 已完成），再实现 PSI_WWQ/PSI_ZDN 来源 adapter（4B）。
5. Integrate PyGMT in bounded subphases: expose consumer-safe grid axes and registration (5A complete), then connect and verify `scatter`, `grid`, and `auto` render modes (5B).<br>分阶段接入 PyGMT：先提供消费端安全使用的网格轴与注册方式（5A 已完成），再接入并验证 `scatter`、`grid` 和 `auto` 绘图模式（5B）。
6. Separate legacy source preparation in bounded subphases: formalize Defsour point parsing and CRS conversion in the adapter (6A source contract complete), then let Visualization retain only temporary GMT gridding and verify it against real-data baselines.<br>分阶段拆分旧来源准备逻辑：先在 Adapter 中规范 Defsour 点表解析与 CRS 转换（6A 来源契约已完成），再让 Visualization 仅保留 GMT 临时网格化，并用真实数据基线验收。
7. Formalize named, headered point-value ingestion before replacing Visualization's legacy TXT parsing (6B source contract). Preserve descriptive value headers while keeping scientific metadata independently explicit.<br>在替换 Visualization 的旧 TXT 解析前，先规范具名、带表头的点值读取（6B 来源契约）；保留描述性数值字段名，同时独立显式记录科学元数据。

No phase should require a broad rewrite of an upstream processing repository.

任何阶段都不应要求大范围重写上游处理仓库。
