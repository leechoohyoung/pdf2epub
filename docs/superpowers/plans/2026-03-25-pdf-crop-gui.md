# PDF Crop GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PDF 페이지별 크롭 영역을 드래그로 지정하고 콘텐츠 잘림을 검증한 뒤 EPUB으로 변환하는 tkinter GUI 앱을 구현한다.

**Architecture:** tkinter Canvas 위에 PDF 페이지를 렌더링하고 마우스 드래그로 크롭 직사각형을 그린다. `CropStore`가 페이지별 크롭 rect를 관리하고, `Validator`가 모든 페이지의 콘텐츠 잘림 여부를 검사한다. 기존 `pdf2epub.py`의 `render_page_to_png` 및 `convert_pdf_to_epub`에 선택적 `crop_rect` 파라미터를 추가해 GUI와 CLI 모두 지원한다.

**Tech Stack:** Python 3, tkinter (built-in), PyMuPDF (fitz), 기존 pdf2epub.py

---

## 파일 구조

| 파일 | 역할 |
|------|------|
| `pdf2epub.py` | `render_page_to_png`, `convert_pdf_to_epub`에 `crop_rect` 파라미터 추가 |
| `gui.py` | 메인 GUI 앱 진입점 및 전체 레이아웃 |
| `crop_store.py` | 페이지별 크롭 rect 저장/조회 (`CropStore`) |
| `validator.py` | 크롭 영역 밖으로 콘텐츠가 잘리는 페이지 탐색 (`Validator`) |
| `tests/test_crop_store.py` | CropStore 단위 테스트 |
| `tests/test_validator.py` | Validator 단위 테스트 |

---

## Task 1: pdf2epub.py — crop_rect 파라미터 추가

**Files:**
- Modify: `pdf2epub.py` (`render_page_to_png`, `convert_pdf_to_epub`)
- Modify: `tests/test_pdf2epub.py`

### 목표
GUI에서 지정한 크롭 rect를 변환에 그대로 반영한다.
`crop_rect`가 없으면 기존처럼 `get_content_bbox`를 사용한다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_pdf2epub.py`에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python3 -m unittest tests.test_pdf2epub.Pdf2EpubTests.test_render_page_to_png_respects_explicit_crop_rect -v
```

Expected: FAIL (`unexpected keyword argument 'crop_rect'`)

- [ ] **Step 3: render_page_to_png 수정**

```python
def render_page_to_png(
    pdf_path: Path,
    page_number: int,
    dpi: int,
    output_path: Path,
    *,
    crop_rect: tuple[float, float, float, float] | None = None,
) -> tuple[int, int]:
    with fitz.open(str(pdf_path)) as doc:
        page = doc[page_number - 1]
        if crop_rect is not None:
            clip = fitz.Rect(crop_rect)
        else:
            clip = get_content_bbox(page)
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pixmap = page.get_pixmap(matrix=mat, clip=clip)
        pixmap.save(str(output_path))
        return pixmap.width, pixmap.height
```

- [ ] **Step 4: convert_pdf_to_epub 수정**

시그니처에 `crop_rects` 추가:

```python
def convert_pdf_to_epub(
    input_pdf: Path,
    output_epub: Path,
    *,
    dpi: int = 150,
    language: str = "ko",
    keep_temp: bool = False,
    logger: logging.Logger | None = None,
    crop_rects: dict[int, tuple[float, float, float, float]] | None = None,
) -> None:
```

렌더링 루프 내 `render_page_to_png` 호출부를 수정:

```python
explicit_crop = crop_rects.get(page_number) if crop_rects else None
width, height = render_page_to_png(
    input_pdf, page_number, dpi, png_path,
    crop_rect=explicit_crop,
)
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
python3 -m unittest tests/test_pdf2epub.py -v
```

Expected: 전체 PASS

- [ ] **Step 6: 커밋**

