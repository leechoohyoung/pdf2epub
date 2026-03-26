# gui.py
from __future__ import annotations

import subprocess
import sys

# ── 부트스트랩: 필수 패키지 자동 설치 ─────────────────────────────────────────
_REQUIRED_PACKAGES = [
    ("PyMuPDF", "fitz"),
    ("marker-pdf", "marker"),
]

def _install(package: str) -> bool:
    """pip 으로 패키지를 설치한다. 성공 여부를 반환한다."""
    pip_args = [sys.executable, "-m", "pip", "install", "-q", package]
    # Homebrew Python 등 시스템 격리 환경에서는 --break-system-packages 필요
    r = subprocess.run(pip_args + ["--break-system-packages"], capture_output=True)
    if r.returncode != 0:
        r = subprocess.run(pip_args, capture_output=True)
    return r.returncode == 0

for _pkg, _imp in _REQUIRED_PACKAGES:
    try:
        __import__(_imp)
    except ImportError:
        print(f"[bootstrap] {_pkg} 설치 중...", flush=True)
        if _install(_pkg):
            print(f"[bootstrap] {_pkg} 설치 완료", flush=True)
        else:
            print(f"[bootstrap] 오류: {_pkg} 설치 실패. 수동으로 설치해주세요: pip install {_pkg}", flush=True)
            sys.exit(1)
# ──────────────────────────────────────────────────────────────────────────────

import base64
import logging
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional
import tkinter as tk

import fitz

from i18n import _t
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
log.info(_t("log_start", path=_LOG_PATH))


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


# ── 로그 핸들러 / tqdm 라우터 ────────────────────────────────────────────────

import re as _re

class _GUILogHandler(logging.Handler):
    """Python 로그 레코드를 tk.Text 위젯으로 라우팅한다."""

    def __init__(self, widget: "tk.Text") -> None:
        super().__init__()
        self._widget = widget

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record) + "\n"
            self._widget.after(0, self._append, msg)
        except Exception:
            pass

    def _append(self, msg: str) -> None:
        try:
            self._widget.config(state="normal")
            self._widget.insert("end", msg)
            self._widget.see("end")
            self._widget.config(state="disabled")
        except tk.TclError:
            pass


class _TqdmRouter:
    """sys.stderr 를 가로채 tqdm 출력을 파싱해 상태/진행률 콜백으로 라우팅한다."""

    _TQDM_RE = _re.compile(
        r"^(?P<stage>[^:]+):\s+(?P<pct>\d+)%\|[^|]*\|\s*(?P<cur>\d+)/(?P<tot>\d+)"
    )

    def __init__(self, log_fn, status_fn, progress_fn) -> None:
        self._log = log_fn
        self._status = status_fn
        self._progress = progress_fn
        self._orig_stderr = None
        self._buf = ""

    def __enter__(self) -> "_TqdmRouter":
        self._orig_stderr = sys.stderr
        sys.stderr = self
        return self

    def __exit__(self, *_) -> None:
        sys.stderr = self._orig_stderr

    def write(self, text: str) -> None:
        if self._orig_stderr:
            self._orig_stderr.write(text)
        self._buf += text
        parts = _re.split(r"[\r\n]", self._buf)
        self._buf = parts[-1]
        for line in parts[:-1]:
            line = line.strip()
            if not line:
                continue
            m = self._TQDM_RE.match(line)
            if m:
                stage = m.group("stage").strip()
                pct   = int(m.group("pct"))
                cur   = m.group("cur")
                tot   = m.group("tot")
                self._status(f"{stage}: {cur}/{tot}")
                self._progress(pct)
                if pct == 100:
                    self._log(f"✓ {stage} Done ({tot})\n")
            else:
                self._log(line + "\n")

    def flush(self) -> None:
        if self._orig_stderr:
            self._orig_stderr.flush()


