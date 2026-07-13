
import os
import re
import time
import uuid
from pathlib import Path
from typing import Literal, List, Dict, Any, Optional
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from app.services.qdrant.qdrant_services import QdrantService
from app.services.embedding.embedding_model import EmbeddingModel
from app.utils.token_usage import TokenUsageService



load_dotenv()

class DocumentEmbedder:

    @staticmethod
    def get_embedding_model():
        """Returns the active embedding model configured in MongoDB."""
        return EmbeddingModel.get_embedding_model()

    @staticmethod
    def get_sparse_embedding_model():
        """Lazily loads BM25 sparse embedding so module import does not require fastembed."""
        try:
            from fastembed import SparseTextEmbedding
        except ImportError:
            return None
        return SparseTextEmbedding(model_name="Qdrant/bm25")

    @staticmethod
    def extract_title(markdown_content: str, fallback: str) -> str:
        """Extracts the document title from the first markdown heading."""
        for line in markdown_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                if title:
                    return title
        return fallback

    @staticmethod
    def extract_related_sections(metadata: Dict[str, Any]) -> List[str]:
        """Builds a clean section list from markdown splitter metadata."""
        sections = []
        for key in ("H1", "H2", "H3"):
            value = metadata.get(key)
            if value and value not in sections:
                sections.append(str(value))
        return sections

    @staticmethod
    def extract_page_number(metadata: Dict[str, Any]) -> Optional[int]:
        """Returns page number when upstream chunk metadata contains it."""
        for key in ("PageNumber", "page_number", "page", "page_no"):
            value = metadata.get(key)
            if value in (None, ""):
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def extract_page_number_from_text(text: str) -> Optional[int]:
        match = re.search(r"<!--\s*PageNumber:\s*(\d+)\s*-->", text)
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def remove_page_markers(text: str) -> str:
        return re.sub(r"<!--\s*PageNumber:\s*\d+\s*-->\s*", "", text).strip()

    @staticmethod
    def split_markdown_by_page(markdown_content: str) -> List[Dict[str, Any]]:
        """Splits markdown on page markers and assigns each section a page number."""
        page_sections = []
        current_page_number = None
        buffer = []

        for line in markdown_content.splitlines():
            match = re.search(r"<!--\s*PageNumber:\s*(\d+)\s*-->", line)
            if match:
                content = "\n".join(buffer).strip()
                if content:
                    page_sections.append(
                        {
                            "page_number": current_page_number,
                            "content": content,
                        }
                    )
                current_page_number = int(match.group(1))
                buffer = []
                continue

            buffer.append(line)

        content = "\n".join(buffer).strip()
        if content:
            page_sections.append(
                {
                    "page_number": current_page_number,
                    "content": content,
                }
            )

        return page_sections

    @staticmethod
    def is_table_separator(line: str) -> bool:
        stripped = line.strip()
        return "|" in stripped and bool(re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", stripped))

    @staticmethod
    def is_table_row(line: str) -> bool:
        return "|" in line and bool(line.strip())

    @staticmethod
    def split_tables_from_text(text: str) -> List[Dict[str, str]]:
        """Splits markdown into text/table segments, keeping each markdown table intact."""
        segments = []
        text_buffer = []
        lines = text.splitlines()
        index = 0
        current_page_marker = ""

        def flush_text_buffer():
            if text_buffer:
                content = "\n".join(text_buffer).strip()
                if content:
                    segments.append({"type": "Text", "content": content})
                text_buffer.clear()

        while index < len(lines):
            line = lines[index]
            marker = re.search(r"<!--\s*PageNumber:\s*\d+\s*-->", line)
            if marker:
                current_page_marker = marker.group(0)
                text_buffer.append(line)
                index += 1
                continue

            is_table_start = (
                DocumentEmbedder.is_table_row(line)
                and index + 1 < len(lines)
                and DocumentEmbedder.is_table_separator(lines[index + 1])
            )

            if not is_table_start:
                text_buffer.append(line)
                index += 1
                continue

            flush_text_buffer()
            table_lines = []
            if current_page_marker:
                table_lines.append(current_page_marker)

            while index < len(lines) and DocumentEmbedder.is_table_row(lines[index]):
                table_lines.append(lines[index])
                index += 1

            table_content = "\n".join(table_lines).strip()
            if table_content:
                segments.append({"type": "Table", "content": table_content})

        flush_text_buffer()
        return segments

    @staticmethod
    def split_documents_preserving_tables(
        documents: List[Document],
        text_splitter: RecursiveCharacterTextSplitter,
    ) -> List[Document]:
        chunks = []
        for document in documents:
            for segment in DocumentEmbedder.split_tables_from_text(document.page_content):
                metadata = dict(document.metadata)
                metadata["ContentType"] = segment["type"]

                segment_document = Document(
                    page_content=segment["content"],
                    metadata=metadata,
                )

                if segment["type"] == "Table":
                    chunks.append(segment_document)
                else:
                    chunks.extend(text_splitter.split_documents([segment_document]))

        return chunks

    @staticmethod
    def to_qdrant_sparse_vector(sparse_embedding) -> SparseVector:
        indices = getattr(sparse_embedding, "indices", [])
        values = getattr(sparse_embedding, "values", [])
        if hasattr(indices, "tolist"):
            indices = indices.tolist()
        if hasattr(values, "tolist"):
            values = values.tolist()
        return SparseVector(indices=indices, values=values)

    @staticmethod
    def get_query_vector_name(
        client: QdrantClient,
        collection_name: str,
    ) -> Optional[str]:
        try:
            collection_info = client.get_collection(collection_name=collection_name)
            vectors_config = getattr(collection_info.config.params, "vectors", None)
            if isinstance(vectors_config, dict) and "dense" in vectors_config:
                return "dense"
        except Exception:
            pass

        return None

    @staticmethod
    async def embed_markdown_document(
        file_path: str,
        document_scope: Literal["company", "tender"],
        company_id: Optional[str],
        document_name: str,
        document_type: str,
        created_by: Optional[str],
        created_at: str,
        tender_id: Optional[str] = None,
        client: Optional[QdrantClient] = None,
        usage_context: Optional[Dict[str, Any]] = None,
        document_id: Optional[str] = None,
    ) -> str:
        """
        Reads a markdown file, splits it into semantic chunks, generates OpenAI embeddings,
        and uploads them to a Qdrant collection. Generates its own DocumentId and RelatedSections.
        """
        document_scope = document_scope.lower()

        if document_scope == "company":
            collection_name = "CPDocuments"
        elif document_scope == "tender":
            collection_name = "CPTenderDoc"
        else:
            raise ValueError("document_scope must be either 'company' or 'tender'")

        # 1. Reuse Mongo DocumentId when this is called by the Mongo-backed flow.
        document_id = document_id or str(uuid.uuid4())

        # 2. Read Markdown File
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"The file {file_path} does not exist.")
            
        with open(file_path, "r", encoding="utf-8") as f:
            markdown_content = f.read()
        title = DocumentEmbedder.extract_title(
            markdown_content=markdown_content,
            fallback=Path(document_name).stem,
        )
        document_extension = Path(document_name).suffix.lstrip(".").upper()

        # 3. Markdown Header Splitting
        headers_to_split_on = [
            ("#", "H1"),
            ("##", "H2"),
            ("###", "H3"),
        ]
        header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
        header_chunks = []
        page_sections = DocumentEmbedder.split_markdown_by_page(markdown_content)
        if not page_sections:
            page_sections = [
                {
                    "page_number": 1,
                    "content": markdown_content,
                }
            ]

        for page_section in page_sections:
            page_header_chunks = header_splitter.split_text(page_section["content"])
            page_number = page_section["page_number"] or 1
            for page_header_chunk in page_header_chunks:
                page_header_chunk.metadata["PageNumber"] = page_number
            header_chunks.extend(page_header_chunks)

        # 4. Further Recursive Character Splitting
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
        )
        chunks = DocumentEmbedder.split_documents_preserving_tables(
            documents=header_chunks,
            text_splitter=text_splitter,
        )
        print(f"Total Chunks Generated: {len(chunks)}")

        if not chunks:
            print("No chunks generated from document.")
            return document_id

        chunks_with_text = [
            (chunk, DocumentEmbedder.remove_page_markers(chunk.page_content))
            for chunk in chunks
        ]
        chunks_with_text = [
            (chunk, chunk_text)
            for chunk, chunk_text in chunks_with_text
            if chunk_text.strip()
        ]

        if not chunks_with_text:
            print("No non-empty chunks generated from document.")
            return document_id

        # 5. Initialize OpenAI Embedding Model
        embedding_model = DocumentEmbedder.get_embedding_model()
        sparse_model = DocumentEmbedder.get_sparse_embedding_model()
        vector_dimension = 1536 

        # 6. Initialize/Use Qdrant Client
        if client is None:
            client = QdrantService.get_client()
        
        collections = [c.name for c in client.get_collections().collections]
        collection_supports_sparse = False
        if collection_name not in collections:
            if sparse_model is not None:
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config={
                        "dense": VectorParams(
                            size=vector_dimension,
                            distance=Distance.COSINE,
                        ),
                    },
                    sparse_vectors_config={
                        "sparse": SparseVectorParams(),
                    },
                )
                collection_supports_sparse = True
            else:
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=vector_dimension,
                        distance=Distance.COSINE,
                    ),
                )
        else:
            try:
                collection_info = client.get_collection(collection_name=collection_name)
                params = collection_info.config.params
                vectors_config = getattr(params, "vectors", None)
                sparse_config = getattr(params, "sparse_vectors", None)
                collection_supports_sparse = (
                    isinstance(vectors_config, dict)
                    and "dense" in vectors_config
                    and isinstance(sparse_config, dict)
                    and "sparse" in sparse_config
                )
            except Exception:
                collection_supports_sparse = False

        QdrantService.ensure_payload_indexes(
            collection_name=collection_name,
            fields=(
                "CompanyId",
                "TenderId",
                "DocumentId",
                "DocumentClassification",
                "DocumentExtension",
                "ChunkId",
                "ContentType",
                "IsTable",
            ),
            client=client,
        )

        # 7. Batch Generate Embeddings (Much faster than looping embed_query)
        texts_to_embed = [chunk_text for _, chunk_text in chunks_with_text]
        started_at = time.perf_counter()
        vectors = embedding_model.embed_documents(texts_to_embed)
        sparse_vectors = (
            list(sparse_model.embed(texts_to_embed))
            if sparse_model is not None and collection_supports_sparse
            else None
        )
        duration_ms = (time.perf_counter() - started_at) * 1000

        usage = getattr(embedding_model, "last_usage", None)
        if usage is not None:
            usage_context = usage_context or {}
            input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            total_tokens = int(getattr(usage, "total_tokens", input_tokens) or 0)
            model = getattr(embedding_model, "model", "")
            cost = TokenUsageService.calculate_token_cost(
                model=model,
                input_tokens=input_tokens,
                output_tokens=0,
            )
            await TokenUsageService.log_usage(
                {
                    "applicationName": usage_context.get("applicationName", "Tender"),
                    "sourceIds": usage_context.get("sourceIds", []),
                    "runId": usage_context.get("runId"),
                    "userId": usage_context.get("userId"),
                    "purpose": usage_context.get("purpose"),
                    "method": "GenerateEmbeddingsUsingConfiguredProvider",
                    "agentName": (
                        "Tender Document Embedding Agent"
                        if tender_id
                        else "Company Document Embedding Agent"
                    ),
                    "usageType": "embedding",
                    "inputToken": input_tokens,
                    "outputToken": 0,
                    "totalTokens": total_tokens,
                    "model": model,
                    "duration": duration_ms,
                    "cost": cost,
                    "companyId": usage_context.get("companyId", company_id),
                    "tenderId": usage_context.get("tenderId", tender_id),
                    "projectId": usage_context.get("projectId"),
                },
                bearer_token=usage_context.get("bearerToken"),
            )

        # 8. Process Chunks and Formulate the Payload
        points = []

        for idx, (chunk, chunk_text) in enumerate(chunks_with_text):
            vector = vectors[idx]
            if sparse_vectors is not None:
                vector = {
                    "dense": vectors[idx],
                    "sparse": DocumentEmbedder.to_qdrant_sparse_vector(sparse_vectors[idx]),
                }

            related_sections = DocumentEmbedder.extract_related_sections(chunk.metadata)
            page_number = (
                DocumentEmbedder.extract_page_number(chunk.metadata)
                or DocumentEmbedder.extract_page_number_from_text(chunk.page_content)
                or 1
            )
            content_type = chunk.metadata.get("ContentType", "Text")

            # Automatically generate the related section string from markdown metadata
            resolved_section = " > ".join(related_sections) if related_sections else "General"

            chunk_id = str(uuid.uuid4())
            payload = {
                "DocumentId": document_id,
                "CompanyId": company_id,
                "DocumentName": document_name,
                "DocumentExtension": document_extension,
                "Title": title,
                "Text": chunk_text,
                "PageNumber": page_number,
                "ChunkId": chunk_id,
                "ChunkIndex": idx,
                # "ContentType": content_type,
                "IsTable": content_type == "Table",
                "DocumentClassification": document_type,
                "CreatedBy": created_by,
                "CreatedAt": created_at,
                "RelatedSection": resolved_section,
            }

            if document_scope == "tender":
                payload["TenderId"] = tender_id

            payload = {
                key: value for key, value in payload.items() if value is not None
            }

            points.append(
                PointStruct(
                    id=chunk_id,
                    vector=vector,
                    payload=payload,
                )
            )

        # Upsert batch to Qdrant
        client.upsert(
            collection_name=collection_name,
            points=points,
        )

        print(f"Uploaded {len(points)} chunks to '{collection_name}' with DocumentId: {document_id}")
        return document_id

    @staticmethod
    def search_similarity(
        client: QdrantClient,
        collection_name: str,
        query_vector: List[float],
        limit: int = 5,
        metadata_filter: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Searches for similar vectors within a given collection instance."""
        query_filter = None

        if metadata_filter:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key=k,
                        match=MatchValue(value=v)
                    )
                    for k, v in metadata_filter.items()
                ]
            )

        results = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            using=DocumentEmbedder.get_query_vector_name(
                client=client,
                collection_name=collection_name,
            ),
            query_filter=query_filter,
            limit=limit,
            with_payload=True
        )

        return [
            {
                "id": p.id,
                "score": p.score,
                "payload": p.payload
            }
            for p in results.points
        ]
