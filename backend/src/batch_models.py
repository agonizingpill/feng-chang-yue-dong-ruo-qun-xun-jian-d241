from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class InspectionBatch(Base):
    """一次分组巡箱的领批、交接接收与封存档案。"""

    __tablename__ = 'inspection_batches'
    __table_args__ = (
        CheckConstraint('hive_count>=0 AND received_count>=0 AND missing_count>=0 AND conflict_count>=0'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    state: Mapped[str] = mapped_column(String(24), default='claimed')
    note: Mapped[str] = mapped_column(String(300), default='')
    claimed_by: Mapped[str] = mapped_column(String(120))
    claimed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    claim_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    claim_fingerprint: Mapped[str] = mapped_column(String(64), default='')
    parent_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey('inspection_batches.id'), nullable=True, index=True
    )
    receive_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    received_by: Mapped[str] = mapped_column(String(120), default='')
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seal_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    seal_reason: Mapped[str] = mapped_column(String(400), default='')
    sealed_by: Mapped[str] = mapped_column(String(120), default='')
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seal_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    seal_fingerprint: Mapped[str] = mapped_column(String(64), default='')
    hive_count: Mapped[int] = mapped_column(Integer, default=0)
    received_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_count: Mapped[int] = mapped_column(Integer, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)
    screen_state: Mapped[str] = mapped_column(String(24), default='idle')
    screen_job_id: Mapped[str] = mapped_column(String(64), default='')
    screen_queued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    screened_count: Mapped[int] = mapped_column(Integer, default=0)
    screened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by: Mapped[str] = mapped_column(String(120), default='')
    cancel_reason: Mapped[str] = mapped_column(String(400), default='')
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class InspectionBatchHive(Base):
    """领批时锁定的箱清单快照；之后编辑蜂箱档案不会改变本批范围。"""

    __tablename__ = 'inspection_batch_hives'
    __table_args__ = (UniqueConstraint('batch_id', 'hive_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey('inspection_batches.id'))
    hive_id: Mapped[int] = mapped_column(ForeignKey('hives.id'))
    hive_code: Mapped[str] = mapped_column(String(30))
    site: Mapped[str] = mapped_column(String(50))
    seq: Mapped[int] = mapped_column(Integer, default=0)
    # 在途批次占用标记：同一蜂箱同时只允许一个未封存批次持有，封存/取消即释放。
    active_key: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)


class InspectionReading(Base):
    """逐箱补录读数。完整读数每箱仅一条；缺项与冲突作为证据留在原批。"""

    __tablename__ = 'inspection_readings'
    __table_args__ = (
        CheckConstraint('weight_kg IS NULL OR weight_kg>0'),
        CheckConstraint('colony_frames IS NULL OR (colony_frames>=0 AND colony_frames<=20)'),
        Index(
            'uq_inspection_reading_complete',
            'batch_id',
            'hive_id',
            unique=True,
            postgresql_where=text("state IN ('complete','accepted')"),
            sqlite_where=text("state IN ('complete','accepted')"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey('inspection_batches.id'))
    hive_id: Mapped[int] = mapped_column(ForeignKey('hives.id'))
    hive_code: Mapped[str] = mapped_column(String(30))
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity: Mapped[float | None] = mapped_column(Float, nullable=True)
    feed_left: Mapped[float | None] = mapped_column(Float, nullable=True)
    queen_seen: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    colony_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(24), default='incomplete')
    missing_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default='')
    conflict_note: Mapped[str] = mapped_column(String(300), default='')
    recorded_by: Mapped[str] = mapped_column(String(120))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    client_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    visit_id: Mapped[int | None] = mapped_column(ForeignKey('visits.id'), nullable=True)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    anomaly_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    decision_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
