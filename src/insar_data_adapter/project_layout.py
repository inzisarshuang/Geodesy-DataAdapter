"""Safe method-root output paths for Data Adapter products."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_CASE = re.compile(r"[A-Z0-9_]+")
_METHOD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


@dataclass(frozen=True)
class AdapterProjectLayout:
    project_root: Path
    case_root: Path
    processing_root: Path

    @classmethod
    def bind(
        cls,
        project_root: str | Path,
        project: str,
        processing_root: str,
    ) -> "AdapterProjectLayout":
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"project_root must be an existing directory: {root}")
        case_parts = project.split("/")
        if len(case_parts) != 2 or any(
            not part or _CASE.fullmatch(part) is None for part in case_parts
        ):
            raise ValueError("project must be SENSOR/CASE with uppercase components")
        method_parts = processing_root.split("/")
        if (
            len(method_parts) != 3
            or method_parts[:2] != case_parts
            or _METHOD.fullmatch(method_parts[2]) is None
        ):
            raise ValueError(
                "processing_root must be SENSOR/CASE/METHOD below the declared project"
            )
        case = root.joinpath(*case_parts).resolve()
        method = root.joinpath(*method_parts).resolve()
        return cls(root, case, method)

    @staticmethod
    def _filename(name: str) -> str:
        path = Path(name)
        if not name or path.is_absolute() or len(path.parts) != 1 or name in {".", ".."}:
            raise ValueError(f"output filename must be one safe component: {name!r}")
        return name

    def canonical(self, name: str) -> Path:
        return self.processing_root / "CANONICAL" / self._filename(name)

    def export(self, name: str) -> Path:
        return self.processing_root / "EXPORT" / self._filename(name)


__all__ = ["AdapterProjectLayout"]
