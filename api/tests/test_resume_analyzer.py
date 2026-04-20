from __future__ import annotations

import io
import zipfile

from app.resume_analyzer import _extract_docx_text, _extract_resume_text


def _minimal_docx_bytes(paragraphs: list[str]) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        for text in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body>"
        "</w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def test_extract_docx_text_reads_visible_paragraphs():
    blob = _minimal_docx_bytes(
        [
            "Jordan Lee",
            "Experience: Data Analyst at Fulcrum Digital",
            "Education: MS in Data Science at NYU",
        ]
    )
    text = _extract_docx_text(blob)
    assert "Jordan Lee" in text
    assert "Data Analyst at Fulcrum Digital" in text
    assert "MS in Data Science at NYU" in text


def test_extract_resume_text_uses_docx_parser_for_docx():
    blob = _minimal_docx_bytes(["Business Analyst", "Risk and operations background"])
    text = _extract_resume_text("resume.docx", blob)
    assert "Business Analyst" in text
    assert "Risk and operations background" in text


def test_extract_docx_text_returns_empty_on_invalid_blob():
    assert _extract_docx_text(b"not-a-docx") == ""
