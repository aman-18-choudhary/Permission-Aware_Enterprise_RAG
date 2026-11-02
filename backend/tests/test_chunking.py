from app.chunking import chunk_text


def test_empty():
    assert chunk_text("  \n ") == []


def test_respects_max_and_overlaps():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(20))
    chunks = chunk_text(text, max_chars=800, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) <= 800 + 100 + 2 for c in chunks)
    assert chunks[1].startswith(chunks[0][-100:].strip()[:20])


def test_oversize_paragraph_without_punctuation():
    chunks = chunk_text("x" * 5000, max_chars=1000, overlap=0)
    assert len(chunks) == 5
