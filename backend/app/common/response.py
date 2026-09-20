from pydantic import BaseModel


class ApiResponse[DataT](BaseModel):
    """Stable v2 response envelope used by REST endpoints."""

    code: str = "OK"
    message: str = "success"
    data: DataT | None = None
    request_id: str | None = None

    @classmethod
    def ok(cls, data: DataT, request_id: str | None = None) -> "ApiResponse[DataT]":
        return cls(data=data, request_id=request_id)
