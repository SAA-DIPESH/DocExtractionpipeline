import re
from collections import Counter
from pathlib import Path
from typing import Union

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption  # type: ignore
from docling_core.types.doc import (
    PictureItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
)

input_file = ""
output_md = "app/infrastrature/documents/out_doc/"
image_dir = Path("images")
image_dir.mkdir(exist_ok=True)


def _clean_text(text: str) -> str:
    text = re.sub(r"!\[.*?\]\(.*?\)", " ", text)
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _first_chars(text: str, limit: int) -> str:
    return _clean_text(text)[:limit]


def _get_page_number(element) -> int | None:
    provenance = getattr(element, "prov", None) or []
    for item in provenance:
        page_no = getattr(item, "page_no", None)
        if page_no is not None:
            return int(page_no)
    return None


class DoclingService:

    def __init__(self, image_dir: Union[str, Path] = "images"):
        """Initializes the DoclingService and sets up the document converter pipeline."""
        self.image_dir = Path(image_dir)
        self.last_page_count = 0
        self._init_converter()

    def _init_converter(self) -> None:
        """Configures the pipeline options and instantiates the DocumentConverter."""
        pipeline_options = PdfPipelineOptions()

        # Required for extracting images via get_image()
        pipeline_options.generate_page_images = True
        pipeline_options.generate_picture_images = True

        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options
                )
            }
        )

    def convert_pdf_to_markdown(
        self, input_file: Union[str, Path], output_md_path: Union[str, Path]
    ) -> Path:
        """Converts an input PDF into Markdown format, extracts images, and saves both to disk."""
        input_path = Path(input_file)
        output_path = Path(output_md_path)

        # Ensure directories exist
        self.image_dir.mkdir(parents=True, exist_ok=True)
        if output_path.suffix:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            # If output_md_path is a directory string, append a default filename
            output_path = output_path / f"{input_path.stem}.md"
            output_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert document
        result = self.converter.convert(input_path)
        doc = result.document
        self.last_page_count = len(getattr(doc, "pages", {}) or {})

        markdown_segments = []
        image_count = 1
        current_page_number = None

        # Iterate document elements
        for element, _ in doc.iterate_items():
            page_number = _get_page_number(element)
            if page_number is not None and page_number != current_page_number:
                markdown_segments.append(f"\n<!-- PageNumber: {page_number} -->\n")
                current_page_number = page_number

            # --- Heading ---
            if isinstance(element, SectionHeaderItem):
                markdown_segments.append(f"\n# {element.text}\n")

            # --- Paragraph ---
            elif isinstance(element, TextItem):
                markdown_segments.append(f"{element.text}\n")

            # --- Table ---
            elif isinstance(element, TableItem):
                markdown_segments.append("\n")
                markdown_segments.append(element.export_to_markdown(doc=doc))
                markdown_segments.append("\n")

            # --- Image / Figure / Flowchart ---
            elif isinstance(element, PictureItem):
                image = element.get_image(doc)
                if image is not None:
                    image_path = self.image_dir / f"image_{image_count}.png"
                    image.save(image_path)

                    markdown_segments.append(
                        f"\n![Image {image_count}]({image_path.as_posix()})\n"
                    )
                    print(f"Saved image: {image_path}")
                    image_count += 1

        # Save markdown output
        output_path.write_text("\n".join(markdown_segments), encoding="utf-8")
        return output_path

    def extract_markdown_metadata(self, markdown_file: Union[str, Path]) -> dict:
        """Extracts metadata from a markdown file."""

        markdown_path = Path(markdown_file)

        if not markdown_path.exists():
            raise FileNotFoundError(markdown_path)

        # File information
        file_name = markdown_path.name          # e.g. document.md
        file_stem = markdown_path.stem          # e.g. document

        text = markdown_path.read_text(encoding="utf-8")

        # ---------------------------
        # Headings
        # ---------------------------
        headings = re.findall(r"^#+\s+(.*)", text, flags=re.MULTILINE)

        # ---------------------------
        # Images
        # ---------------------------
        image_count = len(re.findall(r"!\[.*?\]\(.*?\)", text))

        # ---------------------------
        # Tables
        # ---------------------------
        table_headers = []
        table_count = 0

        lines = text.splitlines()

        for i, line in enumerate(lines):
            if "|" in line:
                if i + 1 < len(lines) and "---" in lines[i + 1]:
                    table_count += 1
                    headers = [
                        h.strip()
                        for h in line.split("|")
                        if h.strip()
                    ]
                    table_headers.extend(headers)

        # ---------------------------
        # Keywords
        # ---------------------------
        words = re.findall(r"\b[A-Za-z]{4,}\b", text)
        counter = Counter(word.lower() for word in words)

        metadata = {
            "file_name": file_name,
            "file_stem": file_stem,

            "document_title": headings[0] if headings else file_stem,

            "document_family": "",
            "document_type": "",
            "appendix_number": "",
            "organisation": "",

            "summary": _first_chars(text, 500),

            "main_headings": headings,
            "section_titles": headings,

            "keywords": list(counter.keys())[:20],
            "top_ngrams": [
                word for word, _ in counter.most_common(20)
            ],

            "named_entities": [],

            "table_headers": table_headers,
            "table_count": table_count,

            "image_count": image_count,
            "page_count": self.last_page_count,

            "processing_status": "SUCCESS",
        }

        return metadata


# if __name__ == "__main__":
#     service = DoclingService()
#     markdown_path = service.convert_pdf_to_markdown(
#         "app/infrastrature/documents/input_doc/Example ITT Appendix D Questionnaire and Response Guidance v1.5 (1).pdf",
#         "app/infrastrature/documents/out_doc/",
#     )
#     metadata = service.extract_markdown_metadata(markdown_path)
#     print(metadata)
