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
