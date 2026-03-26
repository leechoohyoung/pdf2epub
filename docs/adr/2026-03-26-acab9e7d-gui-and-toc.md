# ADR: PDF to EPUB GUI Enhancements and TOC Generation (GUI 개선 및 목차 생성)

**Date:** 2026-03-26
**Status:** Accepted

## Context (배경)

1.  **GUI File Title (GUI 파일명 표시)**: 현재 애플리케이션은 불러온 PDF 파일의 이름을 명확하게 표시하지 않아, 어떤 파일을 작업 중인지 알기 어렵습니다.
2.  **Text Extraction Mode Default (텍스트 추출 모드 기본값)**: "텍스트 추출 모드(실험적)" 기능이 현재 기본적으로 비활성화되어 있습니다. 사용자 피드백에 따라 이 모드를 기본 워크플로우로 설정해야 합니다.
3.  **Missing Table of Contents (목차 누락)**: 생성된 EPUB 파일에 기능적인 목차(Table of Contents)가 없어 탐색이 불가능합니다 (`nav.xhtml`에 빈 `<ol/>`만 존재).

### The TOC Challenge (목차 생성의 기술적 문제점)
목차를 생성하는 데 있어 중요한 기술적 문제가 있습니다:
*   사용자는 페이지별로 여백을 잘라내는(크롭) 영역을 설정할 수 있습니다.
*   "텍스트 추출 모드"에서는 잘라낸 PDF 페이지를 `marker-pdf`로 처리하여 마크다운을 생성합니다.
*   이러한 자르기 및 텍스트 추출 과정 때문에, 결과물인 EPUB의 논리적 구조와 페이지 번호가 원본 PDF의 내부 목차(Outline)와 크게 달라지는 경우가 많습니다. 원본 PDF 목차를 새 EPUB 구조에 매핑하는 것은 신뢰할 수 없고 복잡합니다.

## Decisions (결정 사항)

### 1. GUI: Display Loaded File Title (불러온 파일 제목 표시)
*   GUI 상단(크롭 툴바 위 또는 상단 상태 영역)에 현재 불러온 PDF의 파일명을 명시적으로 표시하는 레이블을 추가합니다.
*   애플리케이션 타이틀 바(`self.title`)는 앱 이름으로 유지하되, 내부 UI에서 현재 작업 중인 파일 컨텍스트를 보여줍니다.

### 2. GUI: Enable Text Mode by Default (텍스트 모드 기본 활성화)
*   `gui.py`의 `_var_text_mode` 부울 변수를 `False` 대신 `True`로 초기화합니다.

### 3. EPUB: Context-Aware TOC Generation (컨텍스트 기반 목차 생성)
원본 PDF의 내부 구조에 의존하는 대신, 변환 과정에서 생성된 **실제 결과물**을 기반으로 목차를 생성합니다.

#### 3a. Text Extraction Mode (Reflowable EPUB - 텍스트 추출 모드)
*   **Strategy (전략)**: 각 페이지에 대해 `marker-pdf`가 생성한 마크다운 출력을 파싱합니다.
*   **Implementation (구현)**:
    *   `pages_md` 리스트(각 변환된 페이지의 마크다운 문자열 포함)를 순회합니다.
    *   정규 표현식을 사용하여 마크다운 헤딩(예: `# 제목 1`, `## 제목 2`)을 찾습니다.
    *   헤딩 레벨, 텍스트를 추출하고 해당 대상 페이지 ID(예: `page-0001.xhtml`)와 연결합니다.
    *   헤딩 레벨을 기반으로 `nav.xhtml` 문서에 계층적인 HTML 목록(`<ol>`, `<li>`, `<a>`)을 구성합니다.
*   **Fallback (대안)**: 전체 문서에서 헤딩을 찾을 수 없는 경우, 고정 레이아웃 모드처럼 페이지의 평면적인 목록을 생성하는 것으로 대체합니다.

#### 3b. Fixed-Layout Mode (Image-based EPUB - 고정 레이아웃 모드)
*   **Strategy (전략)**: 생성된 각 페이지를 나열하는 단순하고 평면적인 목차를 생성합니다.
*   **Implementation (구현)**:
    *   `pages` 리스트(`PageAsset` 객체 포함)를 순회합니다.
    *   각 항목이 해당 페이지에 대한 링크인 평면적인 HTML 목록을 만듭니다 (예: `<li><a href="pages/page-0001.xhtml">Page 1</a></li>`).

## Consequences (결과)

*   **Positive (장점)**: 사용자는 항상 어떤 파일이 열려 있는지 알 수 있습니다. 선호하는 텍스트 모드가 기본이 됩니다. 생성된 EPUB은 오래되거나 어긋난 원본 PDF 목차가 아닌, 실제 추출된 내용을 반영하는 기능적이고 정확한 탐색 기능을 갖추게 됩니다.
*   **Negative (단점)**: 텍스트 모드에서 원본 문서가 의미론적 헤딩(`# 제목`) 대신 스타일링(예: 굵은 텍스트)에 의존하는 경우, 목차가 빈약하거나 단순한 페이지 목록으로 대체될 수 있습니다. 그러나 이는 목차 생성 로직 자체의 문제가 아니라 원본 문서와 추출 모델의 한계입니다.
