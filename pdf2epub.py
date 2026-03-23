#!/opt/homebrew/bin/python3

from __future__ import annotations

import argparse
import html
import logging
import math
import re
import shutil
import subprocess
import tempfile
import traceback
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path


REQUIRED_COMMANDS = ("pdftoppm", "pdfinfo", "sips")


@dataclass(frozen=True)
class CropBox:
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class TocEntry:
    label: str
    page_index: int


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


def read_token(handle) -> bytes:
    token = bytearray()
    while True:
        chunk = handle.read(1)
        if not chunk:
            return bytes(token)
        if chunk == b"#":
            handle.readline()
            continue
        if chunk.isspace():
            if token:
                return bytes(token)
            continue
        token.extend(chunk)
        break
    while True:
        chunk = handle.read(1)
        if not chunk or chunk.isspace():
            return bytes(token)
        token.extend(chunk)


def read_ppm_size(ppm_path: Path) -> tuple[int, int]:
    with ppm_path.open("rb") as handle:
        magic = read_token(handle)
        if magic != b"P6":
            raise ValueError(f"Unsupported PPM format: {magic!r}")
        width = int(read_token(handle))
        height = int(read_token(handle))
        max_value = int(read_token(handle))
        if max_value != 255:
            raise ValueError(f"Unsupported PPM max value: {max_value}")
    return width, height


def find_rendered_page_path(output_prefix: Path, page_number: int) -> Path:
    candidates = sorted(output_prefix.parent.glob(f"{output_prefix.name}-*.ppm"))
    preferred = [
        output_prefix.parent / f"{output_prefix.name}-{page_number}.ppm",
        output_prefix.parent / f"{output_prefix.name}-{page_number:02d}.ppm",
        output_prefix.parent / f"{output_prefix.name}-{page_number:03d}.ppm",
        output_prefix.parent / f"{output_prefix.name}-{page_number:04d}.ppm",
    ]

    for candidate in preferred:
        if candidate.exists():
            return candidate

    if len(candidates) == 1:
        return candidates[0]

    raise FileNotFoundError(f"Unable to locate rendered page for {output_prefix} page={page_number}")


