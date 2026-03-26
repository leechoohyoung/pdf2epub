# i18n.py
import locale
import sys

# 번역 데이터
_MESSAGES = {
    "en": {
        "app_title": "PDF to EPUB Converter",
        "menu_file": "File",
        "menu_open": "Open PDF...",
        "menu_exit": "Exit",
        "menu_options": "Options",
        "menu_text_mode": "Text Extraction Mode (Experimental)",
        "menu_show_log": "Live Log Panel",
        "menu_language": "Language",
        "lang_en": "English",
        "lang_ko": "Korean (한국어)",
        "guide_startup": "📂 Go to [File] → [Open PDF...] to select a PDF document.",
        "guide_drag": "💡 Drag your mouse to select the conversion area",
        "label_crop_area": "Conversion Area",
        "label_not_set": "Not Set",
        "label_page": "Page",
        "label_cover": "Cover",
        "btn_prev": "Previous Page",
        "btn_next": "Next Page",
        "btn_apply_subsequent": "Apply to subsequent pages",
        "btn_load_default": "Apply Default Area",
        "btn_set_cover": "Set current page as cover",
        "btn_convert": "Convert",
        "btn_cancel": "Cancel",
        "status_ready": "Ready",
        "status_opening": "Opening PDF...",
        "status_rendering": "Rendering page...",
        "status_thumbnails": "Generating thumbnails...",
        "status_validating": "Validating crop areas...",
        "status_converting": "Converting to EPUB...",
        "status_loading_models": "Loading marker models...",
        "msg_done": "Success",
        "msg_done_path": "Conversion complete:\n{path}",
        "msg_fail": "Conversion failed",
        "msg_no_area": "No area set. Please drag to select or apply default.",
        "dlg_clipped_title": "Content Cutoff Detected",
        "dlg_clipped_msg": "Content is cut off on page(s): {pages}.\nWould you like to adjust the area?\n\nEdit Area -> Go to the first problem page\nProceed   -> Convert with current settings",
        "dlg_guide_title": "Adjustment Guide",
        "dlg_guide_msg": "Moving to page {page}. Please adjust the area and click Convert again.",
        "log_start": "GUI Started. Log file: {path}",
        "log_open_pdf": "Opening PDF file dialog",
        "log_selected": "Selected file: {path}",
        "log_page_count": "Total pages: {count}",
        "log_convert_start": "Starting conversion: {input} -> {output} (Text mode: {mode})",
        "log_marker_start": "Marker extraction started: {path}",
    },
    "ko": {
        "app_title": "PDF to EPUB 변환기",
        "menu_file": "파일",
        "menu_open": "다른 PDF 열기...",
        "menu_exit": "종료",
        "menu_options": "옵션",
        "menu_text_mode": "텍스트 추출 모드 (실험적)",
        "menu_show_log": "실시간 로그 보기",
        "menu_language": "언어",
        "lang_en": "영어 (English)",
        "lang_ko": "한국어",
        "guide_startup": "📂 상단의 [파일] → [다른 PDF 열기...] 메뉴를 통해 변환할 PDF를 선택하세요.",
        "guide_drag": "💡 마우스로 드래그하여 변환할 영역을 지정하세요",
        "label_crop_area": "변환 영역",
        "label_not_set": "미설정",
        "label_page": "페이지",
        "label_cover": "표지",
        "btn_prev": "이전 페이지",
        "btn_next": "다음 페이지",
        "btn_apply_subsequent": "이후 페이지에 적용",
        "btn_load_default": "기본 영역 적용",
        "btn_set_cover": "현재 페이지를 표지로 지정",
        "btn_convert": "Convert",
        "btn_cancel": "Cancel",
        "status_ready": "준비",
        "status_opening": "PDF 열기 중...",
        "status_rendering": "페이지 렌더링 중...",
        "status_thumbnails": "썸네일 생성 중...",
        "status_validating": "크롭 영역 검증 중...",
        "status_converting": "EPUB 변환 중...",
        "status_loading_models": "marker 모델 로딩 중...",
        "msg_done": "완료",
        "msg_done_path": "변환이 완료됐습니다:\n{path}",
        "msg_fail": "변환 실패",
        "msg_no_area": "변환 영역을 드래그로 지정하거나 기본값을 설정해주세요.",
        "dlg_clipped_title": "콘텐츠 잘림 감지",
        "dlg_clipped_msg": "{pages} 페이지에서 지정된 영역 밖으로 콘텐츠가 잘립니다.\n영역을 수정하시겠습니까?\n\nEdit Area → 첫 번째 문제 페이지로 이동\nProceed   → 현재 설정으로 그대로 변환",
        "dlg_guide_title": "영역 조정 안내",
        "dlg_guide_msg": "페이지 {page}로 이동합니다. 영역을 조정한 뒤 Convert를 다시 눌러주세요.",
        "log_start": "GUI 시작. 로그 파일: {path}",
        "log_open_pdf": "PDF 파일 선택 대화상자 열기",
        "log_selected": "선택된 파일: {path}",
        "log_page_count": "페이지 수: {count}",
        "log_convert_start": "변환 시작: {input} -> {output} (텍스트 모드: {mode})",
        "log_marker_start": "marker 변환 시작: {path}",
    }
}

# 기본 언어 설정
_lang = "en"
try:
    # 시스템 언어 확인
    default_lang = locale.getdefaultlocale()[0]
    if default_lang and default_lang.startswith("ko"):
        _lang = "ko"
except Exception:
    pass

def set_language(lang: str):
    global _lang
    if lang in _MESSAGES:
        _lang = lang

def _t(key: str, **kwargs) -> str:
    """키에 해당하는 번역 문자열을 반환한다."""
    msg = _MESSAGES.get(_lang, _MESSAGES["en"]).get(key, key)
    if kwargs:
        return msg.format(**kwargs)
    return msg
