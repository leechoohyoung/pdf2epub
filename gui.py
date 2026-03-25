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


VIEWER_WIDTH = 900
VIEWER_HEIGHT = 1100
THUMBNAIL_SIZE = (100, 140)
THUMBNAIL_DPI = 36
VIEWER_DPI = 120


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PDF to EPUB Converter")
        self.resizable(True, True)

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

        self._resize_job: Optional[str] = None

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
        self._canvas.pack(side="left", fill="both", expand=True)
        self._canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self._canvas.bind("<B1-Motion>", self._on_drag_move)
        self._canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self._canvas.bind("<Configure>", self._on_canvas_resize)

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
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        # 위젯이 아직 배치되지 않은 경우 기본값 사용
        if cw < 2:
            cw = VIEWER_WIDTH
        if ch < 2:
            ch = VIEWER_HEIGHT
        with fitz.open(str(self._pdf_path)) as doc:
            page = doc[page_number - 1]
            scale = min(cw / page.rect.width, ch / page.rect.height)
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat)
            self._scale_x = pix.width / page.rect.width
            self._scale_y = pix.height / page.rect.height

        png_data = pix.tobytes("png")
        photo = tk.PhotoImage(data=base64.b64encode(png_data))
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

    # ── 창 리사이즈 ───────────────────────────────────────────

    def _on_canvas_resize(self, event: tk.Event) -> None:
        """창 크기 변경 시 페이지를 재렌더링한다 (디바운스 150ms)."""
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(150, self._render_page, self._current_page)

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


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
