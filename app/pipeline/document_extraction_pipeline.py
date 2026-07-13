from pathlib import Path
from app.services.document_processing.doc_processing import DoclingService
from app.services.embedding.embedding_services import DocumentEmbedder
from app.services.mongo.mongo_services import MongoService
from app.services.qdrant.qdrant_services import QdrantService
from app.infrastrature.agents.doc_classifier_agent import document_classifier_agent
from dotenv import load_dotenv
load_dotenv()


async def process_document(
    pdf_path: str,
    document_scope: str,  # company | tender
    company_id: str | None,
    created_by: str | None,
    created_at: str,
    # document_type: str = "",
    tender_id: str | None = None,
    source_filename: str | None = None,
    usage_context: dict | None = None,
    delete_source_file: bool = True,
    mongo_document_id: str | None = None,
    blob_id: str | None = None,
    document_id: str | None = None,
    # document_id_field: str | None = None,
    collection_name: str | None = None,
    existing_document: dict | None = None,
):
    pdf_file_path = Path(pdf_path)
    document_name = Path(source_filename or pdf_path).name

    output_dir = Path("app/infrastrature/documents/out_doc")
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = output_dir / f"{pdf_file_path.stem}.md"

    try:
        client = QdrantService.get_client()
        docling = DoclingService()
        mongo = MongoService()

        markdown_path = docling.convert_pdf_to_markdown(
            input_file=pdf_file_path,
            output_md_path=markdown_path,
        )

        metadata = docling.extract_markdown_metadata(markdown_path)
        metadata["source_file_name"] = document_name
        metadata["source_file_extension"] = pdf_file_path.suffix.lstrip(".").lower()
        classification_set = mongo.get_classification_set(tender_id=tender_id) if tender_id else []
        classification_response = await document_classifier_agent(
            document_metadata=metadata,
            classification_set=classification_set,
            usage_context=usage_context,
        )
        classification_data = classification_response.get("data", classification_response)
        mongo.save_document_classification(
            tender_id=tender_id,
            company_id=company_id,
            document_metadata=metadata,
            classifier_response=classification_data,
            mongo_document_id=mongo_document_id,
            blob_id=blob_id,
            document_id=document_id,
            collection_name=collection_name,
            created_by=created_by,
            created_at=created_at,
            existing_document=existing_document,
        )

        qdrant_document_scope = "tender" if tender_id else "company"
        classified_document_type = classification_data.get("document_type")

        document_id = await DocumentEmbedder.embed_markdown_document(
            file_path=str(markdown_path),
            # Old behavior: use document_scope passed in the API request.
            # document_scope=document_scope,
            document_scope=qdrant_document_scope,
            company_id=company_id,
            document_name=document_name,
            # Old behavior: use document_type passed in the API request.
            # document_type=document_type,
            document_type=classified_document_type,
            created_by=created_by,
            created_at=created_at,
            tender_id=tender_id,
            client=client,
            usage_context=usage_context,
            document_id=document_id,
        )

        mongo.mark_document_processed(
            tender_id=tender_id,
            mongo_document_id=mongo_document_id,
            blob_id=blob_id,
            document_id=document_id,
            collection_name=collection_name,
            modified_by=created_by,
        )

        return document_id

    finally:
        temporary_paths = [markdown_path]
        if delete_source_file:
            temporary_paths.append(pdf_file_path)

        for temporary_path in temporary_paths:
            try:
                if temporary_path.exists():
                    temporary_path.unlink()
            except OSError as e:
                print(f"Could not delete temporary file {temporary_path}: {e}")
                                                       
