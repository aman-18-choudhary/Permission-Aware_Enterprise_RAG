import io

TEXT_EXT = {".txt", ".md", ".rst", ".csv", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".tsx", ".go", ".java", ".sql", ".html"}


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    if name.endswith(".docx"):
        from docx import Document

        doc = Document(io.BytesIO(data))
        parts = [para.text for para in doc.paragraphs if para.text.strip()]
        for table in doc.tables:
            parts += [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
        return "\n\n".join(parts)
    if any(name.endswith(e) for e in TEXT_EXT):
        return data.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported file type: {filename}")
