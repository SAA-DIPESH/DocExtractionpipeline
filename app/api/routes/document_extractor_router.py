import json
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Annotated, List, Literal, Optional

from app.pipeline.document_extraction_pipeline import process_document
from pathlib import Path
from dotenv import load_dotenv
from app.services.embedding.embedding_services import DocumentEmbedder
from app.services.mongo.mongo_services import MongoService
from app.services.qdrant.qdrant_services import QdrantService
router = APIRouter(
    prefix="/documents",
    tags=["Document Extraction"]
)


class DocumentMetadata(BaseModel):
    pdf_path: str
    document_scope: Literal["company", "tender"]

    created_by: Optional[str] = None
    user_name: Optional[str] = None
    created_at: str
    tender_id: Optional[str] = None
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    purpose: Optional[str] = None

class DocumentBatchRequest(BaseModel):
    documents: List[DocumentMetadata]


class UploadedDocumentMetadata(BaseModel):
    document_scope: Literal["company", "tender"]
    company_id: Optional[str] = None

    created_by: Optional[str] = None
    user_name: Optional[str] = None
    created_at: str
    tender_id: Optional[str] = None
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    purpose: Optional[str] = None
    bearer_token: Optional[str] = None


class MongoDocumentProcessRequest(BaseModel):
    tender_id: Optional[str] = None
    company_id: Optional[str] = None
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    created_by: Optional[str] = None
    user_name: Optional[str] = None
    bearer_token: Optional[str] = None


def clean_optional_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


# Old code: this worked when the API received pdf_path values in JSON.
# @router.post("/process")
# def process_documents(request: DocumentBatchRequest):
#
#     results = []
#
#     for document in request.documents:
#         try:
#             document_id = process_document(
#                 pdf_path=document.pdf_path,
#                 document_scope=document.document_scope,
#                 company_id=document.company_id,
#                 tender_id=document.tender_id,
#                 document_name=document.document_name,
#                 title=document.title,
#                 document_type=document.document_type,
#                 created_by=document.created_by,
#                 created_at=document.created_at,
#             )
#
#             results.append({
#                 "document_name": document.document_name,
#                 "document_id": document_id,
#                 "status": "Success"
#             })
#
#         except Exception as e:
#             results.append({
#                 "document_name": document.document_name,
#                 "status": "Failed",
#                 "error": str(e)
#             })
#
#     return {
#         "success": True,
#         "total_documents": len(request.documents),
#         "results": results
#     }

def parse_documents_metadata(documents: str) -> List[UploadedDocumentMetadata]:
    try:
        documents_data = json.loads(documents)
        if isinstance(documents_data, dict):
            documents_data = [documents_data]
        if not isinstance(documents_data, list):
            raise ValueError("documents must be a JSON object or a JSON array")
        return [UploadedDocumentMetadata(**document) for document in documents_data]
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid documents metadata JSON: {e}",
        )


@router.post("/process")
async def process_documents(
    files: Annotated[List[UploadFile], File()],
    documents: Annotated[str, Form()],
):
    run_id = str(uuid4())
    print(f"RunId: {run_id}")

    metadata_list = parse_documents_metadata(documents)

    if len(metadata_list) == 1 and len(files) > 1:
        metadata_list = metadata_list * len(files)

    if len(files) != len(metadata_list):
        raise HTTPException(
            status_code=400,
            detail=(
                "Number of uploaded files must match number of document metadata records, "
                "or pass a single metadata object to apply it to every file."
            ),
        )

    input_dir = Path("app/infrastrature/documents/input_doc")
    input_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for file, document in zip(files, metadata_list):
        source_filename = Path(file.filename or "document.pdf").name
        saved_path = input_dir / f"{uuid4().hex}_{source_filename}"

        try:
            with saved_path.open("wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            source_id_type = (
                "tender"
                if document.tender_id
                else "company"
                if document.company_id
                else None
            )
            source_id = document.tender_id or document.company_id
            usage_context = {
                "applicationName": "Tender",
                "runId": run_id,
                "companyId": document.company_id,
                "tenderId": document.tender_id,
                "projectId": document.project_id,
                "userId": document.user_id,
                "userName": clean_optional_string(document.user_name),
                "purpose": document.purpose or "document_upload",
                "bearerToken": clean_optional_string(document.bearer_token),
                "sourceIds": [
                    {
                        "sourceIdType": source_id_type,
                        "id": source_id,
                    }
                ],
            }

            document_id = await process_document(
                pdf_path=str(saved_path),
                document_scope=document.document_scope,
                company_id=document.company_id,
                tender_id=document.tender_id,
                # document_type=document.document_type,
                created_by=(
                    clean_optional_string(document.created_by)
                    or clean_optional_string(document.user_name)
                ),
                created_at=document.created_at,
                source_filename=source_filename,
                usage_context=usage_context,
            )

            results.append({
                "document_name": source_filename,
                "document_id": document_id,
                "status": "Success"
            })

        except Exception as e:
            results.append({
                "document_name": source_filename,
                "status": "Failed",
                "error": str(e)
            })

        finally:
            await file.close()

    return {
        "success": True,
        "runId": run_id,
        "total_documents": len(metadata_list),
        "results": results
    }