```bash
git add pdf2epub.py tests/test_pdf2epub.py
git commit -m "feat: render_page_to_png/convert_pdf_to_epub에 crop_rect 파라미터 추가"
```

---

## Task 2: CropStore 구현

**Files:**
- Create: `crop_store.py`
- Create: `tests/test_crop_store.py`

### 목표
페이지별 크롭 rect를 저장/조회한다.
페이지별 설정이 없으면 기본값(default)을 반환한다.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_crop_store.py
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crop_store import CropStore

Rect = tuple[float, float, float, float]

class CropStoreTests(unittest.TestCase):
    def test_returns_none_when_no_default_set(self):
        store = CropStore()
        self.assertIsNone(store.get(1))

    def test_returns_default_when_set(self):
        store = CropStore()
        store.set_default((0, 0, 100, 200))
        self.assertEqual(store.get(5), (0, 0, 100, 200))

    def test_per_page_overrides_default(self):
        store = CropStore()
        store.set_default((0, 0, 100, 200))
        store.set(3, (10, 20, 90, 180))
        self.assertEqual(store.get(3), (10, 20, 90, 180))
        self.assertEqual(store.get(4), (0, 0, 100, 200))

    def test_has_override_returns_correct(self):
        store = CropStore()
        store.set(3, (10, 20, 90, 180))
        self.assertTrue(store.has_override(3))
        self.assertFalse(store.has_override(4))

    def test_all_rects_returns_per_page_or_default(self):
        store = CropStore()
        store.set_default((0, 0, 100, 200))
        store.set(2, (5, 5, 95, 195))
        result = store.all_rects(page_count=3)
        self.assertEqual(result[1], (0, 0, 100, 200))
        self.assertEqual(result[2], (5, 5, 95, 195))
        self.assertEqual(result[3], (0, 0, 100, 200))
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python3 -m unittest tests/test_crop_store.py -v
```

Expected: FAIL (`ModuleNotFoundError: No module named 'crop_store'`)

- [ ] **Step 3: CropStore 구현**

```python
# crop_store.py
from __future__ import annotations

Rect = tuple[float, float, float, float]


class CropStore:
    """페이지별 크롭 rect를 관리한다.

    페이지별 설정이 없으면 default를 반환한다.
    default도 없으면 None을 반환한다.
    """

    def __init__(self) -> None:
        self._default: Rect | None = None
        self._overrides: dict[int, Rect] = {}

    def set_default(self, rect: Rect) -> None:
        self._default = rect

    def set(self, page_number: int, rect: Rect) -> None:
        self._overrides[page_number] = rect

    def get(self, page_number: int) -> Rect | None:
        return self._overrides.get(page_number, self._default)

    def has_override(self, page_number: int) -> bool:
        return page_number in self._overrides

    def all_rects(self, page_count: int) -> dict[int, Rect | None]:
        return {p: self.get(p) for p in range(1, page_count + 1)}
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
python3 -m unittest tests/test_crop_store.py -v
```

Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add crop_store.py tests/test_crop_store.py
git commit -m "feat: CropStore — 페이지별 크롭 rect 관리"
```

---

## Task 3: Validator 구현

**Files:**
- Create: `validator.py`
- Create: `tests/test_validator.py`

### 목표
주어진 크롭 rect 기준으로 페이지 콘텐츠(텍스트 블록, 드로잉)가 잘리는 페이지 번호 목록을 반환한다.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_validator.py
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
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
python3 -m unittest tests/test_validator.py -v
```

Expected: FAIL

- [ ] **Step 3: Validator 구현**

```python
# validator.py
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
            if not fitz.Rect(block["bbox"]).is_empty:
                if not crop.contains(fitz.Rect(block["bbox"])):
                    return True
        for drawing in page.get_drawings():
            if not fitz.Rect(drawing["rect"]).is_empty:
                if not crop.contains(fitz.Rect(drawing["rect"])):
                    return True
        return False
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
python3 -m unittest tests/test_validator.py -v
```

Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add validator.py tests/test_validator.py
git commit -m "feat: Validator — 크롭 영역 밖 콘텐츠 잘림 페이지 탐색"
```

