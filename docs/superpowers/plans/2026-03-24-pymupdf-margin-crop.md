# pymupdf 전환 + 페이지별 여백 크롭 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mutool` CLI 의존성을 제거하고 pymupdf로 전환해 각 페이지의 콘텐츠 영역만 크롭 렌더링하여 EPUB 출력물의 여백을 최소화한다.

**Architecture:** PDF 페이지를 pymupdf(`fitz`)로 열고, `page.get_text("dict")`와 `page.get_drawings()`로 콘텐츠 bbox를 감지한 뒤 해당 영역만 클리핑해 PNG로 렌더링한다. EPUB 패키징 코드는 변경 없음.

**Tech Stack:** Python 3, pymupdf(fitz) >= 1.18.0, pdfinfo(Poppler)

---

## 파일 변경 맵

| 파일 | 변경 유형 | 내용 |
|---|---|---|
| `pdf2epub.py` | 수정 | `fitz` import 추가, `REQUIRED_COMMANDS` 변경, `read_png_size()` 제거, `get_content_bbox()` 추가, `render_page_to_png()` 교체 |
| `tests/test_pdf2epub.py` | 수정 | 구버전 테스트 및 `write_ppm()` 삭제, `test_write_fixed_layout_epub` 재작성, `test_get_content_bbox` 추가 |

---

### Task 1: 구버전 테스트 및 헬퍼 정리

현재 테스트 파일에는 이미 제거된 함수들(`detect_crop_box_from_ppm`, `parse_ghostscript_bboxes` 등)에 대한 테스트가 남아 있어 실행 시 전부 실패한다.

**Files:**
- Modify: `tests/test_pdf2epub.py`

- [ ] **Step 1: 현재 테스트 실행해서 실패 확인**

```bash
python -m pytest tests/test_pdf2epub.py -v
```

Expected: 여러 테스트가 `AttributeError`로 실패

- [ ] **Step 2: 삭제 대상 제거**

`tests/test_pdf2epub.py`에서 다음을 삭제한다:

1. `write_ppm()` 함수 전체 (line 22–32):
   ```python
   def write_ppm(path: Path, width: int, height: int, fill=(255, 255, 255), rect=None):
       ...
   ```

2. 다음 테스트 메서드들 전체 (각 `def test_...` 부터 다음 `def` 직전까지):
   - `test_detect_crop_box_from_ppm` (line 36–54)
   - `test_write_fixed_layout_epub` (line 56–90) — TocEntry 사용하는 구버전
   - `test_find_rendered_page_path_accepts_unpadded_name` (line 114–123)
   - `test_detect_crop_box_keeps_sparse_first_text_line` (line 125–159)
   - `test_parse_ghostscript_bboxes` (line 161–172)
   - `test_crop_box_from_pdf_bbox` (line 174–185)
   - `test_crop_box_from_pdf_bbox_keeps_full_page_for_tiny_marks` (line 187–198)

- [ ] **Step 3: 남은 테스트 실행해서 통과 확인**

```bash
python -m pytest tests/test_pdf2epub.py -v
```

Expected: 다음 2개만 PASS:
- `test_extract_pdfinfo_value_does_not_capture_next_line`
- `test_configure_logging_writes_to_file`

- [ ] **Step 4: 커밋**

```bash
git add tests/test_pdf2epub.py
git commit -m "test: 구버전 PPM/Ghostscript 기반 테스트 및 write_ppm 헬퍼 제거"
```

---

### Task 2: `test_write_fixed_layout_epub` 재작성

현재 시그니처 (`toc_entries` 없음)에 맞는 `write_fixed_layout_epub` 테스트를 작성한다.

**Files:**
- Modify: `tests/test_pdf2epub.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_pdf2epub.py`의 `Pdf2EpubTests` 클래스 끝에 다음 테스트를 추가한다:

```python
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
```

- [ ] **Step 2: 테스트 실행해서 통과 확인**

```bash
python -m pytest tests/test_pdf2epub.py::Pdf2EpubTests::test_write_fixed_layout_epub -v
```

Expected: PASS (현재 코드의 `write_fixed_layout_epub`와 시그니처 일치하므로 바로 통과)

- [ ] **Step 3: 전체 테스트 실행**

```bash
python -m pytest tests/test_pdf2epub.py -v
```

Expected: 3개 PASS

- [ ] **Step 4: 커밋**

```bash
git add tests/test_pdf2epub.py
git commit -m "test: write_fixed_layout_epub 테스트 현재 시그니처에 맞게 재작성"
```

---

### Task 3: pymupdf 설치 및 `get_content_bbox()` TDD

`get_content_bbox()` 함수를 TDD로 작성한다. pymupdf로 인메모리 PDF를 만들어 테스트한다.

**Files:**
- Modify: `tests/test_pdf2epub.py`
- Modify: `pdf2epub.py`

- [ ] **Step 1: pymupdf 설치 확인 및 설치**

```bash
python -c "import fitz; print(fitz.__version__)"
```

설치되어 있지 않으면:

```bash
pip install "pymupdf>=1.18.0"
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_pdf2epub.py` 상단 import 블록에 `fitz` import 추가:

```python
import fitz
```

`Pdf2EpubTests` 클래스 끝에 다음 테스트를 추가한다:

