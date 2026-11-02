import io

TEXT_EXT = {".txt", ".md", ".rst", ".csv", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".tsx", ".go", ".java", ".sql", ".html"}


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    if any(name.endswith(e) for e in TEXT_EXT):
        return data.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported file type: {filename}")
