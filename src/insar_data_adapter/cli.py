"""
cli
===

功能概述:
    提供 cfg 驱动的只读 inspect 和 validate 命令；不执行格式转换或文件写入。

函数说明:
    ``build_parser``:
        构建第一阶段命令行界面。
    ``main``:
        加载 cfg、检查 HDF5，并输出 JSON 摘要或校验结果。
"""

from __future__ import annotations

import argparse
import json

from .config import load_inspect_config
from .hdf5 import inspect_hdf5


def build_parser() -> argparse.ArgumentParser:
    """Build the Phase 1 read-only command-line interface."""
    parser = argparse.ArgumentParser(prog="insar-adapter")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "validate"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--config", required=True)
    return parser


def main() -> None:
    """Inspect or validate one configured HDF5 input without modifying it."""
    arguments = build_parser().parse_args()
    config = load_inspect_config(arguments.config)
    summary = inspect_hdf5(
        config["input_file"],
        expected_format=str(config["input_type"]),
        require_unit=bool(config["require_unit"]),
    )
    if arguments.command == "inspect":
        print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(
            f"VALID: {summary.source_format} {summary.layout} "
            f"{summary.deformation_shape} ({len(summary.dates)} epochs)"
        )
