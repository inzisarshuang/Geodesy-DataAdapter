"""Public interfaces for InSAR product inspection and canonical grid I/O."""

from .canonical import CanonicalGridReader, CanonicalGridWriter, GridMetadata
from .hdf5 import detect_hdf5_format, inspect_hdf5
from .model import DatasetSummary

__all__ = [
    "CanonicalGridReader",
    "CanonicalGridWriter",
    "DatasetSummary",
    "GridMetadata",
    "detect_hdf5_format",
    "inspect_hdf5",
]
__version__ = "0.2.0"
