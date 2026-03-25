"""marker-pdf 1.x 를 사용해 PDF 를 페이지별 마크다운으로 변환한다.

설치:
    pip install marker-pdf

크롭 영역 필터링(A안):
    marker 로 전체 PDF 를 변환한 뒤, PyMuPDF 로 크롭 영역 밖 텍스트 span 을
    식별해 마크다운에서 해당 줄을 제거한다.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import fitz

log = logging.getLogger("pdf2epub.marker_extractor")

Rect = tuple[float, float, float, float]

_PAGE_SEP = "-" * 48   # marker MarkdownRenderer 기본 page_separator

# 모델은 프로세스당 한 번만 로드 (느린 초기화)
_models: dict | None = None


def load_models() -> dict:
    """marker surya 모델을 로드한다. 최초 호출 시 다운로드가 발생할 수 있다."""
    global _models
    if _models is not None:
        return _models
    log.info("marker 모델 로딩 중 (최초 실행 시 다운로드 발생)...")
    from marker.models import create_model_dict  # type: ignore[import]
    _models = create_model_dict()
    log.info("marker 모델 로딩 완료")
    return _models


def extract_pages_markdown(
    pdf_path: Path,
    models: dict,
    crop_rects: dict[int, Rect | None] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """PDF 를 marker 로 변환하고 (페이지별 마크다운 목록, 이미지 딕셔너리)를 반환한다.

    crop_rects 가 주어지면, 크롭 영역 밖 텍스트를 마크다운에서 제거한다.
    """
    log.info("marker 변환 시작: %s", pdf_path)

    full_markdown, images = _run_marker(pdf_path, models)
    pages = _split_into_pages(full_markdown)

    log.info("marker 변환 완료: %d 페이지 분리됨, %d 이미지 추출됨", len(pages), len(images))

    if crop_rects:
        pages = _filter_by_crop(pdf_path, pages, crop_rects)

    return pages, images


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _run_marker(pdf_path: Path, models: dict) -> tuple[str, dict[str, Any]]:
    from marker.config.parser import ConfigParser      # type: ignore[import]
    from marker.converters.pdf import PdfConverter     # type: ignore[import]

    config_parser = ConfigParser({"output_format": "markdown", "paginate_output": True})
    converter = PdfConverter(
        config=config_parser.generate_config_dict(),
        artifact_dict=models,
        processor_list=config_parser.get_processors(),
        renderer=config_parser.get_renderer(),
    )
    rendered = converter(str(pdf_path))
    return rendered.markdown, rendered.images


def _split_into_pages(full_text: str) -> list[str]:
    """marker 의 page_separator 기준으로 페이지를 분리한다."""
    # paginate_output=True 이면 "-" * 48 구분자가 삽입됨
    sep = re.escape(_PAGE_SEP)
    parts = re.split(rf"\n*{sep}\n*", full_text)
    result = [p.strip() for p in parts if p.strip()]
    return result if result else [full_text.strip()]


def _filter_by_crop(
    pdf_path: Path,
    pages: list[str],
    crop_rects: dict[int, Rect | None],
) -> list[str]:
    """크롭 영역 밖 텍스트 span 을 각 페이지 마크다운에서 제거한다."""
    filtered: list[str] = []

    with fitz.open(str(pdf_path)) as doc:
        for i, md_text in enumerate(pages):
            page_number = i + 1
            rect = crop_rects.get(page_number)
            if rect is None or page_number > len(doc):
                filtered.append(md_text)
                continue

            crop = fitz.Rect(rect)
            outside_texts: set[str] = set()
            page = doc[page_number - 1]
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        bbox = fitz.Rect(span["bbox"])
                        if not bbox.is_empty and not crop.contains(bbox):
                            t = span["text"].strip()
                            if t:
                                outside_texts.add(t)

            if not outside_texts:
                filtered.append(md_text)
                continue

            kept: list[str] = []
            for line in md_text.splitlines():
                clean = line.strip()
                if any(ot in clean for ot in outside_texts):
                    log.debug("크롭 밖 제거 (p%d): %.60s", page_number, clean)
                    continue
                kept.append(line)

            filtered.append("\n".join(kept).strip())
            log.info("p%d: %d 개 outside span 기준 필터링 완료",
                     page_number, len(outside_texts))

    return filtered
