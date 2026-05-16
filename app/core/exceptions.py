from fastapi import Request
from fastapi.responses import JSONResponse


class SynapseError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


async def synapse_error_handler(request: Request, exc: SynapseError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )
