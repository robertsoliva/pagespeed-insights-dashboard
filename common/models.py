"""Shared dataclasses passed between the setup tool and the fetch job."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class JobConfig:
    job_id: str
    source_type: str  # "csv" | "domain"
    interval_hours: int
    target_project: str
    target_dataset: str
    target_table: str
    urls: list[str] = field(default_factory=list)
    domain: str | None = None
    max_crawl_pages: int = 200
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.source_type not in ("csv", "domain"):
            raise ValueError(f"source_type must be 'csv' or 'domain', got {self.source_type!r}")
        if self.source_type == "csv" and not self.urls:
            raise ValueError("source_type='csv' requires a non-empty urls list")
        if self.source_type == "domain" and not self.domain:
            raise ValueError("source_type='domain' requires a domain")

    def to_bq_row(self) -> dict:
        return {
            "job_id": self.job_id,
            "created_at": self.created_at.isoformat(),
            "enabled": self.enabled,
            "source_type": self.source_type,
            "urls": self.urls,
            "domain": self.domain,
            "max_crawl_pages": self.max_crawl_pages,
            "interval_hours": self.interval_hours,
            "target_project": self.target_project,
            "target_dataset": self.target_dataset,
            "target_table": self.target_table,
        }

    @classmethod
    def from_bq_row(cls, row: dict) -> "JobConfig":
        return cls(
            job_id=row["job_id"],
            source_type=row["source_type"],
            interval_hours=row["interval_hours"],
            target_project=row["target_project"],
            target_dataset=row["target_dataset"],
            target_table=row["target_table"],
            urls=list(row.get("urls") or []),
            domain=row.get("domain"),
            max_crawl_pages=row.get("max_crawl_pages") or 200,
            enabled=row.get("enabled", True),
            created_at=row["created_at"],
        )
