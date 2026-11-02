import uuid
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from .sparse import sparse_vector


@dataclass
class Hit:
    doc_id: str
    title: str
    url: str | None
    text: str
    score: float


def _acl_filter(principals: list[str]) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key="acl", match=models.MatchAny(any=principals))])


def _doc_filter(doc_id: str) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])


class VectorStore:
    def __init__(self, url: str, collection: str, dim: int):
        if url == ":memory:":
            self.client = QdrantClient(location=":memory:")
        elif url.startswith(("http://", "https://")):
            self.client = QdrantClient(url=url)
        else:  # a directory path: embedded Qdrant persisted on disk (single process, dev use)
            self.client = QdrantClient(path=url)
        self.collection = collection
        self.dim = dim

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(
            self.collection,
            vectors_config={"dense": models.VectorParams(size=self.dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        for field in ("acl", "doc_id"):
            self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)

    def upsert_chunks(
        self,
        doc_id: str,
        source_id: str,
        title: str,
        url: str | None,
        acl: list[str],
        chunks: list[str],
        dense: list[list[float]],
    ) -> None:
        points = []
        for i, (text, vec) in enumerate(zip(chunks, dense)):
            idx, vals = sparse_vector(f"{title}\n{text}")
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{i}")),
                    vector={"dense": vec, "sparse": models.SparseVector(indices=idx, values=vals)},
                    payload={
                        "doc_id": doc_id,
                        "source_id": source_id,
                        "title": title,
                        "url": url,
                        "text": text,
                        "chunk_index": i,
                        "acl": acl,
                    },
                )
            )
        for i in range(0, len(points), 64):
            self.client.upsert(self.collection, points[i : i + 64], wait=True)

    def delete_doc(self, doc_id: str) -> None:
        self.client.delete(self.collection, models.FilterSelector(filter=_doc_filter(doc_id)), wait=True)

    def set_acl(self, doc_id: str, acl: list[str]) -> None:
        self.client.set_payload(self.collection, payload={"acl": acl}, points=_doc_filter(doc_id), wait=True)

    def search(self, dense: list[float], query_text: str, principals: list[str], limit: int = 6) -> list[Hit]:
        """Hybrid search: dense + sparse prefetch, fused with RRF. The ACL
        filter is applied INSIDE every prefetch and the final query (pre-filtering),
        so restricted chunks are never candidates."""
        if not principals:
            return []
        flt = _acl_filter(principals)
        idx, vals = sparse_vector(query_text)
        prefetch = [models.Prefetch(query=dense, using="dense", filter=flt, limit=30)]
        if idx:
            prefetch.append(
                models.Prefetch(query=models.SparseVector(indices=idx, values=vals), using="sparse", filter=flt, limit=30)
            )
        res = self.client.query_points(
            self.collection,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=flt,
            limit=limit,
            with_payload=True,
        )
        return [
            Hit(
                doc_id=p.payload["doc_id"],
                title=p.payload["title"],
                url=p.payload.get("url"),
                text=p.payload["text"],
                score=p.score,
            )
            for p in res.points
        ]

    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count
