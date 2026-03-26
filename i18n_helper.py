import re
from pathlib import Path

def apply_i18n(file_path):
    content = Path(file_path).read_text(encoding='utf-8')
    
    # 치환 규칙 (정규식: 한글 문자열 -> _t("키"))
    replacements = [
        # 1. 간단한 버튼/레이블 텍스트
        (r'text="이전 페이지"', 'text=_t("btn_prev")'), # 주의: i18n.py에 추가 필요
        (r'text="다음 페이지"', 'text=_t("btn_next")'),
        (r'text="Convert"', 'text=_t("btn_convert")'),
        (r'text="Cancel"', 'text=_t("btn_cancel")'),
        (r'text="준비"', 'text=_t("status_ready")'),
        
        # 2. 상태바 및 로그 메시지 (포맷팅 포함)
        (r'log\.debug\("상태: %s \(value=%d, max=%d, indeterminate=%s\)",\s*msg, value, maximum, indeterminate\)', 
         'log.debug("Status: %s (value=%d, max=%d, indeterminate=%s)", msg, value, maximum, indeterminate)'),
        (r'self\._status_label\.config\(text=msg\)', 'self._status_label.config(text=msg)'),
        
        # 3. 팝업 메시지
        (r'messagebox\.showwarning\("변환 영역 미설정",\s*"변환 영역을 드래그로 지정하거나 기본값을 설정해주세요\."\)',
         'messagebox.showwarning(_t("label_not_set"), _t("msg_no_area"))'),
        (r'messagebox\.showinfo\("완료",\s*f"변환이 완료됐습니다:\\n{out}"\)',
         'messagebox.showinfo(_t("msg_done"), _t("msg_done_path", path=out))'),
        (r'messagebox\.showerror\("변환 실패",\s*msg\)',
         'messagebox.showerror(_t("msg_fail"), msg)'),
    ]

    # i18n.py에 부족한 키들 추가 (사전에 정의되지 않은 것들)
    # 실제로는 i18n.py 를 직접 수정하는 것이 좋으므로 여기서는 핵심 로직만 변경

    new_content = content
    # Import 추가 확인
    if 'from i18n import _t' not in new_content:
        new_content = "from i18n import _t\n" + new_content

    # 한글 문자열들을 _t() 로 교체 (수동으로 확인하며 진행하는 것이 안전함)
    # 여기서는 예시로 몇 가지만 처리하고, 나머지는 i18n.py 의 키에 맞춰 gui.py 를 직접 재작성함
    
    # (코드 양이 많으므로 gui.py를 통째로 i18n이 적용된 버전으로 다시 쓰는 것이 가장 확실함)
    pass

# 다국어용 키 추가 (i18n.py 업데이트)
def update_i18n_keys():
    path = Path("i18n.py")
    content = path.read_text(encoding='utf-8')
    if '"btn_prev"' not in content:
        # 여기에 필요한 키들을 더 추가함
        pass

if __name__ == "__main__":
    # 이 방식 대신, i18n 이 완벽히 적용된 gui.py 를 직접 생성하여 덮어쓰겠습니다.
    pass
