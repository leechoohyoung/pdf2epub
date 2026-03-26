#!/opt/homebrew/bin/python3

from __future__ import annotations

import argparse
import fitz
import html
import logging
import re
import shutil
import subprocess
import tempfile
import traceback
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path


REQUIRED_COMMANDS = ("pdfinfo",)


@dataclass(frozen=True)
class PageAsset:
    index: int
    image_path: Path
    width: int
    height: int
    spine_title: str


def configure_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"pdf2epub.{log_path}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger


def require_commands(commands: tuple[str, ...]) -> None:
    missing = [command for command in commands if shutil.which(command) is None]
    if missing:
        raise SystemExit(f"Missing required command(s): {', '.join(missing)}")


def run_command(args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        capture_output=True,
    )


def get_content_bbox(page: fitz.Page) -> fitz.Rect:
    rects = []
    for block in page.get_text("dict")["blocks"]:
        rects.append(fitz.Rect(block["bbox"]))
    for drawing in page.get_drawings():
        rects.append(drawing["rect"])
    if not rects:
        return page.rect
    bbox = rects[0]
    for r in rects[1:]:
        bbox |= r
    return bbox & page.rect


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


def parse_pdf_page_count(pdf_path: Path) -> int:
    result = run_command(["pdfinfo", str(pdf_path)])
    match = re.search(r"^Pages:\s+(\d+)$", result.stdout, flags=re.MULTILINE)
    if not match:
        raise ValueError("Unable to determine page count from pdfinfo output")
    return int(match.group(1))


def extract_pdfinfo_value(pdfinfo_text: str, key: str) -> str:
    prefix = f"{key}:"
    for line in pdfinfo_text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def parse_pdf_metadata(pdf_path: Path) -> tuple[str, str]:
    result = run_command(["pdfinfo", str(pdf_path)])
    title = extract_pdfinfo_value(result.stdout, "Title")
    author = extract_pdfinfo_value(result.stdout, "Author")
    return title, author



