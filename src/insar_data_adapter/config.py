"""
config
======

功能概述:
    严格解析第一阶段只读检查 cfg，并按 cfg 目录解析输入路径；不负责转换参数。

函数说明:
    ``load_inspect_config``:
        读取并校验 input_file、input_type 和 require_unit。
"""

from __future__ import annotations

from pathlib import Path


_ALLOWED_KEYS = {"input_file", "input_type", "require_unit"}
_INPUT_TYPES = {"auto", "mintpy", "licsbas", "standard"}


def _parse_bool(value: str, key: str) -> bool:
    """Parse one strict human-readable Boolean value."""
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "1", "on"}:
        return True
    if normalized in {"false", "no", "0", "off"}:
        return False
    raise ValueError(f"{key} must be true or false, got {value!r}")


def load_inspect_config(config_file: str | Path) -> dict[str, object]:
    """Load a strict Phase 1 inspection configuration."""
    path = Path(config_file).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"cfg file not found: {path}")
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"expected key = value at {path}:{line_number}")
        key, value = (part.strip() for part in line.split("=", 1))
        if key not in _ALLOWED_KEYS:
            raise ValueError(f"unknown cfg key {key!r} at {path}:{line_number}")
        if key in values:
            raise ValueError(f"duplicate cfg key {key!r} at {path}:{line_number}")
        values[key] = value
    if not values.get("input_file"):
        raise ValueError(f"input_file is required in {path}")
    input_type = values.get("input_type", "auto").lower()
    if input_type not in _INPUT_TYPES:
        raise ValueError(f"input_type must be one of {sorted(_INPUT_TYPES)}")
    input_path = Path(values["input_file"]).expanduser()
    if not input_path.is_absolute():
        input_path = path.parent / input_path
    return {
        "input_file": input_path.resolve(),
        "input_type": input_type,
        "require_unit": _parse_bool(values.get("require_unit", "true"), "require_unit"),
    }
