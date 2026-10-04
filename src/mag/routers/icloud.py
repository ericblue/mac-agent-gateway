"""iCloud Drive filesystem API router."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from mag.auth import verify_api_key
from mag.config import get_settings
from mag.models.icloud import (
    ICloudDeleteResponse,
    ICloudDirectoryListing,
    ICloudEntry,
    ICloudMove,
)
from mag.services.icloud_drive import ICloudDriveError, ICloudDriveService, ICloudFile

router = APIRouter(prefix="/icloud", dependencies=[Depends(verify_api_key)])
icloud_drive = ICloudDriveService()

_ERROR_STATUS = {
    "invalid_path": 400,
    "parent_missing": 400,
    "unsupported_type": 400,
    "symlink_forbidden": 403,
    "permission_denied": 403,
    "not_found": 404,
    "conflict": 409,
    "insufficient_storage": 507,
    "filesystem_error": 500,
}


def _require_capability(capability: str) -> None:
    settings = get_settings()
    enabled = {
        "read": settings.icloud_read,
        "write": settings.icloud_write,
    }.get(capability, False)
    if not enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "error": f"Capability 'icloud.{capability}' is disabled",
                "hint": f"Set MAG_ICLOUD_{capability.upper()}=true to enable",
            },
        )


def _http_error(error: ICloudDriveError) -> HTTPException:
    return HTTPException(
        status_code=_ERROR_STATUS.get(error.code, 500),
        detail=error.to_detail(),
    )


def _read_path(path: str) -> ICloudDirectoryListing | FileResponse:
    _require_capability("read")
    try:
        result = icloud_drive.read(path)
    except ICloudDriveError as error:
        raise _http_error(error) from None
    if isinstance(result, ICloudFile):
        return FileResponse(path=result.path, media_type=result.media_type)
    return result


@router.get("", response_model=None)
async def get_icloud_root() -> ICloudDirectoryListing | Response:
    """List the Mobile Documents root."""
    return _read_path("")


@router.api_route("", methods=["PUT", "PATCH", "DELETE"], include_in_schema=False)
async def reject_icloud_root_mutation() -> None:
    """Reject mutations without a relative file path."""
    _require_capability("write")
    raise _http_error(ICloudDriveError("invalid_path", "A file path is required", ""))


@router.get("/{path:path}", response_model=None)
async def get_icloud_path(path: str) -> ICloudDirectoryListing | Response:
    """List a directory or stream a regular file."""
    return _read_path(path)


@router.put("/{path:path}", response_model=ICloudEntry)
async def put_icloud_file(path: str, request: Request, response: Response) -> ICloudEntry:
    """Create or fully replace a regular file from the raw request body."""
    _require_capability("write")
    try:
        entry, created = await icloud_drive.put(path, request.stream())
    except ICloudDriveError as error:
        raise _http_error(error) from None
    response.status_code = 201 if created else 200
    return entry


@router.patch("/{path:path}", response_model=ICloudEntry)
async def move_icloud_file(path: str, data: ICloudMove) -> ICloudEntry:
    """Rename or move a regular file without overwriting a destination."""
    _require_capability("write")
    try:
        return icloud_drive.move(path, data.destination)
    except ICloudDriveError as error:
        raise _http_error(error) from None


@router.delete("/{path:path}", response_model=ICloudDeleteResponse)
async def delete_icloud_file(path: str) -> ICloudDeleteResponse:
    """Delete one regular file."""
    _require_capability("write")
    try:
        return icloud_drive.delete(path)
    except ICloudDriveError as error:
        raise _http_error(error) from None
