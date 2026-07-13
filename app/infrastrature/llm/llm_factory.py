from dotenv import load_dotenv
import os
load_dotenv()
from langchain_mistralai import ChatMistralAI
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from bson import ObjectId
from app.utils.decrept import decrypt
# from app.services.mongo import _get_database
from app.services.mongo.mongo_client import get_document


def _load_llm(provider: str | None = None):
    provider = (provider or os.getenv("LLM_PROVIDER", "mistral")).lower()

    if provider == "openai":
        openai_api_key = os.getenv("OPENAI_API_KEY")

        if not openai_api_key:
            security_doc = get_document(
                collection_name="Security",
                filter_query={
                    "_id": ObjectId("6a3944f958430082848fc63d")
                }
            )

            if not security_doc:
                raise Exception("Security document not found")

            encrypted_key = security_doc.get("Security")

            if not encrypted_key:
                raise Exception("Security field not found")

            openai_api_key = decrypt(encrypted_key)
     
        # Fixed: Changed from self.llm to a standard return statement
        return ChatOpenAI(
            model=os.getenv(
                "LLM_MODEL",
                "gpt-4.1"
            ),
            temperature=0,
            api_key=openai_api_key
        )

    elif provider == "mistral":
        return ChatMistralAI(
            model=os.getenv("MISTRAL_MODEL", "mistral-large-latest"),
            temperature=float(os.getenv("LLM_TEMPERATURE", 0)),
            api_key=os.getenv("MISTRAL_API_KEY"),
        )

    elif provider == "ollama":
        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "mistral:7b"),
            temperature=float(os.getenv("LLM_TEMPERATURE", 0)),
        )

    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")

llm = _load_llm()

