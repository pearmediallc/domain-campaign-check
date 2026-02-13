from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)

    domain_id: Mapped[str | None] = mapped_column(String, nullable=True)
    domain_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # candidate URLs
    impression_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    trackback_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # last 30d stats (best effort)
    cost_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_30d: Mapped[float | None] = mapped_column(Float, nullable=True)

    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    checks: Mapped[list[CheckResult]] = relationship(back_populates="campaign")


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String, ForeignKey("campaigns.id"), index=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), index=True)

    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_type: Mapped[str | None] = mapped_column(String, nullable=True)  # dns|timeout|http|ssl|other
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    tested_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    campaign: Mapped[Campaign] = relationship(back_populates="checks")
