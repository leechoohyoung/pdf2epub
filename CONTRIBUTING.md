# Contributing to PDF2EPUB

[한국어 가이드는 아래를 참고하세요.](#한국어)

First off, thank you for considering contributing to **PDF2EPUB**! It's people like you that make open-source tools great. Whether you're fixing a bug, adding a new feature, or improving documentation, your help is always appreciated.

This document serves as a set of guidelines for contributing to this project.

## 🤝 How Can I Contribute?

### 1. Reporting Bugs
If you find a bug in the tool, please open an issue in the repository. When creating an issue, please include:
*   Your operating system and Python version.
*   Steps to reproduce the bug.
*   Expected behavior vs. actual behavior.
*   Error logs (if any). You can enable the "Live Log Panel" in the GUI to see detailed errors.

### 2. Suggesting Enhancements
Have an idea for a new feature or an improvement? We'd love to hear it! Please open an issue to discuss your idea before starting to write code. This ensures your time is well spent and aligns with the project's goals.

### 3. Submitting Pull Requests (PR)
If you're ready to submit code, please follow these steps:
1.  **Fork the repository** and create your branch from `main`.
2.  **Write clear, concise commit messages.**
3.  **Ensure your code follows the existing style.** (We use standard Python formatting, `flake8` / `black` are recommended).
4.  **Test your changes.** If you've added new functionality, make sure it works across different PDF files.
5.  **Open a Pull Request.** Describe your changes in detail, linking to any relevant issues.

## 🛠 Development Environment Setup

1.  Clone your fork:
    ```bash
    git clone https://github.com/your-username/pdf2epub.git
    cd pdf2epub
    ```
2.  Create a virtual environment (recommended):
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Run the application:
    ```bash
    python3 gui.py
    ```

## 🌐 Adding Translations (i18n)
PDF2EPUB supports multiple languages via the `i18n.py` file. If you want to add a new language:
1. Open `i18n.py`.
2. Add your language code (e.g., `"es"` for Spanish) to the `_MESSAGES` dictionary.
3. Translate all existing key-value pairs.
4. Update the language selection menu in `gui.py` (`_build_menu` and `_change_language`).

---

<a name="한국어"></a>

# PDF2EPUB 기여 가이드

**PDF2EPUB** 프로젝트에 기여해 주셔서 진심으로 감사드립니다! 버그 수정, 새로운 기능 추가, 문서 개선 등 여러분의 모든 기여가 오픈소스 생태계를 발전시키는 데 큰 힘이 됩니다.

본 문서는 프로젝트 기여를 위한 기본 가이드라인을 제공합니다.

## 🤝 어떻게 기여할 수 있나요?

### 1. 버그 제보 (Reporting Bugs)
도구 사용 중 버그를 발견하셨다면, 저장소에 이슈(Issue)를 등록해 주세요. 이슈를 작성할 때는 다음 정보를 포함해 주시면 해결에 큰 도움이 됩니다:
*   운영체제 및 파이썬 버전
*   버그 발생 단계 (재현 방법)
*   기대했던 결과와 실제 결과의 차이
*   에러 로그 (GUI 상단 메뉴의 '실시간 로그 보기'를 통해 상세 로그를 확인할 수 있습니다)

### 2. 기능 제안 (Suggesting Enhancements)
새로운 기능이나 개선 아이디어가 있으신가요? 코드를 작성하기 전에 이슈를 먼저 열어 아이디어를 공유하고 논의해 주세요. 프로젝트의 방향성과 일치하는지 확인하여 소중한 시간을 아낄 수 있습니다.

### 3. 풀 리퀘스트 (PR) 제출
코드를 수정하고 제출할 준비가 되었다면 다음 절차를 따라주세요:
1.  **저장소를 포크(Fork)** 하고 `main` 브랜치에서 새로운 브랜치를 생성합니다.
2.  **명확하고 간결한 커밋 메시지**를 작성합니다.
3.  **기존 코드 스타일을 준수합니다.** (표준 파이썬 포맷을 따르며, `flake8`이나 `black` 사용을 권장합니다).
4.  **변경 사항을 테스트합니다.** 새로운 기능을 추가했다면, 다양한 PDF 파일에서도 정상 동작하는지 확인해 주세요.
5.  **Pull Request를 생성합니다.** 변경 사항을 상세히 설명하고, 관련된 이슈가 있다면 링크를 걸어주세요.

## 🛠 개발 환경 구축

1.  포크한 저장소를 클론합니다:
    ```bash
    git clone https://github.com/your-username/pdf2epub.git
    cd pdf2epub
    ```
2.  가상 환경 생성을 권장합니다:
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # Windows의 경우 `venv\Scripts\activate`
    ```
3.  의존성 패키지를 설치합니다:
    ```bash
    pip install -r requirements.txt
    ```
4.  애플리케이션을 실행합니다:
    ```bash
    python3 gui.py
    ```

## 🌐 다국어 번역 추가 (i18n)
PDF2EPUB은 `i18n.py` 파일을 통해 다국어를 지원합니다. 새로운 언어를 추가하고 싶으시다면:
1. `i18n.py` 파일을 엽니다.
2. `_MESSAGES` 딕셔너리에 새로운 언어 코드(예: `"ja"` 일본어)를 추가합니다.
3. 기존의 모든 키-값 쌍을 번역하여 채워 넣습니다.
4. `gui.py`의 언어 선택 메뉴(`_build_menu` 및 `_change_language`)에 새 언어를 등록합니다.
