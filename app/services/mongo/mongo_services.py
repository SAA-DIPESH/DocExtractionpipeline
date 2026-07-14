import os
import re
import ntpath
from typing import Optional
from datetime import datetime
from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

############################################### Helper Functions ###############################################
def _to_document_metadata(metadata: dict) -> dict:
    return {
        "documentTitle": metadata.get("document_title"),
        "DocumentClassification": metadata.get("document_type"),
        "appendixNumber": metadata.get("appendix_number"),
        "summary": metadata.get("summary"),
        "pageCount": metadata.get("page_count"),
        "tableCount": metadata.get("table_count"),
        # "imageCount": metadata.get("image_count"),
        "mainHeadings": metadata.get("main_headings", []),
        "sectionTitles": metadata.get("section_titles", []),
        "keywords": metadata.get("keywords", []),
        "topNgrams": metadata.get("top_ngrams", []),
        # "namedEntities": metadata.get("named_entities", []),
        "tableHeaders": metadata.get("table_headers", []),
        "processingStatus": metadata.get("processing_status"),
    }


def _first_value(document: dict, *keys: str):
    for key in keys:
        value = document.get(key)
        if value is not None:
            return value
    return None


def _first_present_key(document: dict, *keys: str) -> str | None:
    for key in keys:
        if key in document:
            return key
    return None


def _company_id_conditions(company_profile_id: str | None) -> list[dict]:
    return [
        {"CompanyProfileId": company_profile_id},
        {"companyProfileId": company_profile_id},
        {"CompanyProfileID": company_profile_id},
        {"companyProfileID": company_profile_id},
        {"CompanyID": company_profile_id},
        {"companyID": company_profile_id},
        {"CompanyId": company_profile_id},
        {"companyId": company_profile_id},
        {"companyid": company_profile_id},
    ]


def _tender_id_conditions(tender_id: str | None) -> list[dict]:
    return [
        {"TenderId": tender_id},
        {"tenderId": tender_id},
        {"TenderID": tender_id},
        {"tenderID": tender_id},
    ]


def _document_lookup_query(
    tender_id: str | None,
    company_profile_id: str | None,
) -> tuple[str, dict]:
    if not tender_id and not company_profile_id:
        raise ValueError("Pass tender_id, company_profile_id, or both")

    if tender_id:
        filters = [{"$or": _tender_id_conditions(tender_id)}]
        if company_profile_id:
            filters.append({"$or": _company_id_conditions(company_profile_id)})

        return "CPTenderDocuments", filters[0] if len(filters) == 1 else {"$and": filters}

    return "CPDocuments", {"$or": _company_id_conditions(company_profile_id)}


def _eligible_document_conditions() -> list[dict]:
    return [
        {
            "$or": [
                {"IsActive": False},
                {"IsActive": 0},
                {"isActive": False},
                {"isActive": 0},
            ],
        },
    ]


def _join_values(values: list) -> str:
    return ", ".join(str(value) for value in values if value)


def _to_document_description(metadata: dict) -> str:
    rows = [
        ("File Name", metadata.get("source_file_name") or metadata.get("file_name")),
        ("Document Title", metadata.get("document_title")),
        ("Main Headings", _join_values(metadata.get("main_headings", []))),
        ("Section Titles", _join_values(metadata.get("section_titles", []))),
        ("Keywords", _join_values(metadata.get("keywords", []))),
        ("Top Ngrams", _join_values(metadata.get("top_ngrams", []))),
        ("Table Headers", _join_values(metadata.get("table_headers", []))),
        ("Page Count", metadata.get("page_count")),
        ("Table Count", metadata.get("table_count")),
        # ("Image Count", metadata.get("image_count")),
    ]
    return "\n".join(
        f"{label}: {value}"
        for label, value in rows
        if value not in (None, "", [])
    )


def _to_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return value
    return value


def _find_matching_local_file(directory: str, document_name: str | None) -> str | None:
    if not document_name or not os.path.isdir(directory):
        return None

    schedule_match = re.search(r"\bD\.\d+(?:\.\d+)*\b", document_name, re.IGNORECASE)
    version_match = re.search(r"\bv\d+(?:\.\d+)*\b", document_name, re.IGNORECASE)

    if not schedule_match:
        return None

    schedule_token = schedule_match.group(0).lower()
    version_token = version_match.group(0).lower() if version_match else None
    matches = []

    for filename in os.listdir(directory):
        if not filename.lower().endswith(".pdf"):
            continue

        normalized_filename = filename.lower()
        if schedule_token not in normalized_filename:
            continue

        if version_token and version_token not in normalized_filename:
            continue

        matches.append(os.path.join(directory, filename))

    return matches[0] if len(matches) == 1 else None