def _markdown_to_html_body(md_text: str) -> str:
    """마크다운을 HTML body 내용으로 변환한다."""
    import re as _re
    
    def _sanitize_filename(filename: str) -> str:
        # 파일명에서 공백 및 위험한 문자를 언더스코어로 변경
        return _re.sub(r'[\s/\\\:\*\?\"\<\>\|]', '_', filename)

    # marker 가 내보내는 이미지 경로를 EPUB 구조에 맞게 수정
    # 1. 마크다운: ![alt](filename) -> ![alt](../images/safe_filename)
    def _fix_md_img(match):
        alt = match.group(1)
        src = match.group(2).strip()
        if src.startswith(('http://', 'https://', 'data:')):
            return match.group(0)
        return f'![{alt}](../images/{_sanitize_filename(src)})'
    
    md_text = _re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _fix_md_img, md_text)
    
    # 2. HTML: <img src="filename"> -> <img src="../images/safe_filename">
    def _fix_html_img(match):
        prefix = match.group(1)
        src = match.group(2).strip()
        if src.startswith(('http://', 'https://', 'data:')):
            return match.group(0)
        return f'<img {prefix}src="../images/{_sanitize_filename(src)}"'

    md_text = _re.sub(r'<img\s+([^>]*?)src=["\']([^"\']+)["\']', _fix_html_img, md_text)

    # 테이블 셀 내 <br> → 공백
    md_text = _re.sub(r'<br\s*/?>', ' ', md_text, flags=_re.IGNORECASE)

    # 마스킹(Redaction)으로 인해 부자연스럽게 끊어진 문장 이어주기 (한국어/영어 휴리스틱)
    # 단, 마크다운 문법(제목, 목록, 인용구, 표 등)을 해치지 않도록 주의
    def _join_broken_lines(text: str) -> str:
        lines = text.split('\n')
        joined_lines = []
        for i, line in enumerate(lines):
            stripped = line.rstrip()
            if not stripped:
                joined_lines.append('')
                continue
            
            # 다음 줄이 있고, 현재 줄이 마크다운 특수 기호나 마침표로 끝나지 않으며,
            # 다음 줄도 일반 텍스트로 시작하는 경우 문장 이어주기 시도
            is_normal_text_end = not _re.search(r'[.?!:;]$', stripped) and not stripped.endswith('|')
            is_not_md_block = not _re.match(r'^(#|\*|-|>|\d+\.|\||```)', line.lstrip())
            
            if i + 1 < len(lines):
                next_line = lines[i+1].lstrip()
                next_is_normal = next_line and not _re.match(r'^(#|\*|-|>|\d+\.|\||```)', next_line)
                
                if is_normal_text_end and is_not_md_block and next_is_normal:
                    # 한국어의 경우 띄어쓰기 없이 붙이거나 공백 하나로 붙임
                    # 끝 글자가 한글이고 다음 첫 글자도 한글이면 띄어쓰기로 연결
                    joined_lines.append(stripped + ' ')
                    continue
            
            joined_lines.append(line)
        
        # ' \n' 형태로 임시 연결된 줄들을 완전히 합침
        return ''.join(joined_lines).replace(' \n', ' ').replace('\n\n', '\n\n\n').replace('\n\n\n\n', '\n\n')

    md_text = _join_broken_lines(md_text)

    try:
        import markdown2  # type: ignore[import]
        # 표, 코드블록, 각주 등 지원 강화
        return markdown2.markdown(md_text, extras=[
            "tables", "fenced-code-blocks", "footnotes", "break-on-newline", "header-ids"
        ])
    except ImportError:
        pass
    try:
        import markdown as md_lib  # type: ignore[import]
        return md_lib.markdown(md_text, extensions=["extra"])
    except ImportError:
        pass

    # fallback: 기본 변환
    lines = md_text.splitlines()
    html_parts: list[str] = []
    para: list[str] = []

    def flush_para() -> None:
        if para:
            html_parts.append(f"<p>{html.escape(' '.join(para))}</p>")
            para.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_para()
        elif stripped.startswith("### "):
            flush_para()
            html_parts.append(f"<h3>{html.escape(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            flush_para()
            html_parts.append(f"<h2>{html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            flush_para()
            html_parts.append(f"<h1>{html.escape(stripped[2:])}</h1>")
        else:
            para.append(stripped)

    flush_para()
    return "\n".join(html_parts)


def build_chapter_xhtml(page_number: int, title: str, html_body: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="ko">
<head>
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="../styles/reflowable.css"/>
</head>
<body>
{html_body}
</body>
</html>
"""


def build_reflowable_opf(
    identifier: str,
    title: str,
    author: str,
    language: str,
    page_count: int,
    image_names: list[str] | None = None,
) -> str:
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="css" href="styles/reflowable.css" media-type="text/css"/>',
    ]
    spine_items: list[str] = []
    for i in range(1, page_count + 1):
        pid = f"page-{i:04d}"
        manifest_items.append(
            f'<item id="{pid}" href="pages/{pid}.xhtml" media-type="application/xhtml+xml"/>'
        )
        spine_items.append(f'<itemref idref="{pid}"/>')

    if image_names:
        for idx, img_name in enumerate(image_names):
            ext = img_name.split('.')[-1].lower()
            media_type = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
            manifest_items.append(
                f'<item id="img-{idx:04d}" href="images/{img_name}" media-type="{media_type}"/>'
            )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{identifier}</dc:identifier>
    <dc:title>{html.escape(title)}</dc:title>
    <dc:language>{html.escape(language)}</dc:language>
    <dc:creator>{html.escape(author or 'Unknown')}</dc:creator>
    <meta property="dcterms:modified">2026-03-25T00:00:00Z</meta>
  </metadata>
  <manifest>
    {''.join(manifest_items)}
  </manifest>
  <spine>
    {''.join(spine_items)}
  </spine>
</package>
"""


def write_reflowable_epub(
    *,
    output_path: Path,
    title: str,
    author: str,
    language: str,
    pages_md: list[str],
    images: dict[str, any] | None = None,
) -> None:
    identifier = f"urn:uuid:{uuid.uuid4()}"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    css = """body { font-family: serif; line-height: 1.6; margin: 0.5em 1em; color: #333; }
h1, h2, h3, h4 { color: #111; margin-top: 1.2em; margin-bottom: 0.5em; line-height: 1.2; }
p { margin: 0.6em 0; text-align: justify; word-break: break-all; }
img { max-width: 100%; height: auto; display: block; margin: 1em auto; border-radius: 4px; }
table { width: 100%; border-collapse: collapse; margin: 1em 0; font-size: 0.9em; table-layout: auto; }
th, td { border: 1px solid #ccc; padding: 6px 8px; text-align: left; word-break: break-all; }
th { background-color: #f5f5f5; font-weight: bold; }
pre, code { font-family: monospace; background-color: #f8f8f8; padding: 2px 4px; border-radius: 3px; }
pre { padding: 10px; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; }
blockquote { border-left: 4px solid #ddd; padding-left: 1em; color: #666; font-style: italic; }
"""
    # 이미지 파일명 리스트 구성 및 실제 저장 준비
    image_save_tasks: list[tuple[str, any]] = []
    image_names: list[str] = []
    if images:
        import re as _re
        for key, img_data in images.items():
            # _markdown_to_html_body 의 _sanitize_filename 과 동일한 규칙 적용
            img_name = _re.sub(r'[\s/\\\:\*\?\"\<\>\|]', '_', key)
            image_names.append(img_name)
            image_save_tasks.append((img_name, img_data))

    opf = build_reflowable_opf(identifier, title, author, language, len(pages_md), image_names)
    nav_xhtml = build_nav_document(title)

    with zipfile.ZipFile(output_path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        epub.writestr("OEBPS/styles/reflowable.css", css)
        epub.writestr("OEBPS/nav.xhtml", nav_xhtml)
        epub.writestr("OEBPS/content.opf", opf)

        # 이미지 저장
        if image_save_tasks:
            import io
            from PIL import Image
            for img_name, img_data in image_save_tasks:
                img_bytes = io.BytesIO()
                if hasattr(img_data, "save"): # PIL Image
                    ext = img_name.split('.')[-1].lower()
                    img_format = "JPEG" if ext in ("jpg", "jpeg") else "PNG"
                    # RGB 모드로 변환 (JPEG 저장 시 투명도 오류 방지)
                    if img_format == "JPEG" and img_data.mode in ("RGBA", "P"):
                        img_data = img_data.convert("RGB")
                    img_data.save(img_bytes, format=img_format)
                else:
                    img_bytes.write(img_data)
                epub.writestr(f"OEBPS/images/{img_name}", img_bytes.getvalue())

        for i, md_text in enumerate(pages_md):
            page_number = i + 1
            page_id = f"page-{page_number:04d}"
            spine_title = f"{title} - Page {page_number}"
            html_body = _markdown_to_html_body(md_text)
            
            # marker가 마크다운 본문에 이미지 태그를 누락시킨 경우를 대비하여
            # 현재 페이지 번호(p{N}_)가 포함된 이미지들을 찾아 하단에 렌더링
            import re as _re
            page_images_html = []
            prefix = f"p{page_number}_"
            if image_names:
                for img_name in image_names:
                    if img_name.startswith(prefix):
                        # 이미 본문에 삽입된 이미지가 아닐 경우에만 추가
                        if f'src="../images/{img_name}"' not in html_body:
                            page_images_html.append(
                                f'<figure style="text-align: center; margin: 1.5em 0;">\n'
                                f'  <img src="../images/{img_name}" alt="Page {page_number} Image" style="max-width: 100%; height: auto; border-radius: 4px;"/>\n'
                                f'</figure>'
                            )
            
            if page_images_html:
                html_body += "\n" + "\n".join(page_images_html)

            epub.writestr(
                f"OEBPS/pages/{page_id}.xhtml",
                build_chapter_xhtml(page_number, spine_title, html_body),
            )


def convert_pdf_to_epub_text_mode(
    input_pdf: Path,
    output_epub: Path,
    *,
    language: str = "ko",
    logger: logging.Logger | None = None,
    crop_rects: dict[int, tuple[float, float, float, float] | None] | None = None,
    progress_callback: any | None = None,
) -> None:
    """marker 를 사용해 페이지별로 개별 변환하여 리플로우 EPUB 을 생성한다."""
    from marker_extractor import load_models, extract_pages_markdown  # type: ignore[import]

    if not input_pdf.exists():
        raise SystemExit(f"Input PDF not found: {input_pdf}")

    pdf_title, pdf_author = parse_pdf_metadata(input_pdf)
    title = pdf_title or input_pdf.stem
    author = pdf_author or "Unknown"

    if logger:
        logger.info("텍스트 모드 개별 변환 시작: %s → %s", input_pdf, output_epub)

    models = load_models()
    pages_md, images = extract_pages_markdown(
        input_pdf, models, crop_rects=crop_rects,
        progress_callback=progress_callback
    )

    if logger:
        logger.info("%d 페이지 개별 변환 완료 (%d 이미지), EPUB 빌드 중...", len(pages_md), len(images))

    write_reflowable_epub(
        output_path=output_epub,
        title=title,
        author=author,
        language=language,
        pages_md=pages_md,
        images=images,
    )

    if logger:
        logger.info("텍스트 모드 변환 완료: %s", output_epub)


def build_nav_document(title: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ko">
<head>
  <title>{html.escape(title)}</title>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <ol/>
  </nav>
</body>
</html>
"""


def build_page_xhtml(page: PageAsset) -> str:
    image_name = page.image_path.name
    viewport = f"width={page.width},height={page.height}"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="ko">
<head>
  <title>{html.escape(page.spine_title)}</title>
  <meta name="viewport" content="{viewport}"/>
  <link rel="stylesheet" type="text/css" href="../styles/fixed.css"/>
</head>
<body>
  <div class="page" style="width:{page.width}px;height:{page.height}px;">
    <img src="../images/{html.escape(image_name)}" alt="{html.escape(page.spine_title)}"/>
  </div>
</body>
</html>
"""


def build_opf_document(identifier: str, title: str, author: str, language: str, pages: list[PageAsset]) -> str:
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="css" href="styles/fixed.css" media-type="text/css"/>',
    ]
    spine_items: list[str] = []

    for page in pages:
        page_id = f"page-{page.index:04d}"
        image_id = f"image-{page.index:04d}"
        is_cover = page.index == pages[0].index
        cover_image_prop = ' properties="cover-image"' if is_cover else ""
        manifest_items.append(
            f'<item id="{page_id}" href="pages/{page_id}.xhtml" media-type="application/xhtml+xml"/>'
        )
        manifest_items.append(
            f'<item id="{image_id}" href="images/{page.image_path.name}" media-type="image/png"{cover_image_prop}/>'
        )
        spine_items.append(f'<itemref idref="{page_id}"/>')

    metadata_author = html.escape(author or "Unknown")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{identifier}</dc:identifier>
    <dc:title>{html.escape(title)}</dc:title>
    <dc:language>{html.escape(language)}</dc:language>
    <dc:creator>{metadata_author}</dc:creator>
    <meta property="dcterms:modified">2026-03-23T00:00:00Z</meta>
    <meta name="cover" content="image-{pages[0].index:04d}"/>
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:orientation">auto</meta>
    <meta property="rendition:spread">none</meta>
  </metadata>
  <manifest>
    {''.join(manifest_items)}
  </manifest>
  <spine>
    {''.join(spine_items)}
  </spine>
</package>
"""


def write_fixed_layout_epub(
    *,
    output_path: Path,
    title: str,
    author: str,
    language: str,
    pages: list[PageAsset],
) -> None:
    identifier = f"urn:uuid:{uuid.uuid4()}"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fixed_css = """html, body { margin: 0; padding: 0; }
body { background: #fff; }
.page { position: relative; }
img { display: block; width: 100%; height: 100%; }
"""

    opf = build_opf_document(identifier, title, author, language, pages)
    nav_xhtml = build_nav_document(title)

    with zipfile.ZipFile(output_path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        epub.writestr("OEBPS/styles/fixed.css", fixed_css)
        epub.writestr("OEBPS/nav.xhtml", nav_xhtml)
        epub.writestr("OEBPS/content.opf", opf)

        for page in pages:
            page_id = f"page-{page.index:04d}"
            epub.writestr(f"OEBPS/pages/{page_id}.xhtml", build_page_xhtml(page))
            epub.write(page.image_path, arcname=f"OEBPS/images/{page.image_path.name}")


def convert_pdf_to_epub(
    input_pdf: Path,
    output_epub: Path,
    *,
    dpi: int = 150,
    language: str = "ko",
    keep_temp: bool = False,
    logger: logging.Logger | None = None,
    crop_rects: dict[int, tuple[float, float, float, float] | None] | None = None,
) -> None:
    require_commands(REQUIRED_COMMANDS)

    if not input_pdf.exists():
        raise SystemExit(f"Input PDF not found: {input_pdf}")
    if input_pdf.suffix.lower() != ".pdf":
        raise SystemExit(f"Input file is not a PDF: {input_pdf}")

    page_count = parse_pdf_page_count(input_pdf)
    pdf_title, pdf_author = parse_pdf_metadata(input_pdf)
    title = pdf_title or input_pdf.stem
    author = pdf_author or "Unknown"

    if logger is not None:
        logger.info("Starting conversion.")
        logger.info("Input PDF: %s", input_pdf)
        logger.info("Output EPUB: %s", output_epub)
        logger.info("Pages: %s", page_count)
        logger.info("DPI=%s keep_temp=%s", dpi, keep_temp)

    temp_dir_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="pdf2epub-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        try:
            image_dir = temp_dir_path / "images"
            image_dir.mkdir(parents=True, exist_ok=True)

            if logger is not None:
                logger.info("Working directory: %s", temp_dir_path)

            pages: list[PageAsset] = []

            for page_number in range(1, page_count + 1):
                png_path = image_dir / f"page-{page_number:04d}.png"

                try:
                    explicit_crop = crop_rects.get(page_number) if crop_rects else None
                    width, height = render_page_to_png(
                        input_pdf, page_number, dpi, png_path,
                        crop_rect=explicit_crop,
                    )
                except Exception:
                    if logger is not None:
                        logger.exception("Failed while processing page %s/%s", page_number, page_count)
                    raise

                pages.append(
                    PageAsset(
                        index=page_number,
                        image_path=png_path,
                        width=width,
                        height=height,
                        spine_title=f"{title} - Page {page_number}",
                    )
                )

                if logger is not None:
                    logger.info("Page %s/%s | output=%sx%s", page_number, page_count, width, height)

            if logger is not None:
                logger.info("Writing EPUB package with %s pages.", len(pages))

            write_fixed_layout_epub(
                output_path=output_epub,
                title=title,
                author=author,
                language=language,
                pages=pages,
            )

            if keep_temp and temp_dir_path is not None:
                preserved_dir = output_epub.parent / f"{output_epub.stem}-work"
                if preserved_dir.exists():
                    shutil.rmtree(preserved_dir)
                shutil.copytree(temp_dir_path, preserved_dir)
                if logger is not None:
                    logger.info("Preserved intermediate files at %s", preserved_dir)

            if logger is not None:
                logger.info("Conversion finished successfully.")
        except Exception:
            if temp_dir_path is not None:
                failed_dir = output_epub.parent / f"{output_epub.stem}-failed-work"
                if failed_dir.exists():
                    shutil.rmtree(failed_dir)
                shutil.copytree(temp_dir_path, failed_dir)
                if logger is not None:
                    logger.error("Preserved failed intermediate files at %s", failed_dir)
            raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a PDF to a fixed-layout EPUB."
    )
    parser.add_argument("input_pdf", type=Path, help="Path to the input PDF file")
    parser.add_argument(
        "-o",
        "--output",
        dest="output_epub",
        type=Path,
        help="Path to the output EPUB file",
    )
    parser.add_argument("--dpi", type=int, default=150, help="Rasterization DPI (default: 150)")
    parser.add_argument("--language", default="ko", help="EPUB language code (default: ko)")
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Path to a log file. Defaults to <output>.log",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep intermediate render files next to the output EPUB",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    input_pdf = args.input_pdf.expanduser().resolve()
    output_epub = args.output_epub.expanduser().resolve() if args.output_epub else input_pdf.with_suffix(".epub")
    log_file = args.log_file.expanduser().resolve() if args.log_file else output_epub.with_suffix(".log")
    logger = configure_logging(log_file)

    logger.info("Log file: %s", log_file)

    try:
        convert_pdf_to_epub(
            input_pdf=input_pdf,
            output_epub=output_epub,
            dpi=args.dpi,
            language=args.language,
            keep_temp=args.keep_temp,
            logger=logger,
        )
    except BaseException as error:
        if isinstance(error, SystemExit) and error.code in (0, None):
            raise
        logger.error("Conversion failed: %s", error)
        logger.error(traceback.format_exc())
        raise SystemExit(1) from error

    print(output_epub)
    print(log_file)


if __name__ == "__main__":
    main()
