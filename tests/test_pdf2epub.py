import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "pdf2epub.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pdf2epub", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Pdf2EpubTests(unittest.TestCase):
    def test_extract_pdfinfo_value_does_not_capture_next_line(self):
        module = load_module()
        pdfinfo_text = (
            "Title:           \n"
            "Creator:         Adobe InDesign CS3 (5.0)\n"
            "Author:          \n"
        )

        self.assertEqual(module.extract_pdfinfo_value(pdfinfo_text, "Title"), "")
        self.assertEqual(module.extract_pdfinfo_value(pdfinfo_text, "Author"), "")

    def test_configure_logging_writes_to_file(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "run.log"
            logger = module.configure_logging(log_path)
            logger.info("hello log")
            for handler in logger.handlers:
                handler.flush()

            self.assertIn("hello log", log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
