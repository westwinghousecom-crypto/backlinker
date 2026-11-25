from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, field_validator

from app.features.diagnostics.scanner import UrlCheck

_url = TypeAdapter(HttpUrl)


class CheckBatchRequest(BaseModel):
    """The owner is never part of the request: it comes from the verified sign-in."""

    urls: list[str] = Field(min_length=1, max_length=1000)
    target: str | None = Field(default=None, max_length=2000, description="Your website; pages must link to it")

    @field_validator("target")
    @classmethod
    def _target(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if not v:
            return None
        if "://" not in v:
            v = f"https://{v}"
        try:
            _url.validate_python(v)
        except Exception:
            raise ValueError("Target website is not a valid URL")
        return v


class CheckBatchCreated(BaseModel):
    batch_id: str
    total: int


ManualMark = Literal["appears", "not_found"]


class ManualGoogleRequest(BaseModel):
    """The customer's own note after searching Google themselves. `clear` removes it. It is never evidence and never changes a verdict."""

    result: Literal["appears", "not_found", "clear"]


class ManualGoogleMark(BaseModel):
    manual_google: ManualMark | None = None
    manual_google_at: str | None = None


class ReportSharingUpdate(BaseModel):
    """Owner's opt-in to let anyone with the link view this batch's results, with no sign-in. Off by default."""

    public_report: bool


class ReportSharingState(BaseModel):
    public_report: bool
    public_url: str | None = None


class CheckItem(BaseModel):
    id: str
    position: int
    url: str
    state: Literal["pending", "processing", "done"]
    result: UrlCheck | None = None
    manual_google: ManualMark | None = None  # self-reported by the customer, not verified by QuickIndex
    manual_google_at: str | None = None


class CheckSummary(BaseModel):
    total: int
    checked: int
    eligible: int
    with_problems: int  # blocked + warning + unreachable, among checked
    blocked: int
    warnings: int
    unreachable: int
    backlinks_found: int
    backlinks_missing: int
    done: bool


class CheckBatch(BaseModel):
    batch_id: str
    target: str | None
    created_at: str | None
    summary: CheckSummary
    items: list[CheckItem]


class CheckBatchSummaryRow(BaseModel):
    batch_id: str
    target: str | None
    created_at: str | None
    total: int
    checked: int
