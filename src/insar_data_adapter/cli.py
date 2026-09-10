"""
cli
===

功能概述:
    提供 cfg 驱动的 inspect、validate、MintPy、LiCSBAS 和 GAMMA
    规则栅格转换命令。

函数说明:
    ``build_parser``:
        构建第一阶段命令行界面。
    ``main``:
        加载 cfg、检查 HDF5，并输出 JSON 摘要或校验结果。
"""

from __future__ import annotations

import argparse
import json

from .config import (
    load_gamma_conversion_config,
    load_inspect_config,
    load_licsbas_conversion_config,
    load_mintpy_conversion_config,
)
from .converters import convert_gamma_grid, convert_licsbas_grid, convert_mintpy_grid
from .hdf5 import inspect_hdf5


def build_parser() -> argparse.ArgumentParser:
    """Build inspection and source-to-canonical conversion commands."""
    parser = argparse.ArgumentParser(prog="insar-adapter")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "validate"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--config", required=True)
    convert_mintpy = subparsers.add_parser("convert-mintpy")
    convert_mintpy.add_argument("--config", required=True)
    convert_licsbas = subparsers.add_parser("convert-licsbas")
    convert_licsbas.add_argument("--config", required=True)
    convert_gamma = subparsers.add_parser("convert-gamma")
    convert_gamma.add_argument("--config", required=True)
    return parser


def main() -> None:
    """Run one configured inspection or atomic source conversion."""
    arguments = build_parser().parse_args()
    if arguments.command == "convert-mintpy":
        output = convert_mintpy_grid(load_mintpy_conversion_config(arguments.config))
        print(f"WROTE: {output}")
        return
    if arguments.command == "convert-licsbas":
        output = convert_licsbas_grid(load_licsbas_conversion_config(arguments.config))
        print(f"WROTE: {output}")
        return
    if arguments.command == "convert-gamma":
        output = convert_gamma_grid(load_gamma_conversion_config(arguments.config))
        print(f"WROTE: {output}")
        return
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