---

## Task 4: GUI — 기본 레이아웃 및 PDF 로드

**Files:**
- Create: `gui.py`

### 사전 조건: python-tk 설치 확인

```bash
python3 -c "import tkinter"
```

오류가 나면 설치:

```bash
brew install python-tk@3.14
```

Python 3.11을 쓰는 경우 `python3.11 gui.py` 로 실행한다 (`python-tk@3.11`은 이미 설치됨).

### 목표
tkinter 윈도우를 생성하고 PDF를 열어 첫 페이지를 중앙 뷰어에 표시한다.
하단 썸네일 스트립도 초기화한다.

레이아웃 구조:
```
┌─────────────────────────────────────────────┐
│  변환 영역: (x0, y0) — (x1, y1)             │
├──────┬───────────────────────────────┬───────┤
│      │                               │       │
│  <<  │     PDF 뷰어 Canvas           │  >>   │
│      │                               │       │
├──────┴───────────────────────────────┴───────┤
│  [썸네일1] [썸네일2] [썸네일3] ...           │
├──────────────────────────┬──────────┬────────┤
│                          │ Convert  │ Cancel │
└──────────────────────────┴──────────┴────────┘
```

- [ ] **Step 1: gui.py 기본 골격 작성**

```python
# gui.py
from __future__ import annotations

import base64
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import Optional

import fitz

from crop_store import CropStore
from validator import Validator


VIEWER_WIDTH = 700
VIEWER_HEIGHT = 900
THUMBNAIL_SIZE = (80, 110)
THUMBNAIL_DPI = 36
VIEWER_DPI = 120


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PDF to EPUB Converter")
        self.resizable(False, False)

        self._pdf_path: Optional[Path] = None
        self._page_count: int = 0
        self._current_page: int = 1
        self._crop_store = CropStore()

        # 드래그 상태
        self._drag_start: Optional[tuple[int, int]] = None
        self._drag_rect_id: Optional[int] = None
        # 현재 뷰어에 표시된 페이지의 렌더 스케일 (pt → px)
        self._scale_x: float = 1.0
        self._scale_y: float = 1.0

        self._build_ui()
        self._open_pdf()

    # ── UI 빌드 ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        # 상단: 변환 영역 표시 레이블
        self._crop_label = tk.Label(self, text="변환 영역: 미설정", anchor="w", padx=8)
        self._crop_label.pack(fill="x")

        # 중앙: 뷰어 + 네비게이션
        center_frame = tk.Frame(self)
        center_frame.pack(fill="both", expand=True)

        self._btn_prev = tk.Button(center_frame, text="<<", width=4,
                                   command=self._prev_page)
        self._btn_prev.pack(side="left", fill="y")

        self._canvas = tk.Canvas(center_frame,
                                  width=VIEWER_WIDTH, height=VIEWER_HEIGHT,
                                  bg="#888", cursor="crosshair")
        self._canvas.pack(side="left")
        self._canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self._canvas.bind("<B1-Motion>", self._on_drag_move)
        self._canvas.bind("<ButtonRelease-1>", self._on_drag_end)

        self._btn_next = tk.Button(center_frame, text=">>", width=4,
                                   command=self._next_page)
        self._btn_next.pack(side="left", fill="y")

        # 하단: 썸네일 스트립
        thumb_outer = tk.Frame(self, height=THUMBNAIL_SIZE[1] + 16, bd=1,
                                relief="sunken")
        thumb_outer.pack(fill="x")
        thumb_outer.pack_propagate(False)

        self._thumb_canvas = tk.Canvas(thumb_outer, height=THUMBNAIL_SIZE[1] + 16)
        scrollbar = ttk.Scrollbar(thumb_outer, orient="horizontal",
                                   command=self._thumb_canvas.xview)
        self._thumb_canvas.configure(xscrollcommand=scrollbar.set)
        scrollbar.pack(side="bottom", fill="x")
        self._thumb_canvas.pack(side="left", fill="both", expand=True)

        self._thumb_frame = tk.Frame(self._thumb_canvas)
        self._thumb_canvas.create_window((0, 0), window=self._thumb_frame, anchor="nw")

        # 하단: Convert / Cancel 버튼
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x")
        tk.Button(btn_frame, text="Convert", width=12,
                  command=self._on_convert).pack(side="right", padx=4, pady=4)
        tk.Button(btn_frame, text="Cancel", width=12,
                  command=self.destroy).pack(side="right", padx=4, pady=4)

    # ── PDF 열기 ─────────────────────────────────────────────

    def _open_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="PDF 파일을 선택하세요",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not path:
            self.destroy()
            return
        self._pdf_path = Path(path)
        with fitz.open(str(self._pdf_path)) as doc:
            self._page_count = doc.page_count
        self._current_page = 1
        self._render_page(self._current_page)
        self._build_thumbnails()

    # ── 페이지 렌더링 ─────────────────────────────────────────

    def _render_page(self, page_number: int) -> None:
        if self._pdf_path is None:
            return
        with fitz.open(str(self._pdf_path)) as doc:
            page = doc[page_number - 1]
            # 뷰어 크기에 맞게 스케일 계산
            scale = min(VIEWER_WIDTH / page.rect.width,
                        VIEWER_HEIGHT / page.rect.height)
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat)
            self._scale_x = pix.width / page.rect.width
            self._scale_y = pix.height / page.rect.height

        png_data = pix.tobytes("png")
        photo = tk.PhotoImage(data=base64.b64encode(png_data))
        self._canvas.config(width=pix.width, height=pix.height)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=photo)
        self._canvas._photo = photo  # GC 방지

        # 기존 크롭 영역이 있으면 표시
        rect = self._crop_store.get(page_number)
        if rect is not None:
            self._draw_crop_overlay(rect)
        self._update_crop_label(page_number)

    def _draw_crop_overlay(self, pdf_rect: tuple) -> None:
        """PDF 좌표계 rect를 캔버스 좌표로 변환해 오버레이로 그린다."""
        x0 = pdf_rect[0] * self._scale_x
        y0 = pdf_rect[1] * self._scale_y
        x1 = pdf_rect[2] * self._scale_x
        y1 = pdf_rect[3] * self._scale_y
        self._canvas.delete("crop_overlay")
        self._canvas.create_rectangle(
            x0, y0, x1, y1,
            outline="#00aaff", width=2, dash=(6, 3), tags="crop_overlay",
        )

    def _update_crop_label(self, page_number: int) -> None:
        rect = self._crop_store.get(page_number)
        override = "★ " if self._crop_store.has_override(page_number) else ""
        if rect:
            text = f"{override}변환 영역: ({rect[0]:.1f}, {rect[1]:.1f}) — ({rect[2]:.1f}, {rect[3]:.1f})  |  페이지 {page_number}/{self._page_count}"
        else:
            text = f"변환 영역: 미설정  |  페이지 {page_number}/{self._page_count}"
        self._crop_label.config(text=text)

    # ── 드래그 이벤트 ─────────────────────────────────────────

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_start = (event.x, event.y)
        self._canvas.delete("drag_rect")

    def _on_drag_move(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return
        self._canvas.delete("drag_rect")
        x0, y0 = self._drag_start
        self._canvas.create_rectangle(
            x0, y0, event.x, event.y,
            outline="#ff6600", width=2, tags="drag_rect",
        )

    def _on_drag_end(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return
        cx0, cy0 = self._drag_start
        cx1, cy1 = event.x, event.y
        self._drag_start = None
        self._canvas.delete("drag_rect")

        # 최소 크기 필터 (실수 클릭 방지)
        if abs(cx1 - cx0) < 10 or abs(cy1 - cy0) < 10:
            return

        # 캔버스 좌표 → PDF 좌표 변환
        pdf_rect = (
            min(cx0, cx1) / self._scale_x,
            min(cy0, cy1) / self._scale_y,
            max(cx0, cx1) / self._scale_x,
            max(cy0, cy1) / self._scale_y,
        )

        # 페이지 1에서는 항상 default 설정 (페이지 1은 override를 갖지 않는다).
        # 나머지 페이지는 per-page override 저장.
        # 결과적으로 페이지 1에 ★ 표시는 뜨지 않고, 나머지 페이지만 ★ 표시됨.
        if self._current_page == 1:
            self._crop_store.set_default(pdf_rect)
        else:
            self._crop_store.set(self._current_page, pdf_rect)

        self._draw_crop_overlay(pdf_rect)
        self._update_crop_label(self._current_page)

    # ── 썸네일 ────────────────────────────────────────────────

    def _build_thumbnails(self) -> None:
        if self._pdf_path is None:
            return
        for widget in self._thumb_frame.winfo_children():
            widget.destroy()

        with fitz.open(str(self._pdf_path)) as doc:
            for i in range(self._page_count):
                page = doc[i]
                scale = min(THUMBNAIL_SIZE[0] / page.rect.width,
                            THUMBNAIL_SIZE[1] / page.rect.height)
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
                png_data = pix.tobytes("png")
                photo = tk.PhotoImage(data=base64.b64encode(png_data))

                page_num = i + 1
                btn = tk.Button(
                    self._thumb_frame,
                    image=photo,
                    relief="flat",
                    command=lambda p=page_num: self._go_to_page(p),
                )
                btn.image = photo
                btn.pack(side="left", padx=2, pady=4)

        self._thumb_frame.update_idletasks()
        self._thumb_canvas.config(
            scrollregion=self._thumb_canvas.bbox("all")
        )

    # ── 네비게이션 ────────────────────────────────────────────

    def _prev_page(self) -> None:
        if self._current_page > 1:
            self._go_to_page(self._current_page - 1)

    def _next_page(self) -> None:
        if self._current_page < self._page_count:
            self._go_to_page(self._current_page + 1)

    def _go_to_page(self, page_number: int) -> None:
        self._current_page = page_number
        self._render_page(page_number)

    # ── 변환 ─────────────────────────────────────────────────

    def _on_convert(self) -> None:
        if self._pdf_path is None:
            return
        if self._crop_store.get(1) is None:
            messagebox.showwarning("변환 영역 미설정",
                                   "첫 페이지에서 변환 영역을 드래그로 지정해주세요.")
            return
        # 검증 → Task 5에서 구현
        self._run_validation_then_convert()

    def _run_validation_then_convert(self) -> None:
        # Task 5에서 구현
        pass


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실행 확인**

```bash
python3 gui.py
```

Expected: 파일 선택 다이얼로그 → PDF 선택 → 뷰어에 첫 페이지 표시 → 드래그로 영역 지정 시 파란 박스 오버레이 표시

- [ ] **Step 3: 커밋**

```bash
git add gui.py
git commit -m "feat: GUI 기본 레이아웃, PDF 뷰어, 드래그 크롭, 썸네일 스트립"
```

---

## Task 5: GUI — 검증 플로우 및 Convert 실행

**Files:**
- Modify: `gui.py` (`_run_validation_then_convert` 구현)

### 목표
Convert 클릭 시:
1. 모든 페이지를 검증해 잘리는 페이지 목록을 수집한다.
2. 잘리는 페이지가 있으면 메시지 박스로 알리고 해당 페이지로 안내한다.
3. 모든 페이지 확인 후 실제 변환을 실행한다.

- [ ] **Step 1: _run_validation_then_convert 구현**

`gui.py`의 `_run_validation_then_convert` 메서드를 교체:

```python
def _run_validation_then_convert(self) -> None:
    assert self._pdf_path is not None

    # 1. 전체 페이지 크롭 rect 수집
    all_rects = self._crop_store.all_rects(self._page_count)

    # 2. 검증
    validator = Validator(self._pdf_path)
    clipped = validator.find_clipped_pages(all_rects)

    # 3. 잘리는 페이지 안내
    if clipped:
        pages_str = ", ".join(str(p) for p in clipped)
        answer = messagebox.askyesno(
            "콘텐츠 잘림 감지",
            f"{pages_str} 페이지에서 지정된 영역 밖으로 콘텐츠가 잘립니다.\n"
            "각 페이지로 이동해 영역을 조정하시겠습니까?\n\n"
            "예 → 첫 번째 문제 페이지로 이동\n"
            "아니오 → 현재 설정으로 그대로 변환",
        )
        if answer:
            self._guide_through_clipped(clipped)
            return  # 사용자가 조정 후 다시 Convert를 눌러야 함

    # 4. 출력 경로 선택 후 변환 실행
    self._do_convert()