# ── App ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        log.info("App.__init__ 시작")
        self.title(_t("app_title"))
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

        self._pulse_job: Optional[str] = None
        self._pulse_value: int = 0
        self._pulse_direction: int = 1

        self._var_text_mode = tk.BooleanVar(value=False)
        self._var_log_visible = tk.BooleanVar(value=False)
        self._log_panel_visible: bool = False

        self._build_menu()
        self._build_ui()
        log.info("UI 빌드 완료")
        # 시작 시 즉시 파일 선택 대화상자를 띄우지 않음
        # self._open_pdf()

    # ── 메뉴바 빌드 ───────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        # 파일 메뉴
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label=_t("menu_open"), command=self._on_open_other_pdf)
        file_menu.add_separator()
        file_menu.add_command(label=_t("menu_exit"), command=self.destroy)
        menubar.add_cascade(label=_t("menu_file"), menu=file_menu)

        # 옵션 메뉴
        options_menu = tk.Menu(menubar, tearoff=0)
        options_menu.add_checkbutton(
            label=_t("menu_text_mode"),
            variable=self._var_text_mode,
        )
        options_menu.add_checkbutton(
            label=_t("menu_show_log"),
            variable=self._var_log_visible,
            command=self._on_log_menu_toggle,
        )
        menubar.add_cascade(label=_t("menu_options"), menu=options_menu)

        # 언어 메뉴 (Language)
        lang_menu = tk.Menu(menubar, tearoff=0)
        lang_menu.add_command(label=_t("lang_ko"), command=lambda: self._change_language("ko"))
        lang_menu.add_command(label=_t("lang_en"), command=lambda: self._change_language("en"))
        menubar.add_cascade(label=_t("menu_language"), menu=lang_menu)

    def _change_language(self, lang: str) -> None:
        """선택한 언어로 설정을 변경하고 화면의 텍스트를 즉시 새로고침한다."""
        from i18n import set_language
        set_language(lang)
        log.info("언어 변경: %s", lang)
        
        # 메뉴바 다시 빌드 (기존 위젯은 그대로 두고 설정만 변경)
        self._build_menu()
        
        # 기본 텍스트 갱신
        self.title(_t("app_title"))
        self._btn_save_default.config(text=_t("btn_apply_subsequent"))
        self._btn_load_default.config(text=_t("btn_load_default"))
        self._btn_set_cover.config(text=_t("btn_set_cover"))
        self._btn_prev.config(text=_t("btn_prev"))
        self._btn_next.config(text=_t("btn_next"))
        self._btn_convert.config(text=_t("btn_convert"))
        self._btn_cancel.config(text=_t("btn_cancel"))
        self._status_label.config(text=_t("status_ready"))
        
        # 동적 레이블 갱신
        self._update_toolbar()
        self._update_crop_label(self._current_page)
        self._cover_label.config(text=f"{_t('label_cover')}: {self._cover_page}{_t('label_page')}")
        
        # 캔버스 가이드 텍스트 갱신
        if self._pdf_path is None:
            self._canvas.itemconfigure("startup_guide_text", text=_t("guide_startup"))
        elif self._crop_store.get(self._current_page) is None:
            self._canvas.itemconfigure("guide_text_text", text=_t("guide_drag"))

    def _on_open_other_pdf(self) -> None:
        """기존 문서를 닫고 새로운 PDF를 선택하여 엽니다."""
        log.info(_t("log_open_pdf"))
        self._open_pdf()

    def _on_log_menu_toggle(self) -> None:
        """메뉴의 체크 상태에 따라 로그 패널을 강제로 열거나 닫는다."""
        show = self._var_log_visible.get()
        if show and not self._log_panel_visible:
            self._toggle_log_panel()
        elif not show and self._log_panel_visible:
            self._toggle_log_panel()

    # ── UI 빌드 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        log.debug("_build_ui 진입")

        # 상단: 변환 영역 레이블
        self._crop_label = tk.Label(self, text=f"💡 {_t('guide_drag')}  |  {_t('label_page')} 0/0", anchor="w", padx=8)
        self._crop_label.pack(fill="x")

        # 상단: 기본값 툴바
        toolbar = tk.Frame(self)
        toolbar.pack(fill="x", padx=4, pady=2)
        self._btn_save_default = tk.Button(
            toolbar, text=_t("btn_apply_subsequent"), state="disabled",
            command=self._on_save_as_default,
        )
        self._btn_save_default.pack(side="left", padx=2)
        self._btn_load_default = tk.Button(
            toolbar, text=_t("btn_load_default"), state="disabled",
            command=self._on_load_default,
        )
        self._btn_load_default.pack(side="left", padx=2)
        self._default_label = tk.Label(toolbar, text=f"{_t('label_crop_area')} ({_t('btn_load_default')}): {_t('label_not_set')}",
                                        fg="#666", anchor="w")
        self._default_label.pack(side="left", padx=8)

        # 표지 지정 버튼 추가
        self._cover_page: Optional[int] = 1 # 기본값 1페이지
        self._btn_set_cover = tk.Button(
            toolbar, text=_t("btn_set_cover"), state="disabled",
            command=self._on_set_cover,
        )
        self._btn_set_cover.pack(side="left", padx=2)
        self._cover_label = tk.Label(toolbar, text=f"{_t('label_cover')}: 1{_t('label_page')}", fg="#0055cc")
        self._cover_label.pack(side="left", padx=8)


        # 중앙: 뷰어 + 네비게이션
        center_frame = tk.Frame(self)
        center_frame.pack(fill="both", expand=True)

        self._btn_prev = tk.Button(center_frame, text="이전 페이지",
                                   command=self._prev_page)
        self._btn_prev.pack(side="left", fill="y")

        self._canvas = tk.Canvas(center_frame, bg="#888", cursor="crosshair")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",       self._on_motion)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Configure>",       self._on_canvas_resize)

        self._btn_next = tk.Button(center_frame, text="다음 페이지",
                                   command=self._next_page)
        self._btn_next.pack(side="left", fill="y")

        # 중앙 캔버스 초기 상태 (PDF 열기 안내)
        cw = 700
        ch = 600
        self._canvas.create_text(
            cw / 2, ch / 2,
            text=_t("guide_startup"),
            fill="#ffffff", font=("Arial", 16, "bold"),
            tags=("startup_guide", "startup_guide_text")
        )
        self._canvas.tag_lower(
            self._canvas.create_rectangle(
                cw / 2 - 320, ch / 2 - 30, cw / 2 + 320, ch / 2 + 30,
                fill="#333333", outline="#00aaff", width=2, tags="startup_guide"
            ),
            "startup_guide"
        )

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

        # 2) 아코디언 상태바 — 썸네일 바로 위
        accordion = tk.Frame(self, bd=1, relief="sunken")
        accordion.pack(fill="x", side="bottom")

        # 2-a) 로그 패널 (접힘 상태로 시작, pack_propagate=False 로 높이 고정)
        self._log_panel = tk.Frame(accordion, height=160)
        self._log_panel.pack_propagate(False)
        _log_sb = ttk.Scrollbar(self._log_panel, orient="vertical")
        _log_sb.pack(side="right", fill="y")
        self._log_text = tk.Text(
            self._log_panel,
            bg="#1e1e1e", fg="#d4d4d4",
            font=("Courier", 9),
            state="disabled",
            wrap="word",
            yscrollcommand=_log_sb.set,
        )
        self._log_text.pack(side="left", fill="both", expand=True)
        _log_sb.config(command=self._log_text.yview)
        # 초기에는 숨김 (pack 하지 않음)

        # 2-b) 헤더 행 (항상 표시)
        self._accordion_header = tk.Frame(accordion)
        self._accordion_header.pack(fill="x")

        self._status_label = tk.Label(
            self._accordion_header, text=_t("status_ready"), anchor="w", padx=4,
        )
        self._status_label.pack(side="left", fill="x", expand=True)

        self._progress_bar = ttk.Progressbar(
            self._accordion_header, length=200, mode="determinate",
        )
        self._progress_bar.pack(side="right", padx=6, pady=2)

        # 2-c) GUI 로그 핸들러 등록 (INFO 이상만 표시)
        _gui_handler = _GUILogHandler(self._log_text)
        _gui_handler.setLevel(logging.INFO)
        _gui_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(message)s", datefmt="%H:%M:%S",
        ))
        logging.getLogger().addHandler(_gui_handler)
        # pdf2epub 패키지 내부 로거들이 propagate=False 로 설정될 수 있으므로 명시적 추가
        logging.getLogger("pdf2epub").addHandler(_gui_handler)

        # 3) Convert / Cancel 버튼 — 상태바 바로 위
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", side="bottom")
        self._btn_convert = tk.Button(btn_frame, text=_t("btn_convert"), width=12,
                                       command=self._on_convert)
        self._btn_convert.pack(side="right", padx=4, pady=4)
        self._btn_cancel = tk.Button(btn_frame, text=_t("btn_cancel"), width=12,
                  command=self.destroy)
        self._btn_cancel.pack(side="right", padx=4, pady=4)

        log.debug("_build_ui 완료")

    # ── 상태바 헬퍼 ──────────────────────────────────────────────────────────

    def _set_status(self, msg: str, value: int = 0, maximum: int = 0,
                    indeterminate: bool = False) -> None:
        """상태 메시지와 진행률 바를 업데이트한다. 반드시 메인 스레드에서 호출."""
        log.debug("Status: %s (value=%d, max=%d, indeterminate=%s)",
                  msg, value, maximum, indeterminate)
        self._status_label.config(text=msg)
        if indeterminate:
            self._start_pulse()
        else:
            self._stop_pulse()
            self._progress_bar.config(mode="determinate",
                                       maximum=max(maximum, 1), value=value)

    def _start_pulse(self) -> None:
        """native indeterminate 대신 determinate 모드로 직접 펄스 애니메이션."""
        if self._pulse_job is not None:
            return  # 이미 실행 중
        self._progress_bar.config(mode="determinate", maximum=100)
        self._pulse_value = 0
        self._pulse_direction = 1
        self._step_pulse()

    def _step_pulse(self) -> None:
        self._pulse_value += 2
        if self._pulse_value > 100:
            self._pulse_value = 0
        self._progress_bar.config(value=self._pulse_value)
        self._pulse_job = self.after(20, self._step_pulse)

    def _stop_pulse(self) -> None:
        if self._pulse_job is not None:
            self.after_cancel(self._pulse_job)
            self._pulse_job = None
        self._progress_bar.config(value=0)

    def _lock_ui(self, lock: bool) -> None:
        """변환/썸네일 생성 중 버튼을 비활성화한다."""
        self._ui_locked = lock
        state = "disabled" if lock else "normal"
        self._btn_convert.config(state=state)
        self._btn_prev.config(state=state)
        self._btn_next.config(state=state)
        log.debug("UI %s", "Locked" if lock else "Unlocked")

    # ── 로그 패널 헬퍼 ───────────────────────────────────────────────────────

    def _toggle_log_panel(self) -> None:
        if self._log_panel_visible:
            self._log_panel.pack_forget()
            self._log_panel_visible = False
            self._var_log_visible.set(False)
        else:
            self._log_panel.pack(
                fill="both", expand=True,
                before=self._accordion_header,
            )
            self._log_panel_visible = True
            self._var_log_visible.set(True)

    def _append_log(self, msg: str) -> None:
        """스레드에서 호출 가능한 로그 텍스트 추가."""
        def _do() -> None:
            try:
                self._log_text.config(state="normal")
                self._log_text.insert("end", msg)
                self._log_text.see("end")
                self._log_text.config(state="disabled")
            except tk.TclError:
                pass
        self.after(0, _do)

    def _set_progress_direct(self, pct: int) -> None:
        """펄스 애니메이션을 중지하고 실제 진행률(0-100)을 표시한다."""
        self._stop_pulse()
        self._progress_bar.config(mode="determinate", maximum=100, value=pct)

    # ── PDF 열기 ─────────────────────────────────────────────────────────────

    def _open_pdf(self) -> None:
        log.info(_t("log_open_pdf"))
        path = filedialog.askopenfilename(
            title=_t("menu_open"),
            filetypes=[("PDF files", "*.pdf")],
        )
        if not path:
            log.info("File selection cancelled")
            return

        self._pdf_path = Path(path)
        log.info(_t("log_selected", path=self._pdf_path))

        # 새 문서를 열 때 이전의 크롭 영역 설정(CropStore) 및 표지 설정 완전히 초기화
        self._crop_store = CropStore()
        self._cover_page = 1
        self._cover_label.config(text=f"{_t('label_cover')}: 1{_t('label_page')}")
        self._update_toolbar()

        self._set_status(_t("status_opening"))
        with fitz.open(str(self._pdf_path)) as doc:
            self._page_count = doc.page_count
        log.info(_t("log_page_count", count=self._page_count))

        self._current_page = 1
        # 새 문서를 로드하므로 시작 시 그려뒀던 "다른 PDF 열기" 가이드라인 삭제
        self._canvas.delete("startup_guide")
        
        self._render_page(self._current_page)
        self._build_thumbnails()

    # ── 페이지 렌더링 ────────────────────────────────────────────────────────

    def _render_page(self, page_number: int) -> None:
        if self._pdf_path is None:
            return
        log.debug("Rendering page: %d / %d", page_number, self._page_count)
        self._set_status(f"{_t('status_rendering')} ({page_number}/{self._page_count})")

        self.update_idletasks()
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw < 2: cw = 700
        if ch < 2: ch = 600

        with fitz.open(str(self._pdf_path)) as doc:
            page = doc[page_number - 1]
            scale = min(cw / page.rect.width, ch / page.rect.height)
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            self._scale_x = pix.width / page.rect.width
            self._scale_y = pix.height / page.rect.height

        png_data = pix.tobytes("png")
        photo = tk.PhotoImage(data=base64.b64encode(png_data))

        self._img_offset_x = (cw - pix.width) / 2
        self._img_offset_y = (ch - pix.height) / 2

        self._canvas.delete("all")
        self._canvas.create_image(self._img_offset_x, self._img_offset_y,
                                   anchor="nw", image=photo)
        self._canvas._photo = photo

        rect = self._crop_store.get(page_number)
        if rect is not None:
            self._draw_crop_overlay(rect)
        else:
            # 영역 미지정 시 캔버스 중앙에 시각적 가이드 추가
            cw = self._canvas.winfo_width()
            ch = self._canvas.winfo_height()
            self._canvas.create_text(
                cw / 2, ch / 2,
                text=_t("guide_drag"),
                fill="#ffffff", font=("Arial", 16, "bold"),
                tags=("guide_text", "guide_text_text")
            )
            # 가이드 텍스트 뒤에 배경 박스 (가독성 및 눈에 띄게)
            self._canvas.tag_lower(
                self._canvas.create_rectangle(
                    cw / 2 - 190, ch / 2 - 30, cw / 2 + 190, ch / 2 + 30,
                    fill="#0055cc", outline="#ffffff", width=2, tags="guide_text"
                ),
                "guide_text"
            )

        self._update_crop_label(page_number)
        self._update_toolbar()
        self._set_status(_t("status_ready"))

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
            text = f"💡 마우스로 드래그하여 변환할 영역을 지정하세요  |  페이지 {page_number}/{self._page_count}"
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
        # 가이드 텍스트 즉시 삭제 (드래그 시작 시)
        self._canvas.delete("guide_text")
        
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

        # 새 기본값을 저장하기 전에, 현재 페이지 이전 페이지 중
        # 명시적 override 가 없는 페이지를 기존 default 로 고정한다.
        # (예: 1페이지에서 a를 기본값으로 저장 → n+1페이지에서 b를 새 기본값으로 저장할 때
        #  2~n 페이지는 a로 freeze 되어야 한다.)
        old_default = self._crop_store.get_default()
        if old_default is not None:
            for p in range(1, self._current_page):
                if not self._crop_store.has_override(p):
                    self._crop_store.set(p, old_default)
            log.info("기존 기본값 %s → 페이지 1~%d 중 override 없는 페이지에 고정",
                     old_default, self._current_page - 1)

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

    def _on_set_cover(self) -> None:
        self._cover_page = self._current_page
        self._cover_label.config(text=f"표지: {self._cover_page}페이지")
        log.info("표지 페이지 설정: %d", self._cover_page)
        # 썸네일 하이라이트 갱신 (선택 사항)
        self._highlight_thumb(self._current_page)

    def _update_toolbar(self) -> None:
        if self._pdf_path is None:
            return
        
        has_rect    = self._crop_store.get(self._current_page) is not None
        has_default = self._crop_store.get_default() is not None
        self._btn_save_default.config(state="normal" if has_rect    else "disabled")
        self._btn_load_default.config(state="normal" if has_default else "disabled")
        self._btn_set_cover.config(state="normal") # 문서가 열려있으면 항상 가능

        default = self._crop_store.get_default()
        if default:
            self._default_label.config(
                text=f"기본 영역: ({default[0]:.1f}, {default[1]:.1f}) — "
                     f"({default[2]:.1f}, {default[3]:.1f})"
            )
        else:
            self._default_label.config(text="기본 영역: 미설정")

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
                        if (i + 1) % 10 == 0 or (i + 1) == self._page_count:
                            self.after(0, self._set_status,
                                       f"썸네일 생성 중... ({i+1}/{self._page_count})",
                                       i + 1, self._page_count)
            except Exception as exc:
                log.exception("썸네일 생성 오류: %s", exc)
                self.after(0, lambda: self._set_status("썸네일 생성 실패"))
                self.after(0, lambda: self._lock_ui(False))
                return
            log.info("썸네일 PNG 데이터 준비 완료, 메인 스레드에 위젯 생성 요청")
            self.after(10, lambda: self._finish_thumbnails(png_list))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_thumbnails(self, png_list: list[bytes]) -> None:
        log.debug("_finish_thumbnails: 배치 위젯 생성 시작 (총 %d)", len(png_list))
        self._finish_thumbnails_batch(png_list, 0)

    _THUMB_BATCH = 15  # 한 번에 생성할 썸네일 수를 더 줄여서 부드럽게 유지

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
            # 메인 루프가 이벤트를 처리하고 화면을 다시 그릴 여유를 준다
            self.after(20, self._finish_thumbnails_batch, png_list, end)
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

    def _ask_clipped_dialog(self, pages_str: str) -> bool:
        """잘림 감지 다이얼로그 — True: Edit Area, False: Proceed."""
        result: list[bool] = [False]
        dlg = tk.Toplevel(self)
        dlg.title(_t("dlg_clipped_title"))
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(
            dlg,
            text=_t("dlg_clipped_msg", pages=pages_str),
            justify="left",
            padx=20,
            pady=16,
            wraplength=420,
        ).pack()

        btn_frame = tk.Frame(dlg)
        btn_frame.pack(pady=(0, 14))

        def on_edit() -> None:
            result[0] = True
            dlg.destroy()

        def on_proceed() -> None:
            dlg.destroy()

        tk.Button(btn_frame, text="Edit Area", width=12, command=on_edit).pack(
            side="left", padx=8
        )
        tk.Button(btn_frame, text="Proceed", width=12, command=on_proceed).pack(
            side="left", padx=8
        )

        dlg.wait_window()
        return result[0]

    def _on_validation_done(self, clipped: list[int]) -> None:
        self._lock_ui(False)
        self._set_status(_t("status_ready"))

        if clipped:
            pages_str = ", ".join(str(p) for p in clipped)
            log.warning("Content cutoff detected: page %s", pages_str)
            # --- 사용자 요청으로 잘림 경고 팝업 생략 및 즉시 변환 ---
            # answer = self._ask_clipped_dialog(pages_str)
            # if answer:
            #     self._guide_through_clipped(clipped)
            #     return

        self._do_convert()

    def _guide_through_clipped(self, clipped_pages: list[int]) -> None:
        if not clipped_pages:
            return
        first = clipped_pages[0]
        msg = _t("dlg_guide_msg", page=first)
        messagebox.showinfo(_t("dlg_guide_title"), msg)
        self._go_to_page(first)

    def _do_convert(self) -> None:
        assert self._pdf_path is not None
        output_path = filedialog.asksaveasfilename(
            title=_t("app_title"),
            defaultextension=".epub",
            initialfile=self._pdf_path.stem + ".epub",
            filetypes=[("EPUB files", "*.epub")],
        )
        if not output_path:
            log.info("Save path selection cancelled")
            return

        use_text_mode = self._var_text_mode.get()
        log.info(_t("log_convert_start", input=self._pdf_path.name, output=Path(output_path).name, mode=str(use_text_mode)))
        self._lock_ui(True)
        
        # --- 사용자 요청으로 로그 패널 강제 활성화 제거 ---
        # if not self._log_panel_visible:
        #     self._toggle_log_panel()
        
        self._set_status(
            _t("status_loading_models") if use_text_mode else _t("status_converting"),
            indeterminate=True,
        )

        # ... (생략된 임포트 및 모듈 로드 코드)
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
        log.debug("Crop rects count: %d", len(crop_rects))

        def _on_convert_done(success: bool, msg: str) -> None:
            """메인 스레드에서 실행되어 팝업과 UI 잠금 해제를 순차적으로 안전하게 처리한다."""
            self._set_status(_t("status_ready"))
            if success:
                messagebox.showinfo(_t("msg_done"), msg, parent=self)
            else:
                messagebox.showerror(_t("msg_fail"), msg, parent=self)
            self._lock_ui(False)

        def worker() -> None:
            try:
                if use_text_mode:
                    module.convert_pdf_to_epub_text_mode(
                        input_pdf=self._pdf_path,
                        output_epub=out,
                        crop_rects=crop_rects if crop_rects else None,
                        logger=log,
                        progress_callback=lambda cur, tot: self.after(
                            0, lambda: self._set_status(f"{_t('status_converting')} ({cur}/{tot})", cur, tot)
                        ),
                        cover_page=self._cover_page
                    )
                else:
                    module.convert_pdf_to_epub(
                        input_pdf=self._pdf_path,
                        output_epub=out,
                        crop_rects=crop_rects,
                        logger=log,
                    )
                log.info("Conversion complete: %s", out)
                self.after(0, _on_convert_done, True, _t("msg_done_path", path=out))
            except Exception as exc:
                msg = str(exc)
                log.exception("Conversion failed: %s", msg)
                self.after(0, _on_convert_done, False, msg)

        threading.Thread(target=worker, daemon=True).start()


# ── 진입점 ────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("main() 호출")
    app = App()
    app.mainloop()
    log.info("mainloop 종료")


if __name__ == "__main__":
    main()