def detect_crop_box_from_ppm(
    ppm_path: Path,
    *,
    white_threshold: int = 245,
    min_content_pixels: int | None = None,
    padding: int = 12,
) -> CropBox:
    with ppm_path.open("rb") as handle:
        magic = read_token(handle)
        if magic != b"P6":
            raise ValueError(f"Unsupported PPM format: {magic!r}")
        width = int(read_token(handle))
        height = int(read_token(handle))
        max_value = int(read_token(handle))
        if max_value != 255:
            raise ValueError(f"Unsupported PPM max value: {max_value}")
        data = handle.read()

    row_counts = [0] * height
    column_counts = [0] * width
    row_max_run_lengths = [0] * height
    column_run_coverage = [0] * width

    for y in range(height):
        row_start = y * width * 3
        count = 0
        run_start: int | None = None
        for x in range(width):
            offset = row_start + (x * 3)
            red = data[offset]
            green = data[offset + 1]
            blue = data[offset + 2]
            is_dark = red < white_threshold or green < white_threshold or blue < white_threshold
            if is_dark:
                count += 1
                column_counts[x] += 1
                if run_start is None:
                    run_start = x
            elif run_start is not None:
                run_length = x - run_start
                if run_length > row_max_run_lengths[y]:
                    row_max_run_lengths[y] = run_length
                if run_length >= 6:
                    for run_x in range(run_start, x):
                        column_run_coverage[run_x] += 1
                run_start = None
        row_counts[y] = count

        if run_start is not None:
            run_length = width - run_start
            if run_length > row_max_run_lengths[y]:
                row_max_run_lengths[y] = run_length
            if run_length >= 6:
                for run_x in range(run_start, width):
                    column_run_coverage[run_x] += 1

    if min_content_pixels is not None:
        row_threshold = min_content_pixels
        column_threshold = min_content_pixels
        top = next((index for index, count in enumerate(row_counts) if count >= row_threshold), None)
        bottom = next((index for index, count in reversed(list(enumerate(row_counts))) if count >= row_threshold), None)
        left = next((index for index, count in enumerate(column_counts) if count >= column_threshold), None)
        right = next((index for index, count in reversed(list(enumerate(column_counts))) if count >= column_threshold), None)
    else:
        def dense_boundary_start(features: list[int], threshold: int, window_size: int, required_hits: int) -> int | None:
            limit = len(features) - window_size + 1
            if limit < 1:
                return None
            for start_index in range(limit):
                window = features[start_index : start_index + window_size]
                hits = [offset for offset, value in enumerate(window) if value >= threshold]
                if len(hits) >= required_hits:
                    return start_index + hits[0]
            return None

        def dense_boundary_end(features: list[int], threshold: int, window_size: int, required_hits: int) -> int | None:
            limit = len(features) - window_size
            if limit < 0:
                return None
            for start_index in range(limit, -1, -1):
                window = features[start_index : start_index + window_size]
                hits = [offset for offset, value in enumerate(window) if value >= threshold]
                if len(hits) >= required_hits:
                    return start_index + hits[-1]
            return None

        def backtrack_start(features: list[int], start_index: int, sparse_threshold: int, gap_limit: int) -> int:
            boundary = start_index
            gap = 0
            for index in range(start_index, -1, -1):
                if features[index] >= sparse_threshold:
                    boundary = index
                    gap = 0
                else:
                    gap += 1
                    if gap >= gap_limit:
                        break
            return boundary

        def backtrack_end(features: list[int], end_index: int, sparse_threshold: int, gap_limit: int) -> int:
            boundary = end_index
            gap = 0
            for index in range(end_index, len(features)):
                if features[index] >= sparse_threshold:
                    boundary = index
                    gap = 0
                else:
                    gap += 1
                    if gap >= gap_limit:
                        break
            return boundary

        max_row_run = max(row_max_run_lengths) if row_max_run_lengths else 0
        max_column_coverage = max(column_run_coverage) if column_run_coverage else 0

        dense_row_threshold = max(10, int(max_row_run * 0.20))
        sparse_row_threshold = max(6, dense_row_threshold // 2)
        dense_column_threshold = max(3, int(max_column_coverage * 0.08))
        sparse_column_threshold = 1

        top_dense = dense_boundary_start(row_max_run_lengths, dense_row_threshold, window_size=6, required_hits=2)
        bottom_dense = dense_boundary_end(row_max_run_lengths, dense_row_threshold, window_size=6, required_hits=2)
        left_dense = dense_boundary_start(column_run_coverage, dense_column_threshold, window_size=8, required_hits=3)
        right_dense = dense_boundary_end(column_run_coverage, dense_column_threshold, window_size=8, required_hits=3)

        top = backtrack_start(row_max_run_lengths, top_dense, sparse_row_threshold, gap_limit=8) if top_dense is not None else None
        bottom = backtrack_end(row_max_run_lengths, bottom_dense, sparse_row_threshold, gap_limit=8) if bottom_dense is not None else None
        left = backtrack_start(column_counts, left_dense, sparse_column_threshold, gap_limit=12) if left_dense is not None else None
        right = backtrack_end(column_counts, right_dense, sparse_column_threshold, gap_limit=12) if right_dense is not None else None

        if top is None or bottom is None or left is None or right is None:
            max_row_count = max(row_counts) if row_counts else 0
            max_column_count = max(column_counts) if column_counts else 0
            row_threshold = max(24, int(max_row_count * 0.03))
            column_threshold = max(24, int(max_column_count * 0.03))
            top = next((index for index, count in enumerate(row_counts) if count >= row_threshold), None)
            bottom = next((index for index, count in reversed(list(enumerate(row_counts))) if count >= row_threshold), None)
            left = next((index for index, count in enumerate(column_counts) if count >= column_threshold), None)
            right = next((index for index, count in reversed(list(enumerate(column_counts))) if count >= column_threshold), None)

    if top is None or bottom is None or left is None or right is None:
        return CropBox(left=0, top=0, width=width, height=height)

    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(width - 1, right + padding)
    bottom = min(height - 1, bottom + padding)

    return CropBox(
        left=left,
        top=top,
        width=(right - left + 1),
        height=(bottom - top + 1),
    )


def crop_ppm_to_png(ppm_path: Path, output_path: Path, crop_box: CropBox) -> tuple[int, int]:
    args = [
        "sips",
        "-s",
        "format",
        "png",
        "-c",
        str(crop_box.height),
        str(crop_box.width),
        "--cropOffset",
        str(crop_box.top),
        str(crop_box.left),
        str(ppm_path),
        "--out",
        str(output_path),
    ]
    run_command(args)
    return read_image_size(output_path)


def read_image_size(image_path: Path) -> tuple[int, int]:
    result = run_command(
        [
            "sips",
            "-g",
            "pixelWidth",
            "-g",
            "pixelHeight",
            str(image_path),
        ]
    )
    width_match = re.search(r"pixelWidth:\s+(\d+)", result.stdout)
    height_match = re.search(r"pixelHeight:\s+(\d+)", result.stdout)
    if not width_match or not height_match:
        raise ValueError(f"Unable to read image size from {image_path}")
    return int(width_match.group(1)), int(height_match.group(1))


def parse_pdf_page_count(pdf_path: Path) -> int:
    result = run_command(["pdfinfo", str(pdf_path)])
    match = re.search(r"^Pages:\s+(\d+)$", result.stdout, flags=re.MULTILINE)
    if not match:
        raise ValueError("Unable to determine page count from pdfinfo output")
    return int(match.group(1))


def parse_pdf_page_size_points(pdf_path: Path) -> tuple[float, float]:
    result = run_command(["pdfinfo", str(pdf_path)])
    match = re.search(r"^Page size:\s+([0-9.]+)\s+x\s+([0-9.]+)\spts$", result.stdout, flags=re.MULTILINE)
    if not match:
        raise ValueError("Unable to determine page size from pdfinfo output")
    return float(match.group(1)), float(match.group(2))


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


def parse_ghostscript_bboxes(output_text: str) -> list[tuple[float, float, float, float]]:
    matches = re.findall(
        r"^%%HiResBoundingBox:\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)$",
        output_text,
        flags=re.MULTILINE,
    )
    return [tuple(float(value) for value in match) for match in matches]


def extract_page_bboxes(pdf_path: Path) -> list[tuple[float, float, float, float]]:
    result = run_command(
        [
            "gs",
            "-q",
            "-dNOPAUSE",
            "-dBATCH",
            "-sDEVICE=bbox",
            str(pdf_path),
        ]
    )
    bbox_output = f"{result.stdout}\n{result.stderr}"
    return parse_ghostscript_bboxes(bbox_output)


def crop_box_from_pdf_bbox(
    bbox: tuple[float, float, float, float],
    *,
    page_width_points: float,
    page_height_points: float,
    dpi: int,
    padding: int,
) -> CropBox:
    left_points, bottom_points, right_points, top_points = bbox
    left = math.floor((left_points / 72.0) * dpi) - padding
    top = math.floor(((page_height_points - top_points) / 72.0) * dpi) - padding
    right = math.ceil((right_points / 72.0) * dpi) + padding
    bottom = math.ceil(((page_height_points - bottom_points) / 72.0) * dpi) + padding

    left = max(0, left)
    top = max(0, top)
    right = min(math.ceil((page_width_points / 72.0) * dpi), right)
    bottom = min(math.ceil((page_height_points / 72.0) * dpi), bottom)

    full_width = math.ceil((page_width_points / 72.0) * dpi)
    full_height = math.ceil((page_height_points / 72.0) * dpi)
    cropped_width = max(1, right - left)
    cropped_height = max(1, bottom - top)

    # Tiny mark-only pages should stay full size instead of collapsing to a stamp-like page.
    if cropped_width < max(32, int(full_width * 0.10)) or cropped_height < max(32, int(full_height * 0.10)):
        return CropBox(left=0, top=0, width=full_width, height=full_height)

    return CropBox(
        left=left,
        top=top,
        width=cropped_width,
        height=cropped_height,
    )


def extract_outline(pdf_path: Path, work_dir: Path, logger: logging.Logger | None = None) -> list[TocEntry]:
    if shutil.which("pdftohtml") is None:
        if logger is not None:
            logger.warning("Skipping outline extraction because pdftohtml is unavailable.")
        return []

    output_prefix = work_dir / "outline"
    try:
        run_command(
            [
                "pdftohtml",
                "-xml",
                "-i",
                "-f",
                "1",
                "-l",
                "1",
                str(pdf_path),
                str(output_prefix),
            ]
        )
    except subprocess.CalledProcessError as error:
        if logger is not None:
            logger.warning("Outline extraction failed: %s", error)
        return []

    xml_path = output_prefix.with_suffix(".xml")
    if not xml_path.exists():
        if logger is not None:
            logger.warning("Outline extraction produced no XML file.")
        return []

    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as error:
        if logger is not None:
            logger.warning("Outline XML parsing failed: %s", error)
        return []

    outline = root.find("outline")
    if outline is None:
        return []

    entries: list[TocEntry] = []

    def walk(node: ET.Element) -> None:
        for child in node:
            if child.tag != "item":
                if child.tag == "outline":
                    walk(child)
                continue

            label = (child.text or "").strip()
            page_text = child.attrib.get("page", "").strip()
            if label and page_text.isdigit():
                entries.append(TocEntry(label=label, page_index=int(page_text)))

            nested_outline = child.find("outline")
            if nested_outline is not None:
                walk(nested_outline)

    walk(outline)
    return entries


def render_page_to_ppm(pdf_path: Path, page_number: int, dpi: int, output_prefix: Path) -> Path:
    run_command(
        [
            "pdftoppm",
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-r",
            str(dpi),
            str(pdf_path),
            str(output_prefix),
        ]
    )
    return find_rendered_page_path(output_prefix, page_number)


def build_nav_document(title: str, toc_entries: list[TocEntry], page_count: int) -> str:
    nav_items: list[str] = []
    if toc_entries:
        for entry in toc_entries:
            safe_label = html.escape(entry.label)
            nav_items.append(f'<li><a href="pages/page-{entry.page_index:04d}.xhtml">{safe_label}</a></li>')
    else:
        for page_index in range(1, page_count + 1):
            nav_items.append(f'<li><a href="pages/page-{page_index:04d}.xhtml">Page {page_index}</a></li>')

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ko">
<head>
  <title>{html.escape(title)}</title>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>{html.escape(title)}</h1>
    <ol>
      {''.join(nav_items)}
    </ol>
  </nav>
</body>
</html>
"""


def build_ncx_document(identifier: str, title: str, toc_entries: list[TocEntry], page_count: int) -> str:
    points: list[str] = []
    if toc_entries:
        source_entries = toc_entries
    else:
        source_entries = [TocEntry(label=f"Page {page_index}", page_index=page_index) for page_index in range(1, page_count + 1)]

    for play_order, entry in enumerate(source_entries, start=1):
        points.append(
            f"""
    <navPoint id="navPoint-{play_order}" playOrder="{play_order}">
      <navLabel><text>{html.escape(entry.label)}</text></navLabel>
      <content src="pages/page-{entry.page_index:04d}.xhtml"/>
    </navPoint>"""
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{identifier}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{html.escape(title)}</text></docTitle>
  <navMap>{''.join(points)}
  </navMap>
</ncx>
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
    <img src="../images/{html.escape(image_name)}" alt="{html.escape(page.spine_title)}" width="{page.width}" height="{page.height}"/>
  </div>
</body>
</html>
"""


def build_opf_document(identifier: str, title: str, author: str, language: str, pages: list[PageAsset]) -> str:
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="styles/fixed.css" media-type="text/css"/>',
    ]
    spine_items = ['<itemref idref="nav"/>']

    for page in pages:
        page_id = f"page-{page.index:04d}"
        image_id = f"image-{page.index:04d}"
        media_type = "image/png"
        manifest_items.append(
            f'<item id="{page_id}" href="pages/{page_id}.xhtml" media-type="application/xhtml+xml"/>'
        )
        manifest_items.append(
            f'<item id="{image_id}" href="images/{page.image_path.name}" media-type="{media_type}"/>'
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
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:orientation">auto</meta>
    <meta property="rendition:spread">auto</meta>
  </metadata>
  <manifest>
    {''.join(manifest_items)}
  </manifest>
  <spine toc="ncx">
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
    toc_entries: list[TocEntry],
) -> None:
    identifier = f"urn:uuid:{uuid.uuid4()}"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fixed_css = """html, body { margin: 0; padding: 0; }
body { background: #fff; }
.page { position: relative; overflow: hidden; }
img { display: block; width: 100%; height: 100%; object-fit: contain; }
"""

    nav_xhtml = build_nav_document(title, toc_entries, len(pages))
    ncx = build_ncx_document(identifier, title, toc_entries, len(pages))
    opf = build_opf_document(identifier, title, author, language, pages)

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
        epub.writestr("OEBPS/toc.ncx", ncx)
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
    white_threshold: int = 245,
    padding: int = 16,
    language: str = "ko",
    keep_temp: bool = False,
    logger: logging.Logger | None = None,
) -> None:
    require_commands(REQUIRED_COMMANDS)

    if not input_pdf.exists():
        raise SystemExit(f"Input PDF not found: {input_pdf}")
    if input_pdf.suffix.lower() != ".pdf":
        raise SystemExit(f"Input file is not a PDF: {input_pdf}")

    page_count = parse_pdf_page_count(input_pdf)
    page_width_points, page_height_points = parse_pdf_page_size_points(input_pdf)
    pdf_title, pdf_author = parse_pdf_metadata(input_pdf)
    title = pdf_title or input_pdf.stem
    author = pdf_author or "Unknown"

    if logger is not None:
        logger.info("Starting conversion.")
        logger.info("Input PDF: %s", input_pdf)
        logger.info("Output EPUB: %s", output_epub)
        logger.info("Pages: %s", page_count)
        logger.info("Page size (pt): %sx%s", page_width_points, page_height_points)
        logger.info("DPI=%s padding=%s white_threshold=%s keep_temp=%s", dpi, padding, white_threshold, keep_temp)

    temp_dir_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="pdf2epub-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        try:
            ppm_dir = temp_dir_path / "ppm"
            image_dir = temp_dir_path / "images"
            ppm_dir.mkdir(parents=True, exist_ok=True)
            image_dir.mkdir(parents=True, exist_ok=True)

            if logger is not None:
                logger.info("Working directory: %s", temp_dir_path)

            page_bboxes: list[tuple[float, float, float, float]] | None = None
            if shutil.which("gs") is not None:
                try:
                    candidate_bboxes = extract_page_bboxes(input_pdf)
                    if len(candidate_bboxes) == page_count:
                        page_bboxes = candidate_bboxes
                        if logger is not None:
                            logger.info("Using Ghostscript bounding boxes for cropping.")
                    elif logger is not None:
                        logger.warning(
                            "Ghostscript bbox count mismatch: expected %s got %s. Falling back to raster heuristic.",
                            page_count,
                            len(candidate_bboxes),
                        )
                except Exception:
                    if logger is not None:
                        logger.exception("Ghostscript bbox extraction failed. Falling back to raster heuristic.")

            outline_entries = extract_outline(input_pdf, temp_dir_path, logger=logger)
            if logger is not None:
                logger.info("Outline entries: %s", len(outline_entries))

            pages: list[PageAsset] = []

            for page_number in range(1, page_count + 1):
                if logger is not None:
                    logger.info("Processing page %s/%s", page_number, page_count)

                try:
                    ppm_path = render_page_to_ppm(input_pdf, page_number, dpi, ppm_dir / "page")
                    if page_bboxes is not None:
                        crop_box = crop_box_from_pdf_bbox(
                            page_bboxes[page_number - 1],
                            page_width_points=page_width_points,
                            page_height_points=page_height_points,
                            dpi=dpi,
                            padding=padding,
                        )
                    else:
                        crop_box = detect_crop_box_from_ppm(
                            ppm_path,
                            white_threshold=white_threshold,
                            padding=padding,
                        )
                    png_path = image_dir / f"page-{page_number:04d}.png"
                    width, height = crop_ppm_to_png(ppm_path, png_path, crop_box)
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
                    logger.info(
                        "Processed page %s/%s -> %sx%s crop=(left=%s top=%s width=%s height=%s)",
                        page_number,
                        page_count,
                        width,
                        height,
                        crop_box.left,
                        crop_box.top,
                        crop_box.width,
                        crop_box.height,
                    )

            filtered_toc = [entry for entry in outline_entries if 1 <= entry.page_index <= page_count]
            if logger is not None:
                logger.info("Writing EPUB package with %s pages and %s TOC entries.", len(pages), len(filtered_toc))

            write_fixed_layout_epub(
                output_path=output_epub,
                title=title,
                author=author,
                language=language,
                pages=pages,
                toc_entries=filtered_toc,
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
        description="Convert a PDF to a cropped fixed-layout EPUB."
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
    parser.add_argument(
        "--white-threshold",
        type=int,
        default=245,
        help="Treat pixels below this RGB value as content (default: 245)",
    )
    parser.add_argument(
        "--padding",
        type=int,
        default=16,
        help="Padding to add back after auto-crop in pixels (default: 16)",
    )
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
            white_threshold=args.white_threshold,
            padding=args.padding,
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