def _guide_through_clipped(self, clipped_pages: list[int]) -> None:
    """잘림이 감지된 페이지를 순서대로 안내한다."""
    if not clipped_pages:
        return
    first = clipped_pages[0]
    remaining = clipped_pages[1:]
    msg = f"페이지 {first}로 이동합니다. 영역을 조정한 뒤 Convert를 다시 눌러주세요."
    if remaining:
        msg += f"\n\n아직 {len(remaining)}개 페이지가 더 있습니다: {', '.join(str(p) for p in remaining)}"
    messagebox.showinfo("영역 조정 안내", msg)
    self._go_to_page(first)

def _do_convert(self) -> None:
    assert self._pdf_path is not None
    output_path = filedialog.asksaveasfilename(
        title="EPUB 저장 위치",
        defaultextension=".epub",
        initialfile=self._pdf_path.stem + ".epub",
        filetypes=[("EPUB files", "*.epub")],
    )
    if not output_path:
        return

    import sys
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pdf2epub",
        Path(__file__).parent / "pdf2epub.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["pdf2epub"] = module  # dataclass 해석에 필요 (Python 3.14)
    spec.loader.exec_module(module)

    all_rects = self._crop_store.all_rects(self._page_count)
    # None 제거 (None인 페이지는 get_content_bbox 사용)
    crop_rects = {p: r for p, r in all_rects.items() if r is not None}

    try:
        module.convert_pdf_to_epub(
            input_pdf=self._pdf_path,
            output_epub=Path(output_path),
            crop_rects=crop_rects,
        )
        messagebox.showinfo("완료", f"변환이 완료됐습니다:\n{output_path}")
    except Exception as e:
        messagebox.showerror("변환 실패", str(e))
```

- [ ] **Step 2: 실행 확인**

```bash
python3 gui.py
```

확인 시나리오:
1. PDF 열기 → 첫 페이지에서 영역 드래그
2. Convert 클릭 → 잘림 감지 시 페이지 목록 메시지 박스 확인
3. "예" → 해당 페이지로 이동, 영역 재조정
4. Convert 재클릭 → 저장 다이얼로그 → EPUB 생성 확인

- [ ] **Step 3: 커밋**

```bash
git add gui.py
git commit -m "feat: GUI 검증 플로우 및 Convert 실행 연결"
```

---

## Task 6: 전체 테스트 확인 및 마무리

- [ ] **Step 1: 전체 테스트 실행**

```bash
python3 -m unittest discover tests/ -v
```

Expected: 전체 PASS

- [ ] **Step 2: gui.py 실행 최종 확인**

실제 PDF로 전체 플로우 테스트:
- 영역 설정 → 검증 → 예외 페이지 조정 → Convert → EPUB 생성

- [ ] **Step 3: 최종 커밋**

```bash
git add .
git commit -m "feat: PDF crop GUI 완성 — 페이지별 영역 설정, 잘림 검증, EPUB 변환"
```
