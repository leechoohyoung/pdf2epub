# pymupdf 전환 + 페이지별 여백 크롭 설계

**날짜**: 2026-03-24
**목표**: mutool CLI 의존성 제거 및 각 페이지 콘텐츠 영역만 크롭해 여백 최소화

---

## 배경

현재 구현은 `mutool draw`로 PDF 페이지 전체를 PNG로 래스터화한다. 이 방식은 원본 PDF의 여백이 그대로 포함되어 EPUB 출력물에 불필요한 상하좌우 여백이 생긴다. 또한 외부 바이너리(`mutool`) 의존성이 존재한다.

## 목표

- 각 페이지의 실제 콘텐츠 영역(텍스트, 이미지, 드로잉)을 감지해 그 영역만 렌더링
- `mutool` 외부 바이너리 의존성 제거
- 페이지별 독립 크롭 (각 페이지마다 콘텐츠 영역이 다를 수 있음)

## 아키텍처

### 변경 전

```
PDF → mutool draw (전체 페이지) → PNG → EPUB
```

### 변경 후

```
PDF → pymupdf 콘텐츠 bbox 감지 → 크롭 클리핑 렌더링 → PNG → EPUB
```

## 상세 설계

### 콘텐츠 bbox 감지

pymupdf의 `page.get_text("dict")`와 `page.get_drawings()`로 페이지 내 모든 요소의 bbox를 수집하고 union한다.

```python
import fitz

def get_content_bbox(page: fitz.Page) -> fitz.Rect:
    rects = []
    for block in page.get_text("dict")["blocks"]:
        rects.append(fitz.Rect(block["bbox"]))
    for drawing in page.get_drawings():
        rects.append(drawing["rect"])
    if not rects:
        return page.rect
    bbox = rects[0]
    for r in rects[1:]:
        bbox |= r
    return bbox & page.rect  # 페이지 범위 클램핑
```

### 렌더링

```python
def render_page_to_png(pdf_path: Path, page_number: int, dpi: int, output_path: Path) -> tuple[int, int]:
    doc = fitz.open(str(pdf_path))
    page = doc[page_number - 1]  # 0-indexed
    clip = get_content_bbox(page)
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pixmap = page.get_pixmap(matrix=mat, clip=clip)
    pixmap.save(str(output_path))
    return pixmap.width, pixmap.height
```

### 변경되는 코드

| 항목 | 변경 내용 |
|---|---|
| `REQUIRED_COMMANDS` | `("mutool", "pdfinfo")` → `("pdfinfo",)` |
| `render_page_to_png()` | pymupdf 기반으로 교체, bbox 감지+크롭 포함 |
| `read_png_size()` | 제거 (pixmap.width/height로 대체) |
| `import` | `fitz` (pymupdf) 추가, `subprocess`/`shutil` 유지 (pdfinfo용) |

### 변경되지 않는 코드

- `PageAsset` 데이터클래스
- `write_fixed_layout_epub()`
- `build_page_xhtml()`, `build_opf_document()`, `build_nav_document()`
- `parse_pdf_page_count()`, `parse_pdf_metadata()` (pdfinfo 계속 사용)
- `run_command()` (pdfinfo 호출에 계속 사용)
- `require_commands()` (pdfinfo 존재 확인에 계속 사용)
- EPUB 패키징 전체

## 렌더링 상세

`fitz.open()`은 컨텍스트 매니저로 사용해 리소스 누수를 방지한다:

```python
with fitz.open(str(pdf_path)) as doc:
    page = doc[page_number - 1]
    ...
```

`page.get_text("dict")`의 blocks에는 텍스트(`type==0`)와 이미지(`type==1`) 블록이 모두 포함된다. 두 타입 모두 `bbox` 키를 갖고 있으므로 타입 구분 없이 처리한다.

## 엣지 케이스

- **빈 페이지**: 텍스트/드로잉이 없으면 `page.rect` (전체 페이지) 사용
- **bbox 페이지 범위 초과**: `clip & page.rect`로 교차 영역 클램핑
- **래스터 이미지 전용 페이지**: PDF XObject 이미지는 `page.get_text("dict")`와 `page.get_drawings()`에 포함되지 않을 수 있다. 이 경우 `rects`가 비어 `page.rect` (전체 페이지) 반환 — 여백 크롭 없이 전체 렌더링으로 폴백. 이는 의도된 동작이다 (이런 페이지는 이미지 자체가 콘텐츠이므로 크롭 불필요).

## 테스트 처리

현재 `tests/test_pdf2epub.py`에는 이미 제거된 함수들에 대한 테스트가 남아 있어 실행하면 실패하는 상태다:
- `test_detect_crop_box_from_ppm` (×2) — 제거된 PPM 기반 크롭 함수
- `test_find_rendered_page_path_accepts_unpadded_name` — 제거된 함수
- `test_parse_ghostscript_bboxes` — 제거된 Ghostscript 함수
- `test_crop_box_from_pdf_bbox` (×2) — 제거된 함수
- `test_write_fixed_layout_epub` — `TocEntry` 등 제거된 시그니처 전제

삭제 대상 테스트 (모두 삭제):
- `test_detect_crop_box_from_ppm`
- `test_detect_crop_box_keeps_sparse_first_text_line`
- `test_find_rendered_page_path_accepts_unpadded_name`
- `test_parse_ghostscript_bboxes`
- `test_crop_box_from_pdf_bbox`
- `test_crop_box_from_pdf_bbox_keeps_full_page_for_tiny_marks`
- `test_write_fixed_layout_epub` (구버전 — TocEntry 시그니처)

테스트 파일 상단의 `write_ppm()` 헬퍼 함수도 삭제한다 (삭제 대상 테스트들만 사용).

남은 유효한 테스트:
- `test_extract_pdfinfo_value_does_not_capture_next_line` ✓
- `test_configure_logging_writes_to_file` ✓

새로 추가할 테스트:
- `test_write_fixed_layout_epub` — `pdf2epub.py`의 실제 `write_fixed_layout_epub()` 시그니처 기준으로 작성. 현재 구현에는 `toc_entries`/`TocEntry`가 없으므로 해당 인자 없이 호출.

`render_page_to_png()`는 실제 PDF가 필요해 단위 테스트 대상에서 제외한다.

## 의존성

- `pymupdf >= 1.18.0` pip 패키지 추가 (`pip install pymupdf`) — 1.18.0부터 `fitz.open()` 컨텍스트 매니저 지원
- `mutool` 바이너리 의존성 제거
- `pdfinfo` (Poppler) 계속 필요
