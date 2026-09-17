"""Public interfaces for InSAR inspection and canonical grid/point I/O."""

from .canonical import CanonicalGridReader, CanonicalGridWriter, GridMetadata
from .converters import (
    GeoTiffConversionResult,
    GeoTiffValueMetadata,
    convert_gamma_grid,
    convert_geotiff_raster,
    convert_licsbas_grid,
    convert_mintpy_grid,
)
from .exporters import (
    DefsourExportMetadata,
    DefsourExportResult,
    infer_deformation_unit_label,
    write_defsour_blocks,
    write_defsour_grid,
)
from .hdf5 import detect_hdf5_format, inspect_hdf5
from .grid import aggregate_grid_array, build_defsour_valid_mask, downsample_data_grid
from .model import DatasetSummary
from .points import (
    CanonicalPointReader,
    CanonicalPointWriter,
    PointMetadata,
    PointQualitySpec,
)
from .raster import (
    reproject_downsampled_grid_to_profile,
    reproject_static_grid_to_profile,
)
from .sources import (
    DefsourMetadata,
    DefsourPointBlock,
    DefsourPointSource,
    GammaGeoGridSource,
    gamma_par_shape,
    HeaderedPointTableSource,
    LiCSBASGridSource,
    MintPyGridSource,
    PointValueBlock,
    PointValueMetadata,
    radar_indices_from_lookup,
    read_binary_raster,
    read_complex_binary_raster,
    read_gamma_par_value,
)

__all__ = [
    "aggregate_grid_array",
    "build_defsour_valid_mask",
    "downsample_data_grid",
    "CanonicalGridReader",
    "CanonicalGridWriter",
    "CanonicalPointReader",
    "CanonicalPointWriter",
    "DatasetSummary",
    "DefsourMetadata",
    "DefsourExportMetadata",
    "DefsourExportResult",
    "DefsourPointBlock",
    "DefsourPointSource",
    "GammaGeoGridSource",
    "gamma_par_shape",
    "GeoTiffConversionResult",
    "GeoTiffValueMetadata",
    "infer_deformation_unit_label",
    "HeaderedPointTableSource",
    "GridMetadata",
    "LiCSBASGridSource",
    "MintPyGridSource",
    "PointMetadata",
    "PointQualitySpec",
    "PointValueBlock",
    "PointValueMetadata",
    "radar_indices_from_lookup",
    "read_binary_raster",
    "read_complex_binary_raster",
    "read_gamma_par_value",
    "reproject_downsampled_grid_to_profile",
    "reproject_static_grid_to_profile",
    "convert_gamma_grid",
    "convert_geotiff_raster",
    "convert_licsbas_grid",
    "convert_mintpy_grid",
    "detect_hdf5_format",
    "inspect_hdf5",
    "write_defsour_blocks",
    "write_defsour_grid",
]
__version__ = "0.19.0"
