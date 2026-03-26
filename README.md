# PDF2EPUB: Smart PDF to EPUB Converter

> **🤖 Built by AI Agent**
> This project was entirely developed, analyzed, and refactored by an AI agent (Gemini CLI) in collaboration with a human developer. It demonstrates the capability of AI in building complex GUI applications, handling PDF processing algorithms, and integrating machine learning models.

[한국어 설명은 아래를 참고하세요.](#한국어)

PDF2EPUB is a powerful, GUI-based conversion tool designed to transform PDF documents into highly readable EPUB files. It allows precise, page-by-page visual cropping and utilizes advanced AI models for high-quality text and layout extraction.

## ✨ Key Features

*   **Interactive Visual Cropping:** Easily drag to set crop areas for each page to exclude headers, footers, and page numbers.
*   **Batch Application:** Apply a defined crop area to all subsequent pages with a single click.
*   **Two Conversion Modes:**
    1.  **Fixed-Layout Mode:** Converts pages into high-quality images, preserving the exact original layout.
    2.  **Reflowable Text Mode (Experimental):** Uses the `marker-pdf` (Surya AI) model to intelligently extract text, tables, and images from the cropped area, generating a dynamic EPUB that adapts to any screen size.
*   **Smart Image Handling:** Automatically extracts images and places them accurately within the reflowable context.
*   **Cover Page Selection:** Choose any page from the PDF to set as the official EPUB cover image.
*   **Validation:** Automatically detects if your chosen crop areas cut off vital content.

## 🚀 Installation

1. Clone the repository.
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

## 📖 Usage

```bash
python3 gui.py
```

1.  **Open PDF:** Go to `File` -> `Open PDF...`
2.  **Set Crop Areas:** Drag your mouse to select the content area.
3.  **Apply to All:** Click `Apply to subsequent pages` to batch crop.
4.  **Set Cover:** Navigate to a page and click `Set current page as cover`.
5.  **Convert:** Select `Text Extraction Mode` in the `Options` menu for reflowable text, then click **Convert**.

---

<a name="한국어"></a>

# PDF2EPUB: 스마트 PDF to EPUB 변환기

> **🤖 AI 에이전트 개발 프로젝트**
> 이 프로젝트는 사람과 협력하여 기획, 설계, 디버깅부터 코드 구현 및 리팩토링까지 모든 과정을 AI 에이전트(Gemini CLI)가 주도하여 개발했습니다. 복잡한 GUI 구성, 알고리즘 분석, 머신러닝 연동 등 AI 코딩 에이전트의 가능성을 보여주는 오픈소스 도구입니다.

PDF2EPUB은 PDF 문서를 가독성이 높은 EPUB 파일로 변환해주는 강력한 GUI 도구입니다. 페이지별 시각적 자르기 기능을 통해 불필요한 여백을 제거하고, 최신 AI 모델을 사용하여 고품질의 텍스트 및 레이아웃을 추출합니다.

## ✨ 주요 특징

*   **대화형 시각적 자르기:** 마우스 드래그로 각 페이지의 자르기 영역을 설정하여 헤더, 푸터, 페이지 번호 등을 제외할 수 있습니다.
*   **일괄 적용:** 클릭 한 번으로 현재 설정한 영역을 이후 모든 페이지에 즉시 적용합니다.
*   **두 가지 변환 모드:**
    1.  **고정 레이아웃 모드:** 페이지를 고화질 이미지로 변환하여 원본 레이아웃을 완벽하게 보존합니다.
    2.  **리플로우 텍스트 모드 (실험적):** `marker-pdf` (Surya AI) 모델을 사용하여 잘라낸 영역에서 텍스트, 표, 이미지를 지능적으로 추출하여 모든 화면 크기에 최적화된 동적 EPUB을 생성합니다.
*   **스마트 이미지 처리:** 이미지를 자동으로 추출하여 텍스트 문맥에 맞게 정확히 배치합니다.
*   **표지 지정 기능:** PDF의 어떤 페이지든 공식 EPUB 표지로 지정할 수 있습니다.
*   **콘텐츠 잘림 검증:** 설정한 영역이 중요한 콘텐츠를 잘라내는지 자동으로 감지하여 경고합니다.

## 🚀 설치 방법

1. 저장소를 클론합니다.
2. 필수 패키지를 설치합니다:
   ```bash
   pip install -r requirements.txt
   ```

## 📖 사용 방법

```bash
python3 gui.py
```

1.  **PDF 열기:** `파일` -> `다른 PDF 열기...` 메뉴를 선택합니다.
2.  **영역 설정:** 마우스로 본문 영역을 드래그하여 선택합니다.
3.  **일괄 적용:** `이후 페이지에 적용` 버튼을 눌러 나머지 페이지도 한꺼번에 자릅니다.
4.  **표지 설정:** 원하는 페이지에서 `현재 페이지를 표지로 지정` 버튼을 누릅니다.
5.  **변환:** `옵션` 메뉴에서 `텍스트 추출 모드`를 선택(권장)하고 **Convert** 버튼을 누릅니다.

## 📄 License
[MIT License](LICENSE)
