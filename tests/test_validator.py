import sys
import tempfile
import unittest
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from validator import Validator

class ValidatorTests(unittest.TestCase):
    def _make_pdf(self, temp_path: Path) -> Path:
        pdf_path = temp_path / "test.pdf"
        with fitz.open() as doc:
            # 페이지 1: 텍스트가 (50, 100) 근처에 있음
            page = doc.new_page(width=400, height=600)
            page.insert_text((50, 100), "Hello inside", fontsize=12)
            # 페이지 2: 텍스트가 (300, 500) → 크롭 밖으로 나감
            page2 = doc.new_page(width=400, height=600)
            page2.insert_text((300, 500), "Outside text", fontsize=12)
            doc.save(str(pdf_path))
        return pdf_path

    def test_no_clipping_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp))
            v = Validator(pdf_path)
            # 전체 페이지를 포함하는 크롭 rect
            clipped = v.find_clipped_pages({1: (0, 0, 400, 600), 2: (0, 0, 400, 600)})
            self.assertEqual(clipped, [])

    def test_detects_clipped_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(Path(tmp))
            v = Validator(pdf_path)
            # 크롭 영역을 좁게 지정해 페이지 2의 텍스트가 잘리도록
            clipped = v.find_clipped_pages({1: (0, 0, 400, 600), 2: (0, 0, 200, 300)})
            self.assertIn(2, clipped)
            self.assertNotIn(1, clipped)