def _has_drive_or_unc_root(file_path: str) -> bool:
    windows_drive, _ = ntpath.splitdrive(file_path)
    return bool(windows_drive) or file_path.startswith("\\\\")


def _apply_document_base_path(file_path: str) -> str:
    document_base_path = os.getenv("DOCUMENT_BASE_PATH", "").strip()
    if _has_drive_or_unc_root(file_path):
        return file_path

    if not document_base_path:
        return file_path

    relative_file_path = file_path.lstrip("/\\")
    return os.path.join(document_base_path, relative_file_path)


def _looks_like_file_path(file_path: str, document_name: str | None, blob_id: str | None) -> bool:
    file_name = os.path.basename(file_path.rstrip("/\\"))
    if document_name and file_name.lower() == document_name.lower():
        return True

    if blob_id and file_name.lower() == os.path.basename(blob_id).lower():
        return True

    return bool(os.path.splitext(file_name)[1])


def _resolve_local_file_path(file_path: str, document_name: str | None, blob_id: str | None) -> str:
    if not file_path:
        return file_path

    file_path = _apply_document_base_path(file_path)

    if os.path.isfile(file_path):
        return file_path

    if _looks_like_file_path(file_path, document_name, blob_id):
        return file_path

    if document_name:
        candidate = os.path.join(file_path, document_name)
        if os.path.exists(candidate):
            return candidate

    if blob_id:
        candidate = os.path.join(file_path, os.path.basename(blob_id))
        if os.path.exists(candidate):
            return candidate

    matching_file = _find_matching_local_file(file_path, document_name)
    if matching_file:
        return matching_file

    if document_name:
        return os.path.join(file_path, document_name)

    if blob_id:
        return os.path.join(file_path, os.path.basename(blob_id))

    return file_path


