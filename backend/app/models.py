"""SQLAlchemy models. Every business table carries `tenant_id`."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, EmbeddingType


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(sa.String(40), unique=True)
    name: Mapped[str] = mapped_column(sa.String(120))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(sa.ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(sa.String(200))
    name: Mapped[str] = mapped_column(sa.String(120))
    role: Mapped[str] = mapped_column(sa.String(20))  # viewer | manager | admin
    api_key_hash: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(default=True)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(sa.ForeignKey("tenants.id"), index=True)
    title: Mapped[str] = mapped_column(sa.String(300))
    filename: Mapped[str] = mapped_column(sa.String(300))
    content_type: Mapped[str] = mapped_column(sa.String(100))
    category: Mapped[str] = mapped_column(sa.String(40), index=True)
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(sa.String(20), default="active")
    meta: Mapped[dict] = mapped_column(sa.JSON, default=dict)
    uploaded_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Chunk.chunk_index"
    )


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(sa.ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[int] = mapped_column(sa.ForeignKey("tenants.id"), index=True)  # denormalised for filtering
    chunk_index: Mapped[int]
    content: Mapped[str] = mapped_column(sa.Text)
    search_text: Mapped[str] = mapped_column(sa.Text)  # title + section + content: what is embedded/indexed
    content_hash: Mapped[str] = mapped_column(sa.String(64))
    section: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    page: Mapped[int | None] = mapped_column(nullable=True)
    token_count: Mapped[int] = mapped_column(default=0)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType(), nullable=True)
    flagged: Mapped[bool] = mapped_column(default=False)  # prompt-injection quarantine
    flag_reason: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    document: Mapped[Document] = relationship(back_populates="chunks")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (sa.UniqueConstraint("tenant_id", "sku"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(sa.ForeignKey("tenants.id"), index=True)
    sku: Mapped[str] = mapped_column(sa.String(20))
    name: Mapped[str] = mapped_column(sa.String(200))
    category: Mapped[str] = mapped_column(sa.String(60))
    description: Mapped[str] = mapped_column(sa.Text, default="")
    unit_price: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))
    reorder_point: Mapped[int] = mapped_column(default=0)
    supplier: Mapped[str] = mapped_column(sa.String(120), default="")
    hazmat: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)
    inventory: Mapped[list[Inventory]] = relationship(back_populates="product", cascade="all, delete-orphan")


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (sa.UniqueConstraint("product_id", "warehouse"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(sa.ForeignKey("tenants.id"), index=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("products.id"), index=True)
    warehouse: Mapped[str] = mapped_column(sa.String(40))
    on_hand: Mapped[int] = mapped_column(default=0)
    reserved: Mapped[int] = mapped_column(default=0)
    product: Mapped[Product] = relationship(back_populates="inventory")


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(sa.ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    tier: Mapped[str] = mapped_column(sa.String(20), default="standard")  # standard | gold | platinum
    contact_name: Mapped[str] = mapped_column(sa.String(120), default="")
    email: Mapped[str] = mapped_column(sa.String(200), default="")
    phone: Mapped[str] = mapped_column(sa.String(40), default="")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (sa.UniqueConstraint("tenant_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(sa.ForeignKey("tenants.id"), index=True)
    number: Mapped[str] = mapped_column(sa.String(20))
    customer_id: Mapped[int] = mapped_column(sa.ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(sa.String(20), index=True)
    shipping_method: Mapped[str] = mapped_column(sa.String(20), default="standard")
    created_on: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(sa.Text, default="")
    customer: Mapped[Customer] = relationship()
    items: Mapped[list[OrderItem]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(sa.ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("products.id"))
    quantity: Mapped[int]
    unit_price: Mapped[Decimal] = mapped_column(sa.Numeric(12, 2))
    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(sa.ForeignKey("tenants.id"), index=True)
    number: Mapped[str] = mapped_column(sa.String(20))
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("products.id"))
    quantity: Mapped[int]
    supplier: Mapped[str] = mapped_column(sa.String(120))
    status: Mapped[str] = mapped_column(sa.String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class PendingAction(Base):
    """A state change drafted by the assistant. Nothing happens until a human confirms."""

    __tablename__ = "pending_actions"
    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[int] = mapped_column(sa.ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    action_type: Mapped[str] = mapped_column(sa.String(40))
    payload: Mapped[dict] = mapped_column(sa.JSON)
    preview: Mapped[dict] = mapped_column(sa.JSON)
    reason: Mapped[str] = mapped_column(sa.Text, default="")
    status: Mapped[str] = mapped_column(sa.String(20), default="pending", index=True)
    conversation_id: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    result: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[int] = mapped_column(sa.ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(sa.ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(sa.String(20))
    content: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class UsageLog(Base):
    __tablename__ = "usage_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(sa.ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(sa.String(20))  # chat | embedding
    provider: Mapped[str] = mapped_column(sa.String(40))
    model: Mapped[str] = mapped_column(sa.String(80))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    latency_ms: Mapped[float] = mapped_column(sa.Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(sa.ForeignKey("tenants.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    event: Mapped[str] = mapped_column(sa.String(60), index=True)
    detail: Mapped[dict] = mapped_column(sa.JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, index=True)
