# gui.py
from __future__ import annotations

import base64
import logging
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional
import tkinter as tk

import fitz

from crop_store import CropStore
from validator import Validator


# ── 로깅 설정 ────────────────────────────────────────────────────────────────

_LOG_PATH = Path(__file__).parent / f"pdf2epub_gui_{datetime.now():%Y%m%d_%H%M%S}.log"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("pdf2epub.gui")
log.info("GUI 시작. 로그 파일: %s", _LOG_PATH)


# ── 상수 ─────────────────────────────────────────────────────────────────────

THUMBNAIL_SIZE = (80, 112)
THUMBNAIL_STRIP_HEIGHT = THUMBNAIL_SIZE[1] + 44  # image + label + scrollbar + padding
HANDLE_SIZE = 8    # 리사이즈 핸들 한 변 (px)
HANDLE_HIT  = 10   # 핸들 클릭 인식 반경 (px)

# 핸들 이름 → (x축: -1=x0 이동, 0=없음, 1=x1 이동), (y축 동일)
_HANDLE_AXES: dict[str, tuple[int, int]] = {
    "nw": (-1, -1), "n": (0, -1), "ne": (1, -1),
    "e":  ( 1,  0),
    "se": ( 1,  1), "s": (0,  1), "sw": (-1,  1),
    "w":  (-1,  0),
}


