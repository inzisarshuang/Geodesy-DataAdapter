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

Conversion keys are deferred until the canonical writer exists, so Phase 1 cfg files cannot imply that data have been converted.

转换参数留待标准写入器完成后定义，因此第一阶段 cfg 不会造成“已经完成数据转换”的误解。
