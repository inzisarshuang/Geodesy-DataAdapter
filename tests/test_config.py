"""Regression tests for the strict Phase 1 cfg contract."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from insar_data_adapter.config import load_inspect_config


class InspectConfigTests(unittest.TestCase):
    """Verify path resolution and strict cfg failures."""

    def test_resolves_relative_input_and_rejects_unknown_keys(self) -> None:
        """Resolve paths from the cfg directory and reject schema drift."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "inspect.cfg"
            config.write_text(
                "input_file = data/product.h5\n"
                "input_type = mintpy\n"
                "require_unit = false\n",
                encoding="utf-8",
            )
            result = load_inspect_config(config)
            self.assertEqual(result["input_file"], (root / "data/product.h5").resolve())
            self.assertFalse(result["require_unit"])
            config.write_text("input_file = product.h5\nunknown = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown cfg key"):
                load_inspect_config(config)


if __name__ == "__main__":
    unittest.main()
