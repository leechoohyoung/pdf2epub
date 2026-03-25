import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import fitz


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
                author="Tester",
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
            )

            self.assertTrue(output_path.exists())
            with zipfile.ZipFile(output_path) as epub:
                self.assertEqual(epub.read("mimetype"), b"application/epub+zip")
                names = set(epub.namelist())
                self.assertIn("META-INF/container.xml", names)
                self.assertIn("OEBPS/content.opf", names)
                self.assertIn("OEBPS/nav.xhtml", names)
                self.assertIn("OEBPS/pages/page-0001.xhtml", names)
                self.assertIn("OEBPS/images/page-0001.png", names)


    def test_get_content_bbox_returns_text_area(self):
        module = load_module()
        # 인메모리 PDF 생성: 200x300pt 페이지에 텍스트 블록 삽입
        with fitz.open() as doc:
            page = doc.new_page(width=200, height=300)
            page.insert_text((50, 100), "Hello", fontsize=12)

            bbox = module.get_content_bbox(page)

        # 텍스트가 있는 영역 안에 결과가 있어야 함
        self.assertGreaterEqual(bbox.x0, 0)
        self.assertGreaterEqual(bbox.y0, 0)
        self.assertLessEqual(bbox.x1, 200)
        self.assertLessEqual(bbox.y1, 300)
        # 전체 페이지보다 작아야 함 (여백 크롭됨)
        self.assertLess(bbox.get_area(), 200 * 300)

    def test_get_content_bbox_empty_page_returns_full_rect(self):
        module = load_module()
        with fitz.open() as doc:
            page = doc.new_page(width=200, height=300)

            bbox = module.get_content_bbox(page)

            self.assertEqual(bbox, page.rect)

    def test_required_commands_does_not_include_mutool(self):
        module = load_module()
        self.assertNotIn("mutool", module.REQUIRED_COMMANDS)
        self.assertIn("pdfinfo", module.REQUIRED_COMMANDS)

    def test_render_page_to_png_respects_explicit_crop_rect(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            pdf_path = temp_path / "test.pdf"
            with fitz.open() as doc:
                page = doc.new_page(width=400, height=600)
                page.insert_text((50, 100), "Hello", fontsize=12)
                page.insert_text((300, 500), "Outside", fontsize=12)
                doc.save(str(pdf_path))

            png_path = temp_path / "out.png"
            # 크롭 영역을 좁게 지정해 "Outside" 텍스트가 잘리도록
            w, h = module.render_page_to_png(
                pdf_path, 1, 72, png_path,
                crop_rect=(0, 0, 200, 300),
            )
            self.assertTrue(png_path.exists())
            # 크롭된 결과이므로 전체 페이지보다 작아야 함
            self.assertLess(w, 400)


if __name__ == "__main__":
    unittest.main()