@router.post("/process/ocr/using_Tenderid_or_Companyid")
async def process_documents_from_mongo(request: MongoDocumentProcessRequest):
    tender_id = clean_optional_string(request.tender_id)
    company_id = clean_optional_string(request.company_id)
    project_id = clean_optional_string(request.project_id)
    user_id = clean_optional_string(request.user_id)
    created_by = (
        clean_optional_string(request.created_by)
        or clean_optional_string(request.user_name)
    )
    bearer_token = clean_optional_string(request.bearer_token)

    if bool(tender_id) == bool(company_id):
        raise HTTPException(
            status_code=400,
            detail="Pass exactly one of tender_id or company_id.",
        )

    run_id = str(uuid4())
    document_scope = "tender" if tender_id else "company"
    source_id = tender_id or company_id
    created_at = datetime.utcnow().isoformat()

    try:
        mongo = MongoService()
        mongo_documents = mongo.get_documents_for_processing(
            tender_id=tender_id,
            company_profile_id=company_id,
        )
        debug_counts = None
        if not mongo_documents:
            debug_counts = mongo.get_processing_match_counts(
                tender_id=tender_id,
                company_profile_id=company_id,
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to fetch documents from MongoDB: {e}",
        )

    results = []

    for mongo_document in mongo_documents:
        file_path = Path(mongo_document["file_path"])
        document_name = mongo_document.get("document_name") or file_path.name
        resolved_company_id = (
            clean_optional_string(mongo_document.get("company_id"))
            or company_id
        )
        resolved_tender_id = tender_id if document_scope == "tender" else None

        if document_scope == "tender":
            resolved_tender_id = (
                clean_optional_string(mongo_document.get("tender_id"))
                or tender_id
            )

        if not file_path.exists():
            results.append(
                {
                    "document_name": document_name,
                    "file_path": str(file_path),
                    "status": "Failed",
                    "error": "FilePath does not exist locally.",
                }
            )
            continue

        usage_context = {
            "applicationName": "Tender",
            "runId": run_id,
            "companyId": resolved_company_id,
            "tenderId": resolved_tender_id,
            "projectId": project_id,
            "userId": user_id,
            "userName": clean_optional_string(request.user_name),
            "purpose": "document_mongo_processing",
            "bearerToken": bearer_token,
            "sourceIds": [
                {
                    "sourceIdType": document_scope,
                    "id": source_id,
                }
            ],
        }

        try:
            document_id = await process_document(
                pdf_path=str(file_path),
                document_scope=document_scope,
                company_id=resolved_company_id,
                tender_id=resolved_tender_id,
                created_by=created_by or mongo_document.get("created_by"),
                created_at=created_at,
                source_filename=document_name,
                usage_context=usage_context,
                delete_source_file=False,
                mongo_document_id=mongo_document.get("mongo_document_id"),
                blob_id=mongo_document.get("blob_id"),
                document_id=mongo_document.get("document_id"),
                collection_name=mongo_document.get("collection_name"),
                existing_document=mongo_document.get("existing_document"),
            )

            results.append(
                {
                    "document_name": document_name,
                    "file_path": str(file_path),
                    "document_id": document_id,
                    "mongo_document_id": mongo_document.get("mongo_document_id"),
                    "blob_id": mongo_document.get("blob_id"),
                    "status": "Success",
                }
            )
        except Exception as e:
            results.append(
                {
                    "document_name": document_name,
                    "file_path": str(file_path),
                    "mongo_document_id": mongo_document.get("mongo_document_id"),
                    "document_id": mongo_document.get("document_id"),
                    "blob_id": mongo_document.get("blob_id"),
                    "status": "Failed",
                    "error": str(e),
                }
            )

    response = {
        "success": True,
        "runId": run_id,
        "document_scope": document_scope,
        "total_documents": len(mongo_documents),
        "results": results,
    }
    if debug_counts:
        response["debug"] = debug_counts

    return response





@router.get("/health")
def health():
    return {
        "success": True,
        "message": "Document Extraction Service is running."
    }





load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

################################################################  Retrival api code   ################################################################

class RetrievalRequest(BaseModel):
    collection_name: str
    company_id: str
    query: str
    limit: int = 5


@router.post("/retrieve")
def retrieve_context(request: RetrievalRequest):
    try:
        embedding_model = DocumentEmbedder.get_embedding_model()

        query_vector = embedding_model.embed_query(request.query)

        results = QdrantService.search_similarity(
            collection_name=request.collection_name,
            query_vector=query_vector,
            limit=request.limit,
            metadata_filter={
                "CompanyId": request.company_id
            }
        )

        response = []

        for result in results:
            payload = result["payload"]

            response.append({
                "score": round(result["score"], 4),
                "company_id": payload.get("CompanyId"),
                "tender_id": payload.get("TenderId"),
                "document_id": payload.get("DocumentId"),
                "chunk_id": payload.get("ChunkId"),
                "document_name": payload.get("DocumentName"),
                "text": payload.get("Text")
            })

        return {
            "success": True,
            "query": request.query,
            "total_results": len(response),
            "results": response
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
