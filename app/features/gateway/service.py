"""Forwarding of issuer-side wallet actions through the connector.

Credential requests, workflow-engine steps, integration KYC sessions,
and DigiLocker flows live in the DCS that issued the request. This
service owns none of that data; it adds the authenticated holder's
email and forwards the action, and the connector calls the right DCS.
List operations fan out to every source the holder is linked to.

The DCS-shaped request routes (``/v1/holder/subject/requests`` and
friends) name a request by id only. Lists are merged across sources,
and a single request is first located with the fan-out
``requests.find`` operation, then acted on at its own source.
"""

import logging
import math
from datetime import UTC, datetime
from typing import Any

from app.core.connector import (
    ConnectorClient,
    OperationResponse,
    OperationResult,
)
from app.core.exceptions import ExternalServiceError, NotFoundError
from app.features.holders.models import Holder

logger = logging.getLogger(__name__)

REQUEST_NOT_FOUND = "Request not found."
# Keys the DCS searches on in its own request list.
_SEARCH_KEYS = ("subject_name", "issuer_name", "request_id", "uuid")


def _created_at(item: dict[str, Any]) -> datetime:
    value = item.get("created_at")
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _matches(item: dict[str, Any], term: str) -> bool:
    return any(
        term in str(item.get(key) or "").lower() for key in _SEARCH_KEYS
    )


class GatewayService:
    """Runs connector operations on behalf of the signed-in holder.

    Attributes:
        connector: Client for the connector service.
    """

    def __init__(self, connector: ConnectorClient) -> None:
        self.connector = connector

    async def list_from_all_sources(
        self, holder: Holder, operation: str
    ) -> OperationResponse:
        """Run a list operation against every source of the holder."""
        return await self.connector.run_operation(holder.email, operation)

    async def run_on_source(
        self,
        holder: Holder,
        operation: str,
        source_code: str,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> OperationResponse:
        """Run an item operation against one source."""
        return await self.connector.run_operation(
            holder.email,
            operation,
            source_code=source_code,
            params=params,
            body=body,
        )

    async def list_requests(
        self,
        holder: Holder,
        page: int | None = None,
        size: int | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        """Return the holder's requests from every source, newest first.

        Each item carries its ``source_code``. A source that fails is
        left out (and logged) rather than failing the whole list.

        Returns:
            ``{subjects, total}``, plus ``page, size, pages`` when
            ``page`` and ``size`` are given, as the DCS answers.
        """
        response = await self.list_from_all_sources(holder, "requests.list")
        items: list[dict[str, Any]] = []
        for result in response.items:
            if not result.ok or not isinstance(result.data, dict):
                logger.warning(
                    "Source %s answered %s to requests.list",
                    result.source_code,
                    result.status_code,
                )
                continue
            items.extend(
                {**subject, "source_code": result.source_code}
                for subject in result.data.get("subjects") or []
                if isinstance(subject, dict)
            )
        items.sort(key=_created_at, reverse=True)
        term = (search or "").strip().lower()
        if term:
            items = [item for item in items if _matches(item, term)]
        if page is None or size is None:
            return {"subjects": items, "total": len(items)}
        start = (page - 1) * size
        return {
            "subjects": items[start : start + size],
            "total": len(items),
            "page": page,
            "size": size,
            "pages": max(1, math.ceil(len(items) / size)),
        }

    async def get_request(
        self, holder: Holder, request_id: str
    ) -> OperationResult:
        """Return one request from whichever source has it.

        Raises:
            NotFoundError: No linked source has the request.
            ExternalServiceError: A source that may have it is down.
        """
        result = await self._find_request(holder, request_id)
        if isinstance(result.data, dict):
            result.data = {**result.data, "source_code": result.source_code}
        return result

    async def submit_request(
        self, holder: Holder, body: dict[str, Any]
    ) -> OperationResult:
        """Submit the holder's answers to the request's own source.

        Returns:
            The source's answer, passed on whatever its status.

        Raises:
            NotFoundError: No linked source has the request.
            ExternalServiceError: A source that may have it is down.
        """
        request_id = str(body["request_id"])
        found = await self._find_request(holder, request_id)
        response = await self.run_on_source(
            holder,
            "requests.submit",
            found.source_code,
            {"request_id": request_id},
            body,
        )
        return response.items[0]

    async def _find_request(
        self, holder: Holder, request_id: str
    ) -> OperationResult:
        response = await self.connector.run_operation(
            holder.email, "requests.find", params={"request_id": request_id}
        )
        found = [result for result in response.items if result.ok]
        if found:
            if len(found) > 1:
                # Request ids are random per DCS; a clash is unexpected
                # and the newest-linked source cannot be told apart.
                logger.warning(
                    "Request id found in %d sources; using %s",
                    len(found),
                    found[0].source_code,
                )
            return found[0]
        if any(result.status_code >= 500 for result in response.items):
            raise ExternalServiceError(
                "The credential network is unavailable."
            )
        raise NotFoundError(REQUEST_NOT_FOUND)
