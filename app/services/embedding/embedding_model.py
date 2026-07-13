import os
from bson import ObjectId  # Added: Needed for ObjectId() mapping

from langchain_openai import OpenAIEmbeddings
from langchain_mistralai import MistralAIEmbeddings
from langchain_ollama import OllamaEmbeddings
from openai import OpenAI
from app.utils.decrept import decrypt
# from app.services.mongo import _get_database
from app.services.mongo.mongo_client import get_document


class OpenAIEmbeddingSDKAdapter:
    def __init__(self, *, model: str, api_key: str):
        self.model = model
        self.client = OpenAI(api_key=api_key)
        self.last_usage = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(
            model=self.model,
            input=texts,
        )
        self.last_usage = response.usage
        return [item.embedding for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class EmbeddingModel:

    @staticmethod
    def get_embedding_model():
        """Returns the configured embedding model from MongoDB."""

        config = get_document(
            collection_name="EmbeddingModel",
            filter_query={"is_active": True},
        )

        if not config:
            raise Exception("No active embedding model found.")

        provider = config["provider"].lower()

        if provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")

            if not api_key:
                security_doc = get_document(
                    collection_name="Security",
                    filter_query={
                        "_id": ObjectId("6a3944f958430082848fc63d")
                    },
                )

                if not security_doc:
                    raise Exception("Security document not found.")

                encrypted_key = security_doc.get("Security")

                if not encrypted_key:
                    raise Exception("Security field not found.")

                api_key = decrypt(encrypted_key)

            # Old LangChain implementation:
            # return OpenAIEmbeddings(
            #     model=config["model"],
            #     api_key=api_key,
            # )

            return OpenAIEmbeddingSDKAdapter(
                model=config["model"],
                api_key=api_key,
            )

        elif provider == "mistral":
            return MistralAIEmbeddings(
                model=config["model"],
                api_key=os.getenv(config["api_key_env"]),
            )

        elif provider == "ollama":
            return OllamaEmbeddings(
                model=config["model"],
                base_url=config.get("base_url", "http://localhost:11434"),
            )

        raise ValueError(f"Unsupported provider: {provider}")
