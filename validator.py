from __future__ import annotations

import fitz
from pathlib import Path

Rect = tuple[float, float, float, float]


class Validator:
    """크롭 rect 기준으로 콘텐츠가 잘리는 페이지를 탐색한다."""

    def __init__(self, pdf_path: Path) -> None:
        self._pdf_path = pdf_path

    def find_clipped_pages(
        self, crop_rects: dict[int, Rect | None]
    ) -> list[int]:
        """각 페이지의 크롭 rect 밖으로 콘텐츠가 있는 페이지 번호 목록을 반환한다.

        crop_rects에 없거나 None인 페이지는 검사를 건너뛴다.
        """
        clipped: list[int] = []
        with fitz.open(str(self._pdf_path)) as doc:
            for page_number, rect in crop_rects.items():
                if rect is None:
                    continue
                page = doc[page_number - 1]
                crop = fitz.Rect(rect)
                if self._is_clipped(page, crop):
                    clipped.append(page_number)
        return sorted(clipped)

    def _is_clipped(self, page: fitz.Page, crop: fitz.Rect) -> bool:
        for block in page.get_text("dict")["blocks"]:
            # type=1 은 이미지 블록 — 배경 이미지가 전체 페이지를 덮을 수 있으므로 텍스트만 검사
            if block.get("type") != 0:
                continue
            bbox = fitz.Rect(block["bbox"])
            if not bbox.is_empty and not crop.contains(bbox):
                return True
        for drawing in page.get_drawings():
            bbox = fitz.Rect(drawing["rect"])
            if not bbox.is_empty and not crop.contains(bbox):
                return True
        return False
