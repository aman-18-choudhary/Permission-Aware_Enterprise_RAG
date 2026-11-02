"""Keyword (sparse) vectors for hybrid search.

Terms are hashed into a fixed index space and weighted by term frequency.
Qdrant applies IDF server-side (Modifier.IDF on the sparse vector config),
which together gives BM25-style keyword scoring without a model download.
"""
import re
import zlib
from collections import Counter

DIM = 1 << 20
_TOKEN = re.compile(r"[a-z0-9_]+(?:[-.][a-z0-9_]+)*")  # keeps IDs like JIRA-4521, v1.2


def tokenize(text: str) -> list[str]:
    toks = _TOKEN.findall(text.lower())
    out = list(toks)
    for t in toks:  # also index the parts of compound tokens
        if "-" in t or "." in t:
            out.extend(p for p in re.split(r"[-.]", t) if p)
    return out


def sparse_vector(text: str) -> tuple[list[int], list[float]]:
    counts: Counter[int] = Counter(zlib.crc32(t.encode()) % DIM for t in tokenize(text))
    idx = sorted(counts)
    return idx, [float(counts[i]) for i in idx]
