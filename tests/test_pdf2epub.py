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


def write_ppm(path: Path, width: int, height: int, fill=(255, 255, 255), rect=None):
    pixels = [fill] * (width * height)
    if rect:
        left, top, rect_width, rect_height, color = rect
        for y in range(top, top + rect_height):
            for x in range(left, left + rect_width):
                pixels[y * width + x] = color
    with path.open("wb") as handle:
        handle.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
        for red, green, blue in pixels:
            handle.write(bytes((red, green, blue)))


class Pdf2EpubTests(unittest.TestCase):
    def test_detect_crop_box_from_ppm(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            ppm_path = Path(temp_dir) / "sample.ppm"
            write_ppm(
                ppm_path,
                width=12,
                height=10,
                rect=(3, 2, 4, 3, (0, 0, 0)),
            )

            crop_box = module.detect_crop_box_from_ppm(
                ppm_path,
                white_threshold=245,
                min_content_pixels=1,
                padding=0,
            )

            self.assertEqual((crop_box.left, crop_box.top, crop_box.width, crop_box.height), (3, 2, 4, 3))

    def test_write_fixed_layout_epub(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            image_path = temp_path / "page-0001.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            output_path = temp_path / "book.epub"

            module.write_fixed_layout_epub(
                output_path=output_path,
                title="Sample Book",
                author="Codex",
                language="ko",
                pages=[
                    module.PageAsset(
                        index=1,
                        image_path=image_path,
                        width=600,
                        height=800,
                        spine_title="Page 1",
                    )
                ],
                toc_entries=[module.TocEntry(label="Start", page_index=1)],
            )

            self.assertTrue(output_path.exists())
            with zipfile.ZipFile(output_path) as epub:
                self.assertEqual(epub.read("mimetype"), b"application/epub+zip")
                names = set(epub.namelist())
                self.assertIn("META-INF/container.xml", names)
                self.assertIn("OEBPS/content.opf", names)
                self.assertIn("OEBPS/nav.xhtml", names)
                self.assertIn("OEBPS/toc.ncx", names)
                self.assertIn("OEBPS/pages/page-0001.xhtml", names)
                self.assertIn("OEBPS/images/page-0001.png", names)

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

    def test_find_rendered_page_path_accepts_unpadded_name(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            rendered_path = temp_path / "page-1.ppm"
            rendered_path.write_bytes(b"ppm")

            resolved = module.find_rendered_page_path(temp_path / "page", 1)

            self.assertEqual(resolved, rendered_path)

    def test_detect_crop_box_keeps_sparse_first_text_line(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            ppm_path = Path(temp_dir) / "sample.ppm"
            width = 100
            height = 80
            pixels = [(255, 255, 255)] * (width * height)

            # narrow edge artifact that should not become the left boundary
            for y in range(8, 70):
                for x in range(4, 6):
                    pixels[y * width + x] = (0, 0, 0)

            # sparse first line of real content
            for x in range(24, 36):
                pixels[12 * width + x] = (0, 0, 0)

            # denser body block
            for y in range(18, 55):
                for x in range(22, 82):
                    pixels[y * width + x] = (0, 0, 0)

            with ppm_path.open("wb") as handle:
                handle.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
                for red, green, blue in pixels:
                    handle.write(bytes((red, green, blue)))

            crop_box = module.detect_crop_box_from_ppm(
                ppm_path,
                white_threshold=245,
                padding=0,
            )

            self.assertEqual(crop_box.top, 12)
            self.assertEqual(crop_box.left, 22)

    def test_parse_ghostscript_bboxes(self):
        module = load_module()
        stderr_text = (
            "%%BoundingBox: 10 20 90 180\n"
            "%%HiResBoundingBox: 10.5 20.25 90.75 180.5\n"
            "%%BoundingBox: 5 10 95 190\n"
            "%%HiResBoundingBox: 5.0 10.0 95.0 190.0\n"
        )

        boxes = module.parse_ghostscript_bboxes(stderr_text)

        self.assertEqual(boxes, [(10.5, 20.25, 90.75, 180.5), (5.0, 10.0, 95.0, 190.0)])

    def test_crop_box_from_pdf_bbox(self):
        module = load_module()

        crop_box = module.crop_box_from_pdf_bbox(
            (10.0, 20.0, 90.0, 180.0),
            page_width_points=100.0,
            page_height_points=200.0,
            dpi=72,
            padding=0,
        )

        self.assertEqual((crop_box.left, crop_box.top, crop_box.width, crop_box.height), (10, 20, 80, 160))

    def test_crop_box_from_pdf_bbox_keeps_full_page_for_tiny_marks(self):
        module = load_module()

        crop_box = module.crop_box_from_pdf_bbox(
            (0.0, 0.0, 2.0, 2.0),
            page_width_points=100.0,
            page_height_points=200.0,
            dpi=72,
            padding=0,
        )

        self.assertEqual((crop_box.left, crop_box.top, crop_box.width, crop_box.height), (0, 0, 100, 200))


if __name__ == "__main__":
    unittest.main()
