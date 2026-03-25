#!/usr/bin/env bash
# pdf2epub GUI 실행 스크립트
# 실행 전 필요한 패키지를 자동으로 설치한다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Python 탐색 ────────────────────────────────────────────────────────────────
# 환경변수 PYTHON 으로 인터프리터를 지정할 수 있다.
# 예) PYTHON=python3.12 ./run.sh
if [[ -z "${PYTHON:-}" ]]; then
    for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
        if command -v "$candidate" &>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    done
fi

if [[ -z "${PYTHON:-}" ]]; then
    echo "오류: Python 인터프리터를 찾을 수 없습니다." >&2
    exit 1
fi

echo "Python: $($PYTHON --version)"

# ── 패키지 설치 헬퍼 ───────────────────────────────────────────────────────────
install_requirements() {
    local req_file="$1"
    if [[ ! -f "$req_file" ]]; then
        return
    fi
    echo "패키지 확인 중: $(basename "$req_file") ..."
    "$PYTHON" -m pip install -q -r "$req_file" --break-system-packages 2>/dev/null \
        || "$PYTHON" -m pip install -q -r "$req_file"
}

# ── 필수 패키지 설치 ───────────────────────────────────────────────────────────
install_requirements "$SCRIPT_DIR/requirements.txt"

# ── 텍스트 모드 패키지 (선택) ──────────────────────────────────────────────────
if "$PYTHON" -c "import marker" &>/dev/null 2>&1; then
    : # 이미 설치됨
else
    echo ""
    echo "텍스트 추출 모드(marker-pdf)가 설치되어 있지 않습니다."
    read -r -p "지금 설치하시겠습니까? [y/N] " answer
    if [[ "${answer,,}" == "y" ]]; then
        install_requirements "$SCRIPT_DIR/requirements-text-mode.txt"
    else
        echo "텍스트 모드 없이 실행합니다. (이미지 모드만 사용 가능)"
    fi
fi

echo ""
echo "GUI 실행 중..."
exec "$PYTHON" "$SCRIPT_DIR/gui.py"
