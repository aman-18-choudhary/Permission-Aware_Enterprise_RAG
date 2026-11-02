import re

MAX_CHARS = 1200
OVERLAP = 150


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP) -> list[str]:
    """Paragraph-aware chunking: pack paragraphs up to max_chars, split oversize
    paragraphs on sentence boundaries, carry a small overlap between chunks."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    for p in paras:
        if len(p) <= max_chars:
            pieces.append(p)
            continue
        buf = ""
        for s in re.split(r"(?<=[.!?])\s+|\n", p):
            while len(s) > max_chars:  # no sentence boundary: hard split
                if buf:
                    pieces.append(buf)
                    buf = ""
                pieces.append(s[:max_chars])
                s = s[max_chars:]
            if buf and len(buf) + len(s) + 1 > max_chars:
                pieces.append(buf)
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            pieces.append(buf)

    chunks: list[str] = []
    cur = ""
    for piece in pieces:
        if cur and len(cur) + len(piece) + 2 > max_chars:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap else ""
            cur = (tail + "\n\n" + piece).strip() if tail else piece
        else:
            cur = f"{cur}\n\n{piece}".strip()
    if cur:
        chunks.append(cur)
    return chunks
