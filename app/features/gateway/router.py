"""HTTP routes for issuer-side wallet actions, forwarded to DCS.

Every route returns :class:`~app.core.connector.OperationResponse`: one
item per DCS source called, with that source's status code and data.
List routes call every source the holder is linked to; item routes
name the source in the path, using the ``source_code`` from the list.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, status

from app.core.connector import OperationResponse
from app.features.auth.dependencies import CurrentHolder
from app.features.gateway.dependencies import GatewayServiceDep
from app.features.gateway.service import GatewayService
from app.features.holders.models import Holder
from app.shared.identifiers import ExternalId, SourceCode
from app.shared.schemas import ErrorResponse

router = APIRouter(
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
)

ActionBody = Annotated[
    dict[str, Any],
    Body(description="Passed to the DCS source unchanged."),
]

_SOURCE = "/sources/{source_code}"
_REQUEST = f"{_SOURCE}/requests/{{request_id}}"
_WORKFLOW = f"{_SOURCE}/workflow-requests/{{request_uuid}}"
_WORKFLOW_NODE = f"{_WORKFLOW}/nodes/{{node_key}}"
_INTEGRATION_STEP = (
    f"{_REQUEST}/integrations/{{integration_type}}/{{tool_code}}/{{flow}}"
)


@router.get(
    "/requests",
    response_model=OperationResponse,
    tags=["Credential Requests"],
    summary="List my credential requests",
)
async def list_credential_requests(
    holder: CurrentHolder, service: GatewayServiceDep
) -> OperationResponse:
    """Return credential requests from every source."""
    return await service.list_from_all_sources(holder, "requests.list")


@router.get(
    _REQUEST,
    response_model=OperationResponse,
    tags=["Credential Requests"],
    summary="Get a credential request",
)
async def get_credential_request(
    source_code: SourceCode,
    request_id: ExternalId,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Return one credential request."""
    return await service.run_on_source(
        holder, "requests.get", source_code, {"request_id": request_id}
    )


