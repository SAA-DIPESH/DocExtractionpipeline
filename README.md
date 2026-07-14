# Document Extraction Pipeline

## Sample Test Payloads

## Required Usage Log Env

Token usage logs are sent only when this env variable is configured:

```env
AI_USAGE_LOG_API="https://vibeappop.saa.ai/DocAI/api/Contract/InsertAiUsageLog"
```

If MongoDB stores only a relative document path, configure the local/server root folder:

```env
DOCUMENT_BASE_PATH="D:/Uploads/TenderDocuments"
```

The request body `bearer_token` is forwarded as:

```http
Authorization: Bearer YOUR_BEARER_TOKEN
```

### Process OCR From Mongo By Tender ID

`POST /documents/process/ocr/using_Tenderid_or_Companyid`

```json
{
  "tender_id": "6a4506d2f4191032014315fd",
  "company_id": "6a45059ff419103201431533",
  "project_id": "",
  "user_id": "",
  "created_by": "",
  "user_name": "",
  "bearer_token": "YOUR_BEARER_TOKEN"
}
```

### Process OCR From Mongo By Company ID

`POST /documents/process/ocr/using_Tenderid_or_Companyid`

```json
{
  "tender_id": "",
  "company_id": "6a45059ff419103201431533",
  "project_id": "",
  "user_id": "",
  "created_by": "",
  "user_name": "",
  "bearer_token": "YOUR_BEARER_TOKEN"
}
```

Mongo document eligibility:

```json
{
  "IsActive": false,
  "IsLoadedByAI": false
}
```

After successful processing:

```json
{
  "IsActive": true,
  "IsLoadedByAI": false,
  "Status": "Processed"
}
```

### Dense Retrieval

`POST /documents/retrieve`

Tender document search:

```json
{
  "collection_name": "CPTenderDoc",
  "company_id": "6a45059ff419103201431533",
  "query": "Quality Evaluation Process",
  "limit": 5
}
```

Company document search:

```json
{
  "collection_name": "CPDocuments",
  "company_id": "6a45059ff419103201431533",
  "query": "company overview services mission vision",
  "limit": 5
}
```

### Sparse Search Check

Run this locally after sparse vectors are available in Qdrant:

```python
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import SparseVector, Filter, FieldCondition, MatchValue

client = QdrantClient(url="YOUR_QDRANT_URL")

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
```
