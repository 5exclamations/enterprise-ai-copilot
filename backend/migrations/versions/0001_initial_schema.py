"""initial schema (baseline: 256-d hashing embeddings)

Revision ID: 0001
Revises: 
Create Date: 2026-10-09 19:12:59.135967
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


def embedding_type(dim: int):
    """pgvector `vector(dim)` on PostgreSQL, JSON elsewhere (mirrors app.db.EmbeddingType, frozen here)."""
    return sa.JSON().with_variant(Vector(dim), "postgresql")


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def _create_all() -> None:
    op.create_table('tenants',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_table('customers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('tier', sa.String(length=20), nullable=False),
    sa.Column('contact_name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('phone', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_customers_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('products',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('sku', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=60), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('reorder_point', sa.Integer(), nullable=False),
    sa.Column('supplier', sa.String(length=120), nullable=False),
    sa.Column('hazmat', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'sku')
    )
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_products_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('api_key_hash', sa.String(length=64), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_api_key_hash'), ['api_key_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_users_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('audit_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('event', sa.String(length=60), nullable=False),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_logs_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_logs_event'), ['event'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_logs_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('conversations',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_conversations_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('filename', sa.String(length=300), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('meta', sa.JSON(), nullable=False),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_documents_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_documents_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('inventory',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('warehouse', sa.String(length=40), nullable=False),
    sa.Column('on_hand', sa.Integer(), nullable=False),
    sa.Column('reserved', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('product_id', 'warehouse')
    )
    with op.batch_alter_table('inventory', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_inventory_product_id'), ['product_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_inventory_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('orders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('number', sa.String(length=20), nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('shipping_method', sa.String(length=20), nullable=False),
    sa.Column('created_on', sa.DateTime(timezone=True), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'number')
    )
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_orders_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_orders_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('pending_actions',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('action_type', sa.String(length=40), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('preview', sa.JSON(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('conversation_id', sa.String(length=32), nullable=True),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('pending_actions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pending_actions_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_pending_actions_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('purchase_orders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('number', sa.String(length=20), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('supplier', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('purchase_orders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_purchase_orders_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('usage_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=True),
    sa.Column('latency_ms', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('usage_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_usage_logs_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_usage_logs_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('chat_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.String(length=32), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chat_messages_conversation_id'), ['conversation_id'], unique=False)

    op.create_table('chunks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Integer(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('search_text', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('section', sa.String(length=300), nullable=True),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('embedding', embedding_type(256), nullable=True),
    sa.Column('flagged', sa.Boolean(), nullable=False),
    sa.Column('flag_reason', sa.String(length=300), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('chunks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_chunks_document_id'), ['document_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_chunks_tenant_id'), ['tenant_id'], unique=False)

    op.create_table('order_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('order_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_order_items_order_id'), ['order_id'], unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    if sa.inspect(bind).has_table("tenants"):
        return  # database predates Alembic (built by app.db.init_db): adopt it without touching data
    _create_all()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_fts ON chunks USING GIN (to_tsvector('english', search_text))")
        op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    with op.batch_alter_table('order_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_order_items_order_id'))

    op.drop_table('order_items')
    with op.batch_alter_table('chunks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chunks_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_chunks_document_id'))

    op.drop_table('chunks')
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_chat_messages_conversation_id'))

    op.drop_table('chat_messages')
    with op.batch_alter_table('usage_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_usage_logs_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_usage_logs_created_at'))

    op.drop_table('usage_logs')
    with op.batch_alter_table('purchase_orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_purchase_orders_tenant_id'))

    op.drop_table('purchase_orders')
    with op.batch_alter_table('pending_actions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_pending_actions_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_pending_actions_status'))

    op.drop_table('pending_actions')
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_orders_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_orders_status'))

    op.drop_table('orders')
    with op.batch_alter_table('inventory', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_inventory_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_inventory_product_id'))

    op.drop_table('inventory')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_documents_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_documents_category'))

    op.drop_table('documents')
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_conversations_tenant_id'))

    op.drop_table('conversations')
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_logs_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_event'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_created_at'))

    op.drop_table('audit_logs')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_tenant_id'))
        batch_op.drop_index(batch_op.f('ix_users_api_key_hash'))

    op.drop_table('users')
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_products_tenant_id'))

    op.drop_table('products')
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_customers_tenant_id'))

    op.drop_table('customers')
    op.drop_table('tenants')
