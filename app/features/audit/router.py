"""HTTP route for the holder's own audit trail."""

from fastapi import APIRouter

from app.features.audit.dependencies import AuditServiceDep
from app.features.audit.schemas import AuditLogResponse
from app.features.auth.dependencies import CurrentHolder
from app.shared.pagination import Pagination
from app.shared.schemas import Page

router = APIRouter(prefix="/holders/me/audit-logs", tags=["Audit"])


@router.get(
    "",
    response_model=Page[AuditLogResponse],
    summary="List my account activity",
)
async def list_audit_logs(
    holder: CurrentHolder,
    service: AuditServiceDep,
    pagination: Pagination,
) -> Page[AuditLogResponse]:
    """Return sign-ins, password changes, shares and other actions."""
    return await service.list_logs(
        holder.id, pagination.limit, pagination.offset
    )