class MongoService:
    """
    Service for retrieving document taxonomy from MongoDB.
    """

    DATABASE_NAME = "DocAI"
    COLLECTION_NAME = "DocumentTaxonomies"

    def __init__(self):
        mongo_url = os.getenv("MONGODB_URL")

        if not mongo_url:
            raise ValueError("MONGODB_URL not found in .env")

        self.client = MongoClient(mongo_url)
        self.db = self.client[self.DATABASE_NAME]
        self.collection = self.db[self.COLLECTION_NAME]

    def get_classification_set(
        self,
        tender_id: str,
    ) -> list[dict]:
       
        document = self.collection.find_one(
            {
                "$or": [
                    {"tenderId": tender_id},
                    {"TenderId": tender_id},
                    {"TenderID": tender_id},
                    {"tenderID": tender_id},
                ],
            },
            {
                "_id": 0,
                "classificationSet.code": 1,
                "classificationSet.name": 1,
                "classificationSet.expectedSignals": 1,
            },
        )

        if not document:
            return []

        return document.get("classificationSet", [])

    def save_document_classification(
        self,
        *,
        tender_id: str,
        company_id: Optional[str],
        document_metadata: dict,
        classifier_response: dict,
        mongo_document_id: Optional[str] = None,
        blob_id: Optional[str] = None,
        document_id: Optional[str] = None,
        collection_name: Optional[str] = None,
        existing_document: Optional[dict] = None,
        created_by: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> str:
        """
        Saves the document metadata along with the classifier output.

        Args:
            tender_id: Tender ID.
            company_id: Company ID.
            document_metadata: Metadata extracted from the markdown.
            classifier_response: Output from the Document Classification Agent.

        Returns:
            Updated document id or lookup key.
        """

        collection_name = collection_name or ("CPTenderDocuments" if tender_id else "CPDocuments")
        collection = self.db[collection_name]
        now = datetime.utcnow()
        existing_document = existing_document or {}
        extracted_text_preview = document_metadata.get("summary")
        ocr_summary = _to_document_description(document_metadata)
        document_name = (
            document_metadata.get("source_file_name")
            or document_metadata.get("file_name")
            or _first_value(existing_document, "DocumentName", "documentName", "FileName", "fileName")
        )
        document_file_type = (
            document_metadata.get("source_file_extension") or ""
        ).upper()
        document_id_value = (
            document_id
            or _first_value(existing_document, "DocumentId", "DocumentID", "documentId", "fileId")
            or document_metadata.get("file_stem")
        )
        resolved_blob_id = blob_id or _first_value(existing_document, "BlobId", "blobId")
        created_by_value = (
            _first_value(existing_document, "CreatedBy", "createdBy")
            or created_by
        )

        filters = []
        if mongo_document_id:
            filters.append({"_id": mongo_document_id})
            try:
                filters.append({"_id": ObjectId(mongo_document_id)})
            except Exception:
                pass
        if document_id_value:
            filters.append({"DocumentId": document_id_value})
            filters.append({"DocumentID": document_id_value})
            filters.append({"documentId": document_id_value})
        if blob_id:
            filters.append({"BlobId": blob_id})
            filters.append({"blobId": blob_id})

        if filters:
            update_document = {
                "DocumentDescription": extracted_text_preview,
                "OCRSummary": ocr_summary,
                # "SummarizeContent": document_metadata.get("summary"),
                "DocumentClassification": classifier_response.get("document_type"),
                "DocumentFileType": document_file_type,
                "ClassificationScore": classifier_response.get("classification_confidence"),
                "DocumentRelevanceScore": classifier_response.get("relevance_score"),
                "ClassificationReason": classifier_response.get("reason"),
                "Status": "Processing",
                "IsLoadedByAI": False,
                "ModifiedAt": now,
            }
            if created_by_value:
                update_document["ModifiedBy"] = created_by_value
            if document_id_value:
                update_document["DocumentId"] = document_id_value
            if tender_id:
                update_document["TenderId"] = tender_id
            if company_id:
                company_id_field = _first_present_key(
                    existing_document,
                    "CompanyProfileId",
                    "companyProfileId",
                    "CompanyProfileID",
                    "companyProfileID",
                    "CompanyID",
                    "companyID",
                    "CompanyId",
                    "companyId",
                    "companyid",
                ) or "CompanyId"
                update_document[company_id_field] = company_id
            if resolved_blob_id:
                update_document["BlobId"] = resolved_blob_id
            if document_name:
                update_document["DocumentName"] = document_name
            update_document = {
                key: value for key, value in update_document.items() if value is not None
            }
            result = collection.update_one(
                {"$or": filters},
                {
                    "$set": update_document,
                    # "$unset": {
                    #     "AIIsLoadByAgent": "",
                    #     "aiIsLoadByAgent": "",
                    # },
                },
                upsert=False,
            )
            if result.matched_count:
                return mongo_document_id or blob_id or ""

        raise ValueError(
            f"Mongo update matched 0 documents in {collection_name}. "
            f"mongo_document_id={mongo_document_id}, document_id={document_id_value}, blob_id={blob_id}"
        )

    def mark_document_processed(
        self,
        *,
        tender_id: str | None,
        mongo_document_id: Optional[str] = None,
        blob_id: Optional[str] = None,
        document_id: Optional[str] = None,
        collection_name: Optional[str] = None,
        modified_by: Optional[str] = None,
    ) -> bool:
        collection_name = collection_name or ("CPTenderDocuments" if tender_id else "CPDocuments")
        collection = self.db[collection_name]
        filters = []

        if mongo_document_id:
            filters.append({"_id": mongo_document_id})
            try:
                filters.append({"_id": ObjectId(mongo_document_id)})
            except Exception:
                pass
        if document_id:
            filters.append({"DocumentId": document_id})
            filters.append({"DocumentID": document_id})
            filters.append({"documentId": document_id})
        if blob_id:
            filters.append({"BlobId": blob_id})
            filters.append({"blobId": blob_id})

        if not filters:
            return False

        update_document = {
            "IsLoadedByAI": False,
            "IsActive": True,
            "Status": "Processed",
            "ModifiedAt": datetime.utcnow(),
        }
        if modified_by:
            update_document["ModifiedBy"] = modified_by

        result = collection.update_one(
            {"$or": filters},
            {
                "$set": update_document,
                # "$unset": {
                #     "AIIsLoadByAgent": "",
                #     "aiIsLoadByAgent": "",
                # },
            },
            upsert=False,
        )
        if not result.matched_count:
            raise ValueError(
                f"Final Mongo update matched 0 documents in {collection_name}. "
                f"mongo_document_id={mongo_document_id}, document_id={document_id}, blob_id={blob_id}"
            )

        return True

    def get_documents_for_processing(
        self,
        *,
        tender_id: str | None = None,
        company_profile_id: str | None = None,
    ) -> list[dict]:
        collection_name, base_query = _document_lookup_query(
            tender_id=tender_id,
            company_profile_id=company_profile_id,
        )
        query = {
            "$and": [
                base_query,
                *_eligible_document_conditions(),
            ],
        }

        documents = self.db[collection_name].find(query)
        processed_documents = []

        for document in documents:
            file_path = _first_value(document, "FilePath", "filePath", "file_path")
            if not file_path:
                continue

            resolved_company_id = _first_value(
                document,
                "CompanyProfileId",
                "companyProfileId",
                "CompanyID",
                "companyID",
                "CompanyId",
                "companyId",
                "companyid",
            )
            resolved_tender_id = _first_value(
                document,
                "TenderId",
                "tenderId",
                "TenderID",
                "tenderID",
            )
            document_name = _first_value(
                document,
                "DocumentName",
                "documentName",
                "FileName",
                "fileName",
            )
            blob_id = _first_value(document, "BlobId", "blobId")
            document_id = _first_value(
                document,
                "DocumentId",
                "DocumentID",
                "documentId",
                "fileId",
            )
            created_by = _first_value(document, "CreatedBy", "createdBy")
            resolved_file_path = _resolve_local_file_path(
                file_path=file_path,
                document_name=document_name,
                blob_id=blob_id,
            )

            processed_documents.append(
                {
                    "mongo_document_id": str(document.get("_id")),
                    "blob_id": str(blob_id) if blob_id is not None else None,
                    "document_id": str(document_id) if document_id is not None else None,
                    "file_path": resolved_file_path,
                    "document_name": document_name or os.path.basename(file_path),
                    "company_id": str(resolved_company_id) if resolved_company_id is not None else None,
                    "tender_id": str(resolved_tender_id) if resolved_tender_id is not None else tender_id,
                    "created_by": str(created_by) if created_by is not None else None,
                    "collection_name": collection_name,
                    "existing_document": document,
                }
            )

        return processed_documents

    def get_processing_match_counts(
        self,
        *,
        tender_id: str | None = None,
        company_profile_id: str | None = None,
    ) -> dict:
        collection_name, base_query = _document_lookup_query(
            tender_id=tender_id,
            company_profile_id=company_profile_id,
        )

        eligible_query = {
            "$and": [
                base_query,
                *_eligible_document_conditions(),
            ],
        }

        return {
            "collection": collection_name,
            "base_matches": self.db[collection_name].count_documents(base_query),
            "eligible_matches": self.db[collection_name].count_documents(eligible_query),
        }

    def get_document_blob_paths(
        self,
        company_profile_id: str | None = None,
        tender_id: str | None = None,
    ):
        documents = []

        if company_profile_id:
            # Replaced undefined self.company_collection with self.db lookups
            documents.extend(
                self.db["CPDocuments"].find(
                    {
                        "$or": _company_id_conditions(company_profile_id),
                        "IsActive": False,
                        "IsLoadByAI": False
                        
                        
                    },
                    {
                        "_id": 0,
                        "BlobId": '1',
                        "FilePath": 1,
                        "DocumentName": 1
                    }
                )
            )

        if tender_id:
            # Replaced undefined self.tender_collection with self.db lookups
            documents.extend(
                self.db["CPTenderDocuments"].find(
                    {
                        "TenderId": tender_id,
                        "IsActive": False,
                        "IsLoadByAI": False
                    },
                    {
                        "_id": 0,
                        "BlobId": 1,
                        "FilePath": 1,
                        "DocumentName": 1
                    }
                )
            )

        return [doc["BlobId"] for doc in documents]
    
   



# ################################################Test case #######################################################


# # mongo_service = MongoService()

# # blob_paths = mongo_service.get_document_blob_paths(
# #     tender_id="6a4506d2f4191032014315fd"
# # )

# # print(blob_paths)