```python
def test_get_content_bbox_returns_text_area(self):
    module = load_module()
    # 인메모리 PDF 생성: 200x300pt 페이지에 텍스트 블록 삽입
    doc = fitz.open()
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
    doc = fitz.open()
    page = doc.new_page(width=200, height=300)

    bbox = module.get_content_bbox(page)

    self.assertEqual(bbox, page.rect)
```

- [ ] **Step 3: 테스트 실행해서 실패 확인**

```bash
python -m pytest tests/test_pdf2epub.py::Pdf2EpubTests::test_get_content_bbox_returns_text_area tests/test_pdf2epub.py::Pdf2EpubTests::test_get_content_bbox_empty_page_returns_full_rect -v
```

Expected: FAIL with `AttributeError: module 'pdf2epub' has no attribute 'get_content_bbox'`

- [ ] **Step 4: `pdf2epub.py`에 `fitz` import 추가**

파일 상단 import 블록(알파벳 순서 유지)에 추가:

```python
import fitz
```

- [ ] **Step 5: `get_content_bbox()` 구현 추가**

`pdf2epub.py`의 `read_png_size()` 함수 바로 아래에 추가:

```python
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
    return bbox & page.rect
```

- [ ] **Step 6: 테스트 실행해서 통과 확인**

```bash
python -m pytest tests/test_pdf2epub.py -v
```

Expected: 5개 모두 PASS

- [ ] **Step 7: 커밋**

```bash
git add pdf2epub.py tests/test_pdf2epub.py
git commit -m "feat: get_content_bbox() 추가 — 페이지 콘텐츠 bbox 감지"
```

---

### Task 4: `render_page_to_png()` pymupdf로 교체 및 정리

`REQUIRED_COMMANDS`에서 `mutool` 제거, `read_png_size()` 삭제, `render_page_to_png()` pymupdf 버전으로 교체한다.

**Files:**
- Modify: `pdf2epub.py`

- [ ] **Step 1: `REQUIRED_COMMANDS` 변경을 검증하는 테스트 작성**

`tests/test_pdf2epub.py`의 `Pdf2EpubTests` 클래스 끝에 추가:

```python
def test_required_commands_does_not_include_mutool(self):
    module = load_module()
    self.assertNotIn("mutool", module.REQUIRED_COMMANDS)
    self.assertIn("pdfinfo", module.REQUIRED_COMMANDS)
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

```bash
python -m pytest tests/test_pdf2epub.py::Pdf2EpubTests::test_required_commands_does_not_include_mutool -v
```

Expected: FAIL (`mutool` is in `REQUIRED_COMMANDS`)

- [ ] **Step 3: `REQUIRED_COMMANDS` 변경**

`pdf2epub.py` line 19:

```python
# 변경 전
REQUIRED_COMMANDS = ("mutool", "pdfinfo")

# 변경 후
REQUIRED_COMMANDS = ("pdfinfo",)
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
python -m pytest tests/test_pdf2epub.py::Pdf2EpubTests::test_required_commands_does_not_include_mutool -v
```

Expected: PASS

- [ ] **Step 5: `read_png_size()` 함수 삭제**

`pdf2epub.py`에서 다음 함수 전체를 삭제한다:

```python
def read_png_size(png_path: Path) -> tuple[int, int]:
    with png_path.open("rb") as f:
        f.seek(16)  # PNG signature(8) + IHDR length(4) + IHDR type(4)
        width = int.from_bytes(f.read(4), "big")
        height = int.from_bytes(f.read(4), "big")
    return width, height
```

- [ ] **Step 6: `render_page_to_png()` pymupdf 버전으로 교체**

기존 함수:

```python
def render_page_to_png(pdf_path: Path, page_number: int, dpi: int, output_path: Path) -> tuple[int, int]:
    run_command([
        "mutool", "draw",
        "-r", str(dpi),
        "-o", str(output_path),
        str(pdf_path),
        str(page_number),
    ])
    return read_png_size(output_path)
```

교체 후:

```python
def render_page_to_png(pdf_path: Path, page_number: int, dpi: int, output_path: Path) -> tuple[int, int]:
    with fitz.open(str(pdf_path)) as doc:
        page = doc[page_number - 1]
        clip = get_content_bbox(page)
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pixmap = page.get_pixmap(matrix=mat, clip=clip)
        pixmap.save(str(output_path))
        return pixmap.width, pixmap.height
```

- [ ] **Step 7: 전체 테스트 실행**

```bash
python -m pytest tests/test_pdf2epub.py -v
```

Expected: 6개 모두 PASS

- [ ] **Step 8: 모듈 구조 최종 확인**

```bash
python -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('pdf2epub', 'pdf2epub.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
assert not hasattr(m, 'read_png_size'), 'read_png_size should be removed'
assert hasattr(m, 'get_content_bbox'), 'get_content_bbox missing'
assert hasattr(m, 'render_page_to_png'), 'render_page_to_png missing'
assert m.REQUIRED_COMMANDS == ('pdfinfo',), f'unexpected: {m.REQUIRED_COMMANDS}'
print('All checks passed')
"
```

Expected: `All checks passed`

- [ ] **Step 9: 커밋**

```bash
git add pdf2epub.py tests/test_pdf2epub.py
git commit -m "feat: mutool 제거, render_page_to_png pymupdf+콘텐츠 크롭 기반으로 교체"
```
