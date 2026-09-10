"""Public interfaces for InSAR product inspection and canonical grid I/O."""

from .canonical import CanonicalGridReader, CanonicalGridWriter, GridMetadata
from .converters import convert_licsbas_grid, convert_mintpy_grid
from .hdf5 import detect_hdf5_format, inspect_hdf5
from .model import DatasetSummary
from .sources import LiCSBASGridSource, MintPyGridSource

__all__ = [
    "CanonicalGridReader",
    "CanonicalGridWriter",
    "DatasetSummary",
    "GridMetadata",
    "LiCSBASGridSource",
    "MintPyGridSource",
    "convert_licsbas_grid",
    "convert_mintpy_grid",
    "detect_hdf5_format",
    "inspect_hdf5",
]
__version__ = "0.4.0"