# ── App ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        log.info("App.__init__ 시작")
        self.title("PDF to EPUB Converter")
        self.resizable(True, True)
        self.geometry("1000x820")

        self._pdf_path: Optional[Path] = None
        self._page_count: int = 0
        self._current_page: int = 1
        self._crop_store = CropStore()

        self._scale_x: float = 1.0
        self._scale_y: float = 1.0
        self._img_offset_x: float = 0.0   # 캔버스 내 이미지 좌상단 x (중앙 정렬용)
        self._img_offset_y: float = 0.0   # 캔버스 내 이미지 좌상단 y

        self._drag_mode: str = "none"   # "new_crop" | "handle"
        self._drag_start: Optional[tuple[int, int]] = None
        self._drag_handle: Optional[str] = None
        self._drag_pdf_rect_start: Optional[tuple] = None

        self._resize_job: Optional[str] = None
        self._thumb_buttons: list[tk.Button] = []
        self._ui_locked: bool = False

        self._build_ui()
        log.info("UI 빌드 완료")
        self._open_pdf()

    # ── UI 빌드 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        log.debug("_build_ui 진입")

        # 상단: 변환 영역 레이블
        self._crop_label = tk.Label(self, text="변환 영역: 미설정", anchor="w", padx=8)
        self._crop_label.pack(fill="x")

        # 상단: 기본값 툴바
        toolbar = tk.Frame(self)
        toolbar.pack(fill="x", padx=4, pady=2)
        self._btn_save_default = tk.Button(
            toolbar, text="기본값으로 저장", state="disabled",
            command=self._on_save_as_default,
        )
        self._btn_save_default.pack(side="left", padx=2)
        self._btn_load_default = tk.Button(
            toolbar, text="기본값 불러오기", state="disabled",
            command=self._on_load_default,
        )
        self._btn_load_default.pack(side="left", padx=2)
        self._default_label = tk.Label(toolbar, text="기본값: 미설정",
                                        fg="#666", anchor="w")
        self._default_label.pack(side="left", padx=8)

        # 중앙: 뷰어 + 네비게이션
        center_frame = tk.Frame(self)
        center_frame.pack(fill="both", expand=True)

        self._btn_prev = tk.Button(center_frame, text="<<", width=4,
                                   command=self._prev_page)
        self._btn_prev.pack(side="left", fill="y")

        self._canvas = tk.Canvas(center_frame, bg="#888", cursor="crosshair")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",       self._on_motion)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Configure>",       self._on_canvas_resize)

        self._btn_next = tk.Button(center_frame, text=">>", width=4,
                                   command=self._next_page)
        self._btn_next.pack(side="left", fill="y")

        # ── 하단 영역 (side="bottom" 역순 패킹) ──────────────────────────────
        # 1) 썸네일 스트립 — 가장 아래
        thumb_outer = tk.Frame(self, height=THUMBNAIL_STRIP_HEIGHT, bd=1,
                                relief="sunken")
        thumb_outer.pack(fill="x", side="bottom")
        thumb_outer.pack_propagate(False)

        h_scrollbar = ttk.Scrollbar(thumb_outer, orient="horizontal")
        h_scrollbar.pack(side="bottom", fill="x")

        self._thumb_canvas = tk.Canvas(thumb_outer, xscrollcommand=h_scrollbar.set,
                                        xscrollincrement=THUMBNAIL_SIZE[0] + 8)
        h_scrollbar.configure(command=self._thumb_canvas.xview)
        self._thumb_canvas.pack(fill="both", expand=True)

        self._thumb_frame = tk.Frame(self._thumb_canvas)
        self._thumb_canvas.create_window((0, 0), window=self._thumb_frame, anchor="nw")

        for w in (self._thumb_canvas, self._thumb_frame):
            w.bind("<MouseWheel>", self._on_thumb_scroll)
            w.bind("<Button-4>",   self._on_thumb_scroll)
            w.bind("<Button-5>",   self._on_thumb_scroll)

        # 2) 상태바 — 썸네일 바로 위
        status_frame = tk.Frame(self, bd=1, relief="sunken")
        status_frame.pack(fill="x", side="bottom")

        self._status_label = tk.Label(status_frame, text="준비", anchor="w", padx=6)
        self._status_label.pack(side="left", fill="x", expand=True)

        self._progress_bar = ttk.Progressbar(status_frame, length=200, mode="determinate")
        self._progress_bar.pack(side="right", padx=6, pady=2)

        # 3) Convert / Cancel 버튼 — 상태바 바로 위
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", side="bottom")
        self._btn_convert = tk.Button(btn_frame, text="Convert", width=12,
                                       command=self._on_convert)
        self._btn_convert.pack(side="right", padx=4, pady=4)
        tk.Button(btn_frame, text="Cancel", width=12,
                  command=self.destroy).pack(side="right", padx=4, pady=4)

        log.debug("_build_ui 완료")

    # ── 상태바 헬퍼 ──────────────────────────────────────────────────────────

    def _set_status(self, msg: str, value: int = 0, maximum: int = 0,
                    indeterminate: bool = False) -> None:
        """상태 메시지와 진행률 바를 업데이트한다. 반드시 메인 스레드에서 호출."""
        log.debug("상태: %s (value=%d, max=%d, indeterminate=%s)",
                  msg, value, maximum, indeterminate)
        self._status_label.config(text=msg)
        if indeterminate:
            self._progress_bar.config(mode="indeterminate")
            self._progress_bar.start(12)
        else:
            self._progress_bar.stop()
            self._progress_bar.config(mode="determinate",
                                       maximum=max(maximum, 1), value=value)
        # update_idletasks() 를 여기서 호출하면 ArrangePacking 이 누적된
        # 모든 위젯을 재배치해 O(n²) 레이아웃 폭발이 발생하므로 호출하지 않는다.

    def _lock_ui(self, lock: bool) -> None:
        """변환/썸네일 생성 중 버튼을 비활성화한다."""
        self._ui_locked = lock
        state = "disabled" if lock else "normal"
        self._btn_convert.config(state=state)
        self._btn_prev.config(state=state)
        self._btn_next.config(state=state)
        log.debug("UI %s", "잠금" if lock else "잠금 해제")

    # ── PDF 열기 ─────────────────────────────────────────────────────────────

    def _open_pdf(self) -> None:
        log.info("PDF 파일 선택 대화상자 열기")
        path = filedialog.askopenfilename(
            title="PDF 파일을 선택하세요",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not path:
            log.info("파일 선택 취소 → 종료")
            self.destroy()
            return

        self._pdf_path = Path(path)
        log.info("선택된 파일: %s", self._pdf_path)

        self._set_status("PDF 열기 중...")
        with fitz.open(str(self._pdf_path)) as doc:
            self._page_count = doc.page_count
        log.info("페이지 수: %d", self._page_count)

        self._current_page = 1
        self._render_page(self._current_page)
        self._build_thumbnails()

    # ── 페이지 렌더링 ────────────────────────────────────────────────────────

    def _render_page(self, page_number: int) -> None:
        if self._pdf_path is None:
            return
        log.debug("페이지 렌더링 시작: %d / %d", page_number, self._page_count)
        self._set_status(f"페이지 렌더링 중... ({page_number}/{self._page_count})")

        self.update_idletasks()
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw < 2:
            cw = 700
        if ch < 2:
            ch = 600

        with fitz.open(str(self._pdf_path)) as doc:
            page = doc[page_number - 1]
            scale = min(cw / page.rect.width, ch / page.rect.height)
            log.debug("캔버스 크기: %dx%d, 페이지 크기: %.1fx%.1f, 스케일: %.3f",
                      cw, ch, page.rect.width, page.rect.height, scale)
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            self._scale_x = pix.width / page.rect.width
            self._scale_y = pix.height / page.rect.height

        log.debug("픽스맵 생성 완료: %dx%d px, scale_x=%.3f scale_y=%.3f",
                  pix.width, pix.height, self._scale_x, self._scale_y)

        png_data = pix.tobytes("png")
        photo = tk.PhotoImage(data=base64.b64encode(png_data))

        # 이미지를 캔버스 중앙에 배치
        self._img_offset_x = (cw - pix.width) / 2
        self._img_offset_y = (ch - pix.height) / 2
        log.debug("이미지 offset: (%.1f, %.1f)", self._img_offset_x, self._img_offset_y)

        self._canvas.delete("all")
        self._canvas.create_image(self._img_offset_x, self._img_offset_y,
                                   anchor="nw", image=photo)
        self._canvas._photo = photo

        rect = self._crop_store.get(page_number)
        if rect is not None:
            log.debug("크롭 오버레이 적용: %s", rect)
            self._draw_crop_overlay(rect)
        self._update_crop_label(page_number)
        self._update_toolbar()
        self._set_status("준비")
        log.debug("페이지 렌더링 완료: %d", page_number)

    # ── 크롭 오버레이 ────────────────────────────────────────────────────────

    def _draw_crop_overlay(self, pdf_rect: tuple) -> None:
        ox = self._img_offset_x
        oy = self._img_offset_y
        x0 = pdf_rect[0] * self._scale_x + ox
        y0 = pdf_rect[1] * self._scale_y + oy
        x1 = pdf_rect[2] * self._scale_x + ox
        y1 = pdf_rect[3] * self._scale_y + oy
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        log.debug("오버레이 그리기: canvas(%.0f,%.0f)-(%.0f,%.0f), 캔버스 %dx%d",
                  x0, y0, x1, y1, cw, ch)

        self._canvas.delete("crop_overlay")

        # 바깥 마스크 (어두운 반투명) — 전체 캔버스 기준
        mask_kw = dict(fill="black", stipple="gray50",
                       outline="", tags="crop_overlay")
        self._canvas.create_rectangle(0,  0,  cw, y0, **mask_kw)
        self._canvas.create_rectangle(0,  y1, cw, ch, **mask_kw)
        self._canvas.create_rectangle(0,  y0, x0, y1, **mask_kw)
        self._canvas.create_rectangle(x1, y0, cw, y1, **mask_kw)

        # 크롭 테두리
        self._canvas.create_rectangle(
            x0, y0, x1, y1,
            outline="#00aaff", width=2, dash=(6, 3), tags="crop_overlay",
        )

        # 리사이즈 핸들
        hs = HANDLE_SIZE // 2
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        for hname, (hx, hy) in {
            "nw": (x0, y0), "n": (mx, y0), "ne": (x1, y0),
            "e":  (x1, my),
            "se": (x1, y1), "s": (mx, y1), "sw": (x0, y1),
            "w":  (x0, my),
        }.items():
            self._canvas.create_rectangle(
                hx - hs, hy - hs, hx + hs, hy + hs,
                fill="white", outline="#00aaff", width=1,
                tags=("crop_overlay", f"handle_{hname}"),
            )

    def _update_crop_label(self, page_number: int) -> None:
        rect = self._crop_store.get(page_number)
        override = "★ " if self._crop_store.has_override(page_number) else ""
        if rect:
            text = (f"{override}변환 영역: ({rect[0]:.1f}, {rect[1]:.1f}) — "
                    f"({rect[2]:.1f}, {rect[3]:.1f})  |  페이지 {page_number}/{self._page_count}")
        else:
            text = f"변환 영역: 미설정  |  페이지 {page_number}/{self._page_count}"
        self._crop_label.config(text=text)

    # ── 핸들 히트테스트 ──────────────────────────────────────────────────────

    def _hit_handle(self, cx: int, cy: int) -> Optional[str]:
        pdf_rect = self._crop_store.get(self._current_page)
        if pdf_rect is None:
            return None
        ox = self._img_offset_x
        oy = self._img_offset_y
        x0 = pdf_rect[0] * self._scale_x + ox
        y0 = pdf_rect[1] * self._scale_y + oy
        x1 = pdf_rect[2] * self._scale_x + ox
        y1 = pdf_rect[3] * self._scale_y + oy
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        for name, (hx, hy) in {
            "nw": (x0, y0), "n": (mx, y0), "ne": (x1, y0),
            "e":  (x1, my),
            "se": (x1, y1), "s": (mx, y1), "sw": (x0, y1),
            "w":  (x0, my),
        }.items():
            if abs(cx - hx) <= HANDLE_HIT and abs(cy - hy) <= HANDLE_HIT:
                log.debug("핸들 히트: %s at (%d,%d)", name, cx, cy)
                return name
        return None

    # ── 마우스 이벤트 ────────────────────────────────────────────────────────

    def _on_press(self, event: tk.Event) -> None:
        if self._ui_locked:
            return
        handle = self._hit_handle(event.x, event.y)
        if handle:
            log.debug("핸들 드래그 시작: %s", handle)
            self._drag_mode = "handle"
            self._drag_handle = handle
            self._drag_start = (event.x, event.y)
            self._drag_pdf_rect_start = self._crop_store.get(self._current_page)
        else:
            log.debug("새 크롭 드래그 시작: (%d,%d)", event.x, event.y)
            self._drag_mode = "new_crop"
            self._drag_start = (event.x, event.y)
            self._canvas.delete("drag_rect")

    def _on_motion(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return

        if self._drag_mode == "new_crop":
            x0, y0 = self._drag_start
            self._canvas.delete("drag_rect")
            self._canvas.create_rectangle(
                x0, y0, event.x, event.y,
                outline="#ff6600", width=2, tags="drag_rect",
            )

        elif self._drag_mode == "handle" and self._drag_pdf_rect_start is not None:
            dx = (event.x - self._drag_start[0]) / self._scale_x
            dy = (event.y - self._drag_start[1]) / self._scale_y
            r  = list(self._drag_pdf_rect_start)
            ax, ay = _HANDLE_AXES[self._drag_handle]
            if ax == -1: r[0] = min(r[0] + dx, r[2] - 1)
            elif ax == 1: r[2] = max(r[2] + dx, r[0] + 1)
            if ay == -1: r[1] = min(r[1] + dy, r[3] - 1)
            elif ay == 1: r[3] = max(r[3] + dy, r[1] + 1)
            self._canvas.delete("crop_overlay")
            self._draw_crop_overlay(tuple(r))    # offset은 _draw_crop_overlay 내부에서 적용

    def _on_release(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return
        sx, sy = self._drag_start
        self._drag_start = None

        if self._drag_mode == "new_crop":
            self._canvas.delete("drag_rect")
            if abs(event.x - sx) < 10 or abs(event.y - sy) < 10:
                log.debug("드래그 너무 짧음 — 무시")
                self._drag_mode = "none"
                return
            ox, oy = self._img_offset_x, self._img_offset_y
            pdf_rect = (
                (min(sx, event.x) - ox) / self._scale_x,
                (min(sy, event.y) - oy) / self._scale_y,
                (max(sx, event.x) - ox) / self._scale_x,
                (max(sy, event.y) - oy) / self._scale_y,
            )
            log.info("새 크롭 영역 설정 (페이지 %d): %s", self._current_page, pdf_rect)
            self._save_crop(pdf_rect)

        elif self._drag_mode == "handle" and self._drag_pdf_rect_start is not None:
            dx = (event.x - sx) / self._scale_x
            dy = (event.y - sy) / self._scale_y
            r = list(self._drag_pdf_rect_start)
            ax, ay = _HANDLE_AXES[self._drag_handle]
            if ax == -1: r[0] = min(r[0] + dx, r[2] - 1)
            elif ax == 1: r[2] = max(r[2] + dx, r[0] + 1)
            if ay == -1: r[1] = min(r[1] + dy, r[3] - 1)
            elif ay == 1: r[3] = max(r[3] + dy, r[1] + 1)
            log.info("핸들 조정 완료 (페이지 %d, 핸들 %s): %s",
                     self._current_page, self._drag_handle, tuple(r))
            self._save_crop(tuple(r))

        self._drag_mode = "none"
        self._drag_handle = None
        self._drag_pdf_rect_start = None

    def _save_crop(self, pdf_rect: tuple) -> None:
        self._crop_store.set(self._current_page, pdf_rect)
        self._canvas.delete("crop_overlay")
        self._draw_crop_overlay(pdf_rect)
        self._update_crop_label(self._current_page)
        self._update_toolbar()

    def _on_save_as_default(self) -> None:
        rect = self._crop_store.get(self._current_page)
        if rect is None:
            return
        log.info("기본값 저장: %s (페이지 %d에서)", rect, self._current_page)
        self._crop_store.set_default(rect)
        self._update_crop_label(self._current_page)
        self._update_toolbar()

    def _on_load_default(self) -> None:
        default = self._crop_store.get_default()
        if default is None:
            return
        log.info("기본값 불러오기 → 페이지 %d 적용: %s", self._current_page, default)
        self._crop_store.set(self._current_page, default)
        self._canvas.delete("crop_overlay")
        self._draw_crop_overlay(default)
        self._update_crop_label(self._current_page)
        self._update_toolbar()

    def _update_toolbar(self) -> None:
        has_rect    = self._crop_store.get(self._current_page) is not None
        has_default = self._crop_store.get_default() is not None
        self._btn_save_default.config(state="normal" if has_rect    else "disabled")
        self._btn_load_default.config(state="normal" if has_default else "disabled")
        default = self._crop_store.get_default()
        if default:
            self._default_label.config(
                text=f"기본값: ({default[0]:.1f}, {default[1]:.1f}) — "
                     f"({default[2]:.1f}, {default[3]:.1f})"
            )
        else:
            self._default_label.config(text="기본값: 미설정")

    # ── 썸네일 (백그라운드 스레드) ───────────────────────────────────────────

    def _build_thumbnails(self) -> None:
        log.info("썸네일 빌드 시작 (%d 페이지)", self._page_count)
        for w in self._thumb_frame.winfo_children():
            w.destroy()
        self._thumb_buttons = []
        self._lock_ui(True)
        self._set_status("썸네일 생성 중...", value=0, maximum=self._page_count)

        def worker() -> None:
            log.debug("썸네일 워커 스레드 시작")
            png_list: list[bytes] = []
            try:
                with fitz.open(str(self._pdf_path)) as doc:
                    for i in range(self._page_count):
                        page = doc[i]
                        scale = min(THUMBNAIL_SIZE[0] / page.rect.width,
                                    THUMBNAIL_SIZE[1] / page.rect.height)
                        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
                        png_list.append(pix.tobytes("png"))
                        log.debug("썸네일 렌더 완료: %d / %d", i + 1, self._page_count)
                        self.after(0, self._set_status,
                                   f"썸네일 생성 중... ({i+1}/{self._page_count})",
                                   i + 1, self._page_count)
            except Exception as exc:
                log.exception("썸네일 생성 오류: %s", exc)
                self.after(0, lambda: self._set_status("썸네일 생성 실패"))
                self.after(0, lambda: self._lock_ui(False))
                return
            log.info("썸네일 PNG 데이터 준비 완료, 메인 스레드에 위젯 생성 요청")
            self.after(0, lambda: self._finish_thumbnails(png_list))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_thumbnails(self, png_list: list[bytes]) -> None:
        log.debug("_finish_thumbnails: 배치 위젯 생성 시작 (총 %d)", len(png_list))
        self._finish_thumbnails_batch(png_list, 0)

    _THUMB_BATCH = 30  # 한 번에 생성할 썸네일 수

    def _finish_thumbnails_batch(self, png_list: list[bytes], start: int) -> None:
        end = min(start + self._THUMB_BATCH, len(png_list))
        log.debug("썸네일 위젯 생성: %d ~ %d", start + 1, end)

        for i in range(start, end):
            png_data = png_list[i]
            photo    = tk.PhotoImage(data=base64.b64encode(png_data))
            page_num = i + 1
            cell = tk.Frame(self._thumb_frame)
            cell.pack(side="left", padx=2, pady=4)

            btn = tk.Button(cell, image=photo, relief="flat", bd=2,
                            command=lambda p=page_num: self._go_to_page(p))
            btn.image = photo
            btn.pack()
            self._thumb_buttons.append(btn)
            lbl = tk.Label(cell, text=str(page_num), font=("Arial", 8))
            lbl.pack()

            for w in (cell, btn, lbl):
                w.bind("<MouseWheel>", self._on_thumb_scroll)
                w.bind("<Button-4>",   self._on_thumb_scroll)
                w.bind("<Button-5>",   self._on_thumb_scroll)

        if end < len(png_list):
            self._set_status(f"썸네일 표시 중... ({end}/{len(png_list)})",
                             value=end, maximum=len(png_list))
            self.after(0, self._finish_thumbnails_batch, png_list, end)
        else:
            # update_idletasks() 를 여기서 호출하면 N개 위젯 전체 재배치가
            # 한꺼번에 일어나 ArrangePacking O(n²) 폭발이 발생한다.
            # after(50) 으로 Tk 가 자연스럽게 배치를 끝낸 뒤 scrollregion 을 설정한다.
            log.info("썸네일 빌드 완료 (총 %d) — 50ms 뒤 마무리", len(png_list))
            self.after(50, self._finalize_thumbnails)

    def _finalize_thumbnails(self) -> None:
        """배치 생성 완료 후 50ms 지연 실행 — Tk 가 위젯 배치를 마친 뒤 호출된다."""
        self._thumb_canvas.config(scrollregion=self._thumb_canvas.bbox("all"))
        self._highlight_thumb(self._current_page)
        self._lock_ui(False)
        self._set_status("준비")
        log.info("썸네일 마무리 완료")

    def _highlight_thumb(self, page_number: int) -> None:
        for i, btn in enumerate(self._thumb_buttons):
            if i + 1 == page_number:
                btn.config(relief="solid", highlightbackground="#00aaff",
                           highlightthickness=2, highlightcolor="#00aaff")
            else:
                btn.config(relief="flat", highlightthickness=0)

        if not (self._thumb_buttons and 1 <= page_number <= len(self._thumb_buttons)):
            return

        # update_idletasks() 없이 위치를 수학적으로 계산한다.
        # 각 cell 슬롯 폭 = THUMBNAIL_SIZE[0](80) + bd*2(4) + pack padx*2(4) = 88
        # (xscrollincrement 와 동일하게 맞춰져 있다)
        _CELL_W = THUMBNAIL_SIZE[0] + 8  # 88px
        bx  = (page_number - 1) * _CELL_W
        bw  = THUMBNAIL_SIZE[0]
        cw  = self._thumb_canvas.winfo_width()
        sr  = self._thumb_canvas.bbox("all")
        if sr and sr[2] > cw:
            total_w = sr[2] - sr[0]
            target  = bx - (cw - bw) / 2
            self._thumb_canvas.xview_moveto(max(0.0, min(target / total_w, 1.0)))
            log.debug("썸네일 스크롤: 페이지 %d, bx=%d, fraction=%.3f",
                      page_number, bx, target / total_w)

    def _on_thumb_scroll(self, event: tk.Event) -> None:
        if event.num == 4:
            self._thumb_canvas.xview_scroll(-1, "units")
        elif event.num == 5:
            self._thumb_canvas.xview_scroll(1, "units")
        else:
            delta = -1 if event.delta > 0 else 1
            self._thumb_canvas.xview_scroll(delta, "units")

    # ── 창 리사이즈 ──────────────────────────────────────────────────────────

    def _on_canvas_resize(self, event: tk.Event) -> None:
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(150, self._render_page, self._current_page)

    # ── 네비게이션 ───────────────────────────────────────────────────────────

    def _prev_page(self) -> None:
        if self._current_page > 1:
            log.debug("이전 페이지: %d → %d", self._current_page, self._current_page - 1)
            self._go_to_page(self._current_page - 1)

    def _next_page(self) -> None:
        if self._current_page < self._page_count:
            log.debug("다음 페이지: %d → %d", self._current_page, self._current_page + 1)
            self._go_to_page(self._current_page + 1)

    def _go_to_page(self, page_number: int) -> None:
        log.info("페이지 이동: %d", page_number)
        self._current_page = page_number
        self._render_page(page_number)
        self._highlight_thumb(page_number)

    # ── 변환 ─────────────────────────────────────────────────────────────────

    def _on_convert(self) -> None:
        if self._pdf_path is None:
            return
        all_rects = self._crop_store.all_rects(self._page_count)
        if all(r is None for r in all_rects.values()):
            log.warning("변환 시도 — 영역 미설정")
            messagebox.showwarning("변환 영역 미설정",
                                   "변환 영역을 드래그로 지정하거나 기본값을 설정해주세요.")
            return
        log.info("변환 시작 요청")
        self._run_validation_then_convert()

    def _run_validation_then_convert(self) -> None:
        assert self._pdf_path is not None
        self._lock_ui(True)
        self._set_status("크롭 영역 검증 중...", indeterminate=True)
        log.info("검증 시작")

        all_rects = self._crop_store.all_rects(self._page_count)

        def worker() -> None:
            try:
                validator = Validator(self._pdf_path)
                clipped = validator.find_clipped_pages(all_rects)
                log.info("검증 완료 — 잘림 페이지: %s", clipped)
            except Exception as exc:
                log.exception("검증 오류: %s", exc)
                self.after(0, lambda: self._set_status("검증 실패"))
                self.after(0, lambda: self._lock_ui(False))
                return
            self.after(0, lambda: self._on_validation_done(clipped))

        threading.Thread(target=worker, daemon=True).start()

    def _on_validation_done(self, clipped: list[int]) -> None:
        self._lock_ui(False)
        self._set_status("준비")

        if clipped:
            pages_str = ", ".join(str(p) for p in clipped)
            log.warning("콘텐츠 잘림 감지: 페이지 %s", pages_str)
            answer = messagebox.askyesno(
                "콘텐츠 잘림 감지",
                f"{pages_str} 페이지에서 지정된 영역 밖으로 콘텐츠가 잘립니다.\n"
                "각 페이지로 이동해 영역을 조정하시겠습니까?\n\n"
                "예 → 첫 번째 문제 페이지로 이동\n"
                "아니오 → 현재 설정으로 그대로 변환",
            )
            if answer:
                self._guide_through_clipped(clipped)
                return

        self._do_convert()

    def _guide_through_clipped(self, clipped_pages: list[int]) -> None:
        if not clipped_pages:
            return
        first = clipped_pages[0]
        remaining = clipped_pages[1:]
        msg = f"페이지 {first}로 이동합니다. 영역을 조정한 뒤 Convert를 다시 눌러주세요."
        if remaining:
            msg += (f"\n\n아직 {len(remaining)}개 페이지가 더 있습니다: "
                    f"{', '.join(str(p) for p in remaining)}")
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
            log.info("저장 경로 선택 취소")
            return

        log.info("변환 시작: %s → %s", self._pdf_path, output_path)
        self._lock_ui(True)
        self._set_status("EPUB 변환 중...", indeterminate=True)

        import sys
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "pdf2epub", Path(__file__).parent / "pdf2epub.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["pdf2epub"] = module
        spec.loader.exec_module(module)

        all_rects  = self._crop_store.all_rects(self._page_count)
        crop_rects = {p: r for p, r in all_rects.items() if r is not None}
        out        = Path(output_path)
        log.debug("변환 crop_rects 수: %d", len(crop_rects))

        def worker() -> None:
            try:
                module.convert_pdf_to_epub(
                    input_pdf=self._pdf_path,
                    output_epub=out,
                    crop_rects=crop_rects,
                )
                log.info("변환 완료: %s", out)
                self.after(0, lambda: messagebox.showinfo(
                    "완료", f"변환이 완료됐습니다:\n{out}"))
            except Exception as exc:
                log.exception("변환 실패: %s", exc)
                self.after(0, lambda: messagebox.showerror("변환 실패", str(exc)))
            finally:
                self.after(0, lambda: self._set_status("준비"))
                self.after(0, lambda: self._lock_ui(False))

        threading.Thread(target=worker, daemon=True).start()


# ── 진입점 ────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("main() 호출")
    app = App()
    app.mainloop()
    log.info("mainloop 종료")


if __name__ == "__main__":
    main()
