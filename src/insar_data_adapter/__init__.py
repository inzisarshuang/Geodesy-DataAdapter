"""Public interfaces for InSAR product inspection and canonical grid I/O."""

from .canonical import CanonicalGridReader, CanonicalGridWriter, GridMetadata
from .converters import convert_gamma_grid, convert_licsbas_grid, convert_mintpy_grid
from .hdf5 import detect_hdf5_format, inspect_hdf5
from .model import DatasetSummary
from .sources import GammaGeoGridSource, LiCSBASGridSource, MintPyGridSource

__all__ = [
    "CanonicalGridReader",
    "CanonicalGridWriter",
    "DatasetSummary",
    "GammaGeoGridSource",
    "GridMetadata",
    "LiCSBASGridSource",
    "MintPyGridSource",
    "convert_gamma_grid",
    "convert_licsbas_grid",
    "convert_mintpy_grid",
    "detect_hdf5_format",
    "inspect_hdf5",
]
__version__ = "0.5.0"
