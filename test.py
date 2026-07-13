from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import SparseVector, Filter, FieldCondition, MatchValue

client = QdrantClient(url="http://localhost:6333")

sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
query = "Quality Evaluation Process"
sparse_embedding = list(sparse_model.embed([query]))[0]

sparse_vector = SparseVector(
    indices=sparse_embedding.indices.tolist(),
    values=sparse_embedding.values.tolist(),
)

results = client.query_points(
    collection_name="CPTenderDoc",
    query=sparse_vector,
    using="sparse",
    query_filter=Filter(
        must=[
            FieldCondition(
                key="CompanyId",
                match=MatchValue(value="6a45059ff419103201431533"),
            )
        ]
    ),
    limit=5,
    with_payload=True,
)

for point in results.points:
    print(point.score)
    print(point.payload.get("DocumentName"))
    print(point.payload.get("PageNumber"))
    print(point.payload.get("RelatedSection"))
    print(point.payload.get("Text"))