import os
import json
import logging
import requests

from dotenv import load_dotenv
from typing import Any, Dict, Optional

load_dotenv()


class AgentLogger:

    def __init__(self):
        self.log_api_url = os.getenv("LOGGER_API_URL")
        self.logger = logging.getLogger("agent_logger")

    def log_event(
        self,
        agent_name: str,
        message: str,
        event_type: str,
        source_module: str,
        is_success: bool,
        duration_ms: int = 0,
        payload: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> None:

        if not self.log_api_url:
            self.logger.error("LOGGER_API_URL not found in environment")
            return

        log_payload = {
            "agentName": agent_name,
            "message": message,
            "eventType": event_type,
            "sourceModule": source_module,
            "isSuccess": is_success,
            "durationMs": duration_ms,
            "payloadJson": json.dumps(payload or {}),
            "correlationId": correlation_id or "",
        }

        try:
            requests.post(
                self.log_api_url,
                json=log_payload,
                timeout=10
            )
        except Exception as ex:
            self.logger.error(
                f"Failed to send log event: {str(ex)}"
            )