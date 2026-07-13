import json
import os
import httpx
import logging
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")
logger = logging.getLogger(__name__)


DEFAULT_MODEL_PRICING_USD_PER_1M = {
    # OpenAI chat models. Prices are USD per 1M input/output tokens.
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # OpenAI embedding models. Embeddings charge input tokens only.
    "text-embedding-3-small": {"input": 0.02, "output": 0.00},
    "text-embedding-3-large": {"input": 0.13, "output": 0.00},
    "text-embedding-ada-002": {"input": 0.10, "output": 0.00},
    # Mistral common hosted models.
    "mistral-large-latest": {"input": 2.00, "output": 6.00},
    "mistral-small-latest": {"input": 0.10, "output": 0.30},
    "mistral-embed": {"input": 0.10, "output": 0.00},
}


class TokenUsageService:
    @staticmethod
    def _normalize_model_name(model: Any) -> str:
        return str(model or "").strip().lower()

    @staticmethod
    def _get_model_pricing() -> dict:
        pricing = dict(DEFAULT_MODEL_PRICING_USD_PER_1M)
        custom_pricing = os.getenv("AI_MODEL_PRICING_USD_PER_1M")

        if not custom_pricing:
            return pricing

        try:
            for model, rates in json.loads(custom_pricing).items():
                model_name = TokenUsageService._normalize_model_name(model)
                pricing[model_name] = {
                    "input": float(rates.get("input", 0) or 0),
                    "output": float(rates.get("output", 0) or 0),
                }
        except (TypeError, ValueError, json.JSONDecodeError) as ex:
            logger.warning("Invalid AI_MODEL_PRICING_USD_PER_1M: %s", ex)

        return pricing

    @staticmethod
    def calculate_token_cost(
        *,
        model: Any,
        input_tokens: int = 0,
        output_tokens: int = 0,
        currency: str = "USD",
    ) -> dict:
        model_name = TokenUsageService._normalize_model_name(model)
        rates = TokenUsageService._get_model_pricing().get(model_name)

        if not rates:
            logger.warning("Token cost pricing not configured for model: %s", model)
            return {
                "currency": currency,
                "value": 0,
            }

        input_cost = (int(input_tokens or 0) / 1_000_000) * rates["input"]
        output_cost = (int(output_tokens or 0) / 1_000_000) * rates["output"]

        return {
            "currency": currency,
            "value": round(input_cost + output_cost, 8),
        }

    @staticmethod
    def _get_usage_log_api_url() -> Optional[str]:
        api_url = (
            os.getenv("AI_USAGE_LOG_API")
            or os.getenv("TOKEN_USAGE_LOG_API")
            or os.getenv("TOKEN_USAGE")
            or os.getenv("Token_UASAGE")
            or os.getenv("Token_USAGE")
        )

        if not api_url:
            return None

        return api_url.strip().strip("\"'")

    @staticmethod
    def _required_string(value: Any) -> str:
        if value is None:
            return "NA"

        value = str(value).strip()
        return value or "NA"

    @staticmethod
    def _optional_string(value: Any) -> Optional[str]:
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    @staticmethod
    def _source_id(payload: dict, source_type: str) -> Optional[str]:
        for source in payload.get("sourceIds") or []:
            if not isinstance(source, dict):
                continue

            if str(source.get("sourceIdType") or "").lower() == source_type:
                return TokenUsageService._optional_string(source.get("id"))

        return None

    @staticmethod
    def _normalize_usage_payload(payload: dict) -> dict:
        normalized_payload = dict(payload)
        company_id = (
            TokenUsageService._optional_string(payload.get("companyId"))
            or TokenUsageService._optional_string(payload.get("CompanyId"))
            or TokenUsageService._source_id(payload, "company")
        )
        tender_id_value = (
            TokenUsageService._optional_string(payload.get("tenderId"))
            or TokenUsageService._optional_string(payload.get("TenderId"))
            or TokenUsageService._source_id(payload, "tender")
        )

        user_id = TokenUsageService._required_string(
            payload.get("userId") or payload.get("UserId")
        )
        tender_id = TokenUsageService._required_string(tender_id_value)
        project_id = TokenUsageService._required_string(
            payload.get("projectId") or payload.get("ProjectId")
        )

        if company_id:
            normalized_payload["companyId"] = company_id
            normalized_payload["CompanyId"] = company_id

        normalized_payload["userId"] = user_id
        normalized_payload["tenderId"] = tender_id
        normalized_payload["projectId"] = project_id
        normalized_payload["UserId"] = user_id
        normalized_payload["TenderId"] = tender_id
        normalized_payload["ProjectId"] = project_id

        return normalized_payload

    @staticmethod
    def _get_value(source: Any, key: str, default: Any = None) -> Any:
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default)

    @staticmethod
    def extract_token_usage(response: Any) -> dict:
        metadata = (
            TokenUsageService._get_value(response, "response_metadata", {}) or {}
        )

        usage = (
            TokenUsageService._get_value(response, "usage_metadata", None)
            or metadata.get("token_usage")
            or metadata.get("usage")
            or {}
        )

        input_tokens = (
            TokenUsageService._get_value(usage, "input_tokens", None)
            or TokenUsageService._get_value(usage, "prompt_tokens", None)
            or 0
        )

        output_tokens = (
            TokenUsageService._get_value(usage, "output_tokens", None)
            or TokenUsageService._get_value(usage, "completion_tokens", None)
            or 0
        )

        total_tokens = (
            TokenUsageService._get_value(usage, "total_tokens", None)
            or input_tokens + output_tokens
        )

        model = (
            metadata.get("model_name")
            or metadata.get("model")
            or TokenUsageService._get_value(response, "model_name", "")
            or ""
        )

        return {
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "total_tokens": int(total_tokens or 0),
            "model": model,
        }

    @staticmethod
    async def log_usage(payload: dict, bearer_token: Optional[str] = None):
        api_url = TokenUsageService._get_usage_log_api_url()

        if not api_url:
            logger.warning("Token usage logging skipped: AI_USAGE_LOG_API is not configured")
            return None

        headers = {}
        if bearer_token:
            token = bearer_token.strip()
            if token.lower().startswith("bearer "):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Bearer {token}"
        else:
            logger.warning("Token usage logging skipped: bearer_token is required")
            return None

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                payload = TokenUsageService._normalize_usage_payload(payload)
                response = await client.post(api_url, json=payload, headers=headers)

                if response.status_code == 404:
                    alternate_api_url = (
                        api_url.rstrip("/")
                        if api_url.endswith("/")
                        else f"{api_url}/"
                    )

                    if alternate_api_url != api_url:
                        response = await client.post(
                            alternate_api_url,
                            json=payload,
                            headers=headers,
                        )

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as ex:
                logger.warning(
                    "Token usage logging failed with status %s: %s",
                    ex.response.status_code,
                    ex.response.text,
                )
                return {
                    "success": False,
                    "status_code": ex.response.status_code,
                    "message": "Token usage logging failed",
                }

            except httpx.HTTPError as ex:
                logger.warning("Token usage logging request failed: %s", ex)
                return {
                    "success": False,
                    "message": "Token usage logging request failed",
                }
                
 
 
 
######################################## Token Uasge ########################################
 
                
# usage = TokenUsageService.extract_token_usage(response)

# await TokenUsageService.log_usage(
#     payload=usage,
#     bearer_token=token,
#
