"""Focused tests for atomic, explicit GeoTIFF raster adaptation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from insar_data_adapter import GeoTiffValueMetadata, convert_geotiff_raster


class GeoTiffConversionTests(unittest.TestCase):
    """Verify scaling, nodata, metadata, geometry, and atomic failure behavior."""

    def setUp(self) -> None:
        """Create an isolated directory and explicit raster-value metadata."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.metadata = GeoTiffValueMetadata(
            input_unit="m/yr",
            output_unit="cm/yr",
            value_quantity="velocity",
            los_positive="toward_satellite",
            nodata_policy="NaN is nodata; zero is valid",
            temporal_reference="source velocity interval",
            spatial_reference="none",
            source_provenance="synthetic GeoTIFF test",
        )

    def _write_source(self, path: Path, crs: str | None = "EPSG:4326") -> None:
        """Write one small single-band source with an explicit nodata sentinel."""
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype="float32",
            crs=crs,
            transform=from_origin(10.0, 12.0, 1.0, 1.0),
            nodata=-9999.0,
        ) as dst:
            dst.write(np.array([[1.0, 2.0], [3.0, -9999.0]], dtype="float32"), 1)

    def test_scales_and_preserves_nan_with_metadata(self) -> None:
        """Publish float32 values, geometry, tags, and NaN nodata atomically."""
        source = self.root / "source.tif"
        output = self.root / "output.tif"
        self._write_source(source)
        result = convert_geotiff_raster(
            source,
            output,
            self.metadata,
            scale=2.0,
            nan_to_zero=False,
        )
        self.assertEqual(result.region, (10.0, 12.0, 10.0, 12.0))
        self.assertEqual((result.height, result.width), (2, 2))
        with rasterio.open(output) as dataset:
            values = dataset.read(1)
            np.testing.assert_allclose(values[:1], [[2.0, 4.0]])
            self.assertEqual(values[1, 0], 6.0)
            self.assertTrue(np.isnan(values[1, 1]))
            self.assertEqual(dataset.tags()["output_unit"], "cm/yr")
            self.assertEqual(dataset.tags()["scale_factor"], "2.0")

    def test_requires_explicit_source_crs_and_preserves_existing_output(self) -> None:
        """Reject an unreferenced input without replacing an existing target."""
        source = self.root / "unreferenced.tif"
        output = self.root / "existing.tif"
        self._write_source(source, crs=None)
        output.write_bytes(b"original")
        with self.assertRaisesRegex(ValueError, "source_crs_override is required"):
            convert_geotiff_raster(
                source, output, self.metadata, overwrite=True
            )
        self.assertEqual(output.read_bytes(), b"original")
        self.assertEqual(list(self.root.glob(".existing.*.tif")), [])

    def test_explicit_source_override_and_zero_nodata(self) -> None:
        """Allow an explicit source CRS override and intentionally encode nodata as zero."""
        source = self.root / "override.tif"
        output = self.root / "zero.tif"
        self._write_source(source, crs=None)
        result = convert_geotiff_raster(
            source,
            output,
            self.metadata,
            source_crs_override="EPSG:4326",
            nan_to_zero=True,
        )
        self.assertEqual(result.nodata, 0.0)
        with rasterio.open(output) as dataset:
            self.assertEqual(dataset.read(1)[1, 1], 0.0)
            self.assertEqual(dataset.nodata, 0.0)


if __name__ == "__main__":
    unittest.main()
