"""Regression tests for the strict Phase 1 cfg contract."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from insar_data_adapter.config import (
    load_gamma_conversion_config,
    load_inspect_config,
    load_licsbas_conversion_config,
    load_mintpy_conversion_config,
)


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

    def test_inspect_type_and_boolean_choices(self) -> None:
        """Check every documented inspection type and both sets of boolean spellings."""
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "inspect.cfg"
            choices = (
                ("true", True), ("YES", True), ("1", True), ("on", True),
                ("false", False), ("NO", False), ("0", False), ("off", False),
            )
            for input_type in ("auto", "mintpy", "licsbas", "standard"):
                for token, expected in choices:
                    with self.subTest(input_type=input_type, require_unit=token):
                        config.write_text(
                            f"input_file = product.h5\ninput_type = {input_type.upper()}\n"
                            f"require_unit = {token}\n",
                            encoding="utf-8",
                        )
                        loaded = load_inspect_config(config)
                        self.assertEqual(loaded["input_type"], input_type)
                        self.assertIs(loaded["require_unit"], expected)
            for field in ("require_unit", "input_type"):
                with self.subTest(invalid=field):
                    config.write_text(f"input_file = product.h5\n{field} = maybe\n")
                    with self.assertRaisesRegex(ValueError, field):
                        load_inspect_config(config)

    def test_canonical_examples_accept_each_compression_choice(self) -> None:
        """Keep the common compression choices valid in the three canonical examples."""
        examples = Path(__file__).resolve().parents[1] / "config/data2canonical"
        loaders = (
            ("gamma", load_gamma_conversion_config),
            ("licsbas", load_licsbas_conversion_config),
            ("mintpy", load_mintpy_conversion_config),
        )
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "convert.cfg"
            for source, load in loaders:
                text = (examples / f"{source}2canonical_h5.cfg").read_text(encoding="utf-8")
                for choice, expected in (("gzip", "gzip"), ("LZF", "lzf"), ("none", None)):
                    with self.subTest(source=source, compression=choice):
                        config.write_text(text.replace("compression = gzip", f"compression = {choice}"))
                        self.assertEqual(load(config)["compression"], expected)
                with self.subTest(source=source, compression="auto"):
                    config.write_text(text.replace("compression = gzip", "compression = auto"))
                    with self.assertRaisesRegex(ValueError, "compression.*none, gzip, or lzf"):
                        load(config)


if __name__ == "__main__":
    unittest.main()
