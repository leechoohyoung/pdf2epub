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
| `REQUIRED_COMMANDS` | `mutool` 제거, `pdfinfo`만 유지 |
| `render_page_to_png()` | pymupdf 기반으로 교체, bbox 감지+크롭 포함 |
| `read_png_size()` | 제거 (pixmap.width/height로 대체) |
| `import` | `fitz` (pymupdf) 추가, `subprocess` 유지 (pdfinfo용) |

### 변경되지 않는 코드

- `PageAsset` 데이터클래스
- `write_fixed_layout_epub()`
- `build_page_xhtml()`, `build_opf_document()`, `build_nav_document()`
- `parse_pdf_page_count()`, `parse_pdf_metadata()` (pdfinfo 계속 사용)
- EPUB 패키징 전체

## 엣지 케이스

- **빈 페이지**: 텍스트/드로잉이 없으면 `page.rect` (전체 페이지) 사용
- **bbox 페이지 범위 초과**: `& page.rect`로 교차 영역 클램핑

## 의존성

- `pymupdf` pip 패키지 추가 (`pip install pymupdf`)
- `mutool` 바이너리 의존성 제거
- `pdfinfo` (Poppler) 계속 필요
