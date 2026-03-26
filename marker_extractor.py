"""marker-pdf 1.x 를 사용해 PDF 를 페이지별 마크다운으로 변환한다.

설치:
    pip install marker-pdf
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import fitz
from i18n import _t

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
    log.info("Loading marker models (download may occur on first run)...")
    from marker.models import create_model_dict  # type: ignore[import]
    _models = create_model_dict()
    log.info("Marker models loaded successfully")
    return _models


def extract_pages_markdown(
    pdf_path: Path,
    models: dict,
    crop_rects: dict[int, Rect | None] | None = None,
    progress_callback: Any | None = None,
    debug_mode: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    """Convert PDF to markdown page by page using marker."""
    log.info(_t("log_marker_start", path=pdf_path))

    from marker.config.parser import ConfigParser      # type: ignore[import]
    from marker.converters.pdf import PdfConverter     # type: ignore[import]

    # 모델 설정 및 컨버터 초기화 (루프 밖에서 한 번만)
    config_parser = ConfigParser({"output_format": "markdown", "paginate_output": False})
    converter = PdfConverter(
        config=config_parser.generate_config_dict(),
        artifact_dict=models,
        processor_list=config_parser.get_processors(),
        renderer=config_parser.get_renderer(),
    )

    all_pages_md: list[str] = []
    all_images: dict[str, Any] = {}

    import tempfile
    import os

    # 디버깅 모드일 경우 폴더 생성
    debug_dir = None
    if debug_mode:
        debug_dir = pdf_path.parent / f"{pdf_path.stem}_debug_pages"
        debug_dir.mkdir(parents=True, exist_ok=True)
        log.info("디버깅 모드 활성화 - 중간 파일 저장 경로: %s", debug_dir)

    with fitz.open(str(pdf_path)) as doc:
        total = len(doc)
        for i in range(total):
            page_num = i + 1
            if progress_callback:
                progress_callback(page_num, total)

            # 1. 해당 페이지만 추출하여 임시 PDF 생성
            temp_doc = fitz.open()
            temp_doc.insert_pdf(doc, from_page=i, to_page=i)
            page = temp_doc[0]
            
            # 크롭 영역 정보가 있을 경우 좌표 보정 및 적용
            rect = crop_rects.get(page_num) if crop_rects else None
            if rect:
                # GUI의 상대 좌표를 PDF의 물리적 절대 좌표로 보정 (오프셋 더하기)
                offset_rect = fitz.Rect(rect) + (page.cropbox.x0, page.cropbox.y0, page.cropbox.x0, page.cropbox.y0)
                
                # 디버깅용 가이드 이미지 생성 (영역 보정 확인용)
                if debug_mode and debug_dir:
                    mat = fitz.Matrix(150 / 72, 150 / 72)
                    guide_doc = fitz.open()
                    guide_page = guide_doc.new_page(width=page.rect.width, height=page.rect.height)
                    guide_page.show_pdf_page(guide_page.rect, temp_doc, 0)
                    guide_page.draw_rect(fitz.Rect(rect), color=(1, 0, 0), width=2)
                    guide_pix = guide_page.get_pixmap(matrix=mat)
                    guide_pix.save(str(debug_dir / f"page_{page_num:04d}_guide.png"))
                    guide_doc.close()

                # 실제 변환용 PDF에는 보정된 절대 좌표로 크롭 적용
                page.set_cropbox(offset_rect)
            
            # marker 처리를 위한 임시 파일 저장
            fd, temp_path = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
            try:
                temp_doc.save(temp_path)
                
                # 디버깅 모드일 경우 크롭된 PDF 별도 저장
                if debug_mode and debug_dir:
                    debug_pdf_path = debug_dir / f"page_{page_num:04d}_cropped.pdf"
                    import shutil
                    shutil.copy(temp_path, debug_pdf_path)

                temp_doc.close()

                # 2. marker 실행
                try:
                    log.debug("페이지 %d/%d 변환 중...", page_num, total)
                    rendered = converter(temp_path)
                    
                    # 마크다운 저장
                    md_text = rendered.markdown.strip()
                    all_pages_md.append(md_text)
                    
                    # 이미지 수집
                    for img_key, img_data in rendered.images.items():
                        safe_key = f"p{page_num}_{img_key}"
                        all_images[safe_key] = img_data
                        
                        import re
                        pattern = re.escape(img_key)
                        all_pages_md[-1] = re.sub(rf'(!\[.*?\]\()({pattern})(\))', rf'\1{safe_key}\3', all_pages_md[-1])
                        all_pages_md[-1] = re.sub(rf'(<img.*?src=["\'])({pattern})(["\'])', rf'\1{safe_key}\3', all_pages_md[-1])

                except Exception as e:
                    log.error("페이지 %d 변환 실패: %s", page_num, e)
                    all_pages_md.append(f"> [오류] 페이지 {page_num} 변환에 실패했습니다.")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

    log.info("marker 페이지별 변환 완료: %d 페이지, %d 이미지", len(all_pages_md), len(all_images))
    return all_pages_md, all_images

    log.info("marker 페이지별 변환 완료: %d 페이지, %d 이미지", len(all_pages_md), len(all_images))
    return all_pages_md, all_images


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
