"""Public interfaces for read-only InSAR product inspection."""

from .hdf5 import detect_hdf5_format, inspect_hdf5
from .model import DatasetSummary

__all__ = ["DatasetSummary", "detect_hdf5_format", "inspect_hdf5"]
__version__ = "0.1.0"