@router.get(
    f"{_REQUEST}/fields",
    response_model=OperationResponse,
    tags=["Credential Requests"],
    summary="Get the fields a credential request asks for",
)
async def get_credential_request_fields(
    source_code: SourceCode,
    request_id: ExternalId,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Return the form the holder has to fill in."""
    return await service.run_on_source(
        holder, "requests.fields", source_code, {"request_id": request_id}
    )


@router.post(
    f"{_REQUEST}/submission",
    response_model=OperationResponse,
    tags=["Credential Requests"],
    summary="Submit a credential request",
)
async def submit_credential_request(
    source_code: SourceCode,
    request_id: ExternalId,
    body: ActionBody,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Send the holder's answers to the issuer."""
    return await service.run_on_source(
        holder,
        "requests.submit",
        source_code,
        {"request_id": request_id},
        body,
    )


@router.post(
    f"{_REQUEST}/decline",
    response_model=OperationResponse,
    tags=["Credential Requests"],
    summary="Decline a credential request",
)
async def decline_credential_request(
    source_code: SourceCode,
    request_id: ExternalId,
    body: ActionBody,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Decline the request, optionally with a reason in the body."""
    return await service.run_on_source(
        holder,
        "requests.decline",
        source_code,
        {"request_id": request_id},
        body,
    )


@router.get(
    f"{_SOURCE}/kyc-detail",
    response_model=OperationResponse,
    tags=["Credential Requests"],
    summary="Get my KYC details at a source",
)
async def get_kyc_detail(
    source_code: SourceCode,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Return the KYC details the source holds for the holder."""
    return await service.run_on_source(holder, "kyc.detail", source_code)


@router.get(
    "/workflow-requests",
    response_model=OperationResponse,
    tags=["Workflow Requests"],
    summary="List my workflow requests",
)
async def list_workflow_requests(
    holder: CurrentHolder, service: GatewayServiceDep
) -> OperationResponse:
    """Return workflow-engine requests from every source."""
    return await service.list_from_all_sources(holder, "workflow.list")


@router.get(
    _WORKFLOW,
    response_model=OperationResponse,
    tags=["Workflow Requests"],
    summary="Get a workflow request",
)
async def get_workflow_request(
    source_code: SourceCode,
    request_uuid: ExternalId,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Return one workflow request with its current step."""
    return await service.run_on_source(
        holder, "workflow.get", source_code, {"request_uuid": request_uuid}
    )


@router.post(
    f"{_WORKFLOW}/consent",
    response_model=OperationResponse,
    tags=["Workflow Requests"],
    summary="Give consent for a workflow request",
)
async def give_workflow_consent(
    source_code: SourceCode,
    request_uuid: ExternalId,
    body: ActionBody,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Record the holder's consent decision."""
    return await service.run_on_source(
        holder,
        "workflow.consent",
        source_code,
        {"request_uuid": request_uuid},
        body,
    )


async def _run_workflow_node(
    operation: str,
    source_code: str,
    request_uuid: str,
    node_key: str,
    body: dict[str, Any],
    holder: Holder,
    service: GatewayService,
) -> OperationResponse:
    return await service.run_on_source(
        holder,
        operation,
        source_code,
        {"request_uuid": request_uuid, "node_key": node_key},
        body,
    )


@router.post(
    f"{_WORKFLOW_NODE}/submit",
    response_model=OperationResponse,
    tags=["Workflow Requests"],
    summary="Submit a workflow step",
)
async def submit_workflow_node(
    source_code: SourceCode,
    request_uuid: ExternalId,
    node_key: ExternalId,
    body: ActionBody,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Send the holder's input for a workflow step."""
    return await _run_workflow_node(
        "workflow.node_submit",
        source_code,
        request_uuid,
        node_key,
        body,
        holder,
        service,
    )


@router.post(
    f"{_WORKFLOW_NODE}/accept",
    response_model=OperationResponse,
    tags=["Workflow Requests"],
    summary="Accept a workflow step",
)
async def accept_workflow_node(
    source_code: SourceCode,
    request_uuid: ExternalId,
    node_key: ExternalId,
    body: ActionBody,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Accept what a workflow step offers."""
    return await _run_workflow_node(
        "workflow.node_accept",
        source_code,
        request_uuid,
        node_key,
        body,
        holder,
        service,
    )


@router.post(
    f"{_WORKFLOW_NODE}/decline",
    response_model=OperationResponse,
    tags=["Workflow Requests"],
    summary="Decline a workflow step",
)
async def decline_workflow_node(
    source_code: SourceCode,
    request_uuid: ExternalId,
    node_key: ExternalId,
    body: ActionBody,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Decline what a workflow step offers."""
    return await _run_workflow_node(
        "workflow.node_decline",
        source_code,
        request_uuid,
        node_key,
        body,
        holder,
        service,
    )


@router.get(
    f"{_REQUEST}/integrations",
    response_model=OperationResponse,
    tags=["Integration KYC"],
    summary="List the integrations a request needs",
)
async def list_request_integrations(
    source_code: SourceCode,
    request_id: ExternalId,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Return the verification or gather steps of a request."""
    return await service.run_on_source(
        holder,
        "integrations.list",
        source_code,
        {"request_id": request_id},
    )


async def _run_integration_step(
    operation: str,
    source_code: str,
    request_id: str,
    integration_type: str,
    tool_code: str,
    flow: str,
    body: dict[str, Any],
    holder: Holder,
    service: GatewayService,
) -> OperationResponse:
    return await service.run_on_source(
        holder,
        operation,
        source_code,
        {
            "request_id": request_id,
            "integration_type": integration_type,
            "tool_code": tool_code,
            "flow": flow,
        },
        body,
    )


@router.post(
    f"{_INTEGRATION_STEP}/start",
    response_model=OperationResponse,
    tags=["Integration KYC"],
    summary="Start an integration step",
)
async def start_integration_step(
    source_code: SourceCode,
    request_id: ExternalId,
    integration_type: ExternalId,
    tool_code: ExternalId,
    flow: ExternalId,
    body: ActionBody,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Start a KYC or gather session for a request."""
    return await _run_integration_step(
        "integrations.start",
        source_code,
        request_id,
        integration_type,
        tool_code,
        flow,
        body,
        holder,
        service,
    )


@router.post(
    f"{_INTEGRATION_STEP}/inputs",
    response_model=OperationResponse,
    tags=["Integration KYC"],
    summary="Submit inputs to an integration step",
)
async def submit_integration_inputs(
    source_code: SourceCode,
    request_id: ExternalId,
    integration_type: ExternalId,
    tool_code: ExternalId,
    flow: ExternalId,
    body: ActionBody,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Send the inputs a session asked for, such as an OTP."""
    return await _run_integration_step(
        "integrations.inputs",
        source_code,
        request_id,
        integration_type,
        tool_code,
        flow,
        body,
        holder,
        service,
    )


@router.post(
    f"{_INTEGRATION_STEP}/cancel",
    response_model=OperationResponse,
    tags=["Integration KYC"],
    summary="Cancel an integration step",
)
async def cancel_integration_step(
    source_code: SourceCode,
    request_id: ExternalId,
    integration_type: ExternalId,
    tool_code: ExternalId,
    flow: ExternalId,
    body: ActionBody,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Cancel a running session."""
    return await _run_integration_step(
        "integrations.cancel",
        source_code,
        request_id,
        integration_type,
        tool_code,
        flow,
        body,
        holder,
        service,
    )


@router.post(
    f"{_SOURCE}/digilocker/initialize",
    response_model=OperationResponse,
    tags=["DigiLocker"],
    summary="Start a DigiLocker flow",
)
async def initialize_digilocker(
    source_code: SourceCode,
    body: ActionBody,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Start DigiLocker consent; the response has the redirect URL."""
    return await service.run_on_source(
        holder, "digilocker.initialize", source_code, body=body
    )


@router.get(
    f"{_SOURCE}/digilocker/complete-flow/{{client_id}}",
    response_model=OperationResponse,
    tags=["DigiLocker"],
    summary="Finish a DigiLocker flow",
)
async def complete_digilocker(
    source_code: SourceCode,
    client_id: ExternalId,
    holder: CurrentHolder,
    service: GatewayServiceDep,
) -> OperationResponse:
    """Fetch the documents after the holder approved in DigiLocker."""
    return await service.run_on_source(
        holder,
        "digilocker.complete",
        source_code,
        {"client_id": client_id},
    )
