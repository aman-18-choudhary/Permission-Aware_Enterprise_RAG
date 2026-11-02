import logging
import threading

from .vectorstore import Hit

log = logging.getLogger(__name__)


class CrossEncoderReranker:
    """Re-scores retrieval candidates with a local cross-encoder (ONNX via fastembed).

    A cross-encoder reads the question and each passage together, which is far
    more precise than comparing independent embeddings, but too slow to run over
    the whole index, so it only sees the (already ACL-filtered) top candidates.
    Free, no API quota. If the model can't load or run, we keep the RRF order.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                log.info("loading reranker %s", self.model_name)
                self._model = TextCrossEncoder(model_name=self.model_name)
        return self._model

    def warm(self) -> None:
        """Load (and download, first time) the model ahead of the first question."""
        self._load()

    def rerank(self, query: str, hits: list[Hit], top_k: int) -> list[Hit]:
        if len(hits) <= 1:
            return hits[:top_k]
        try:
            scores = list(self._load().rerank(query, [f"{h.title}\n{h.text}" for h in hits]))
        except Exception:
            log.warning("reranker failed; keeping hybrid-search order", exc_info=True)
            return hits[:top_k]
        ranked = sorted(zip(scores, hits), key=lambda p: p[0], reverse=True)
        return [Hit(h.doc_id, h.title, h.url, h.text, float(s)) for s, h in ranked[:top_k]]
