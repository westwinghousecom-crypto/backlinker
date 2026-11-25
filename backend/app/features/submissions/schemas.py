from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, field_validator

_url_adapter = TypeAdapter(HttpUrl)


class SubmitRequest(BaseModel):
    """URLs to submit. The owner is never part of the request: it comes from the verified sign-in."""

    urls: list[str] = Field(min_length=1, max_length=1000)

    @field_validator("urls")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for raw in v:
            u = raw.strip()
            if not u:
                continue
            if len(u) > 2000:
                raise ValueError(f"URL too long: {u[:50]}...")
            try:
                _url_adapter.validate_python(u)
            except Exception:
                raise ValueError(f"Invalid URL: {u[:100]}")
            seen.setdefault(u, None)
        if not seen:
            raise ValueError("No valid URLs supplied")
        return list(seen)


class SubmitOneRequest(BaseModel):
    url: str


class SubmitResponse(BaseModel):
    batch_id: str
    total: int


class RecentBatch(BaseModel):
    batch_id: str
    total: int
    created_at: str | None = None


class BatchUrl(BaseModel):
    url: str
    status: str
    attempts: int


class BatchStatus(BaseModel):
    batch_id: str
    total: int
    counts: dict[str, int]
    done: bool
    urls: list[BatchUrl]
