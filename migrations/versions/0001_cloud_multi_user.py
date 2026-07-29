"""创建云端多用户完整结构。

Revision ID: 0001_cloud_multi_user
Revises:
"""
from __future__ import annotations

from alembic import op
from sqlmodel import SQLModel

from app import models  # noqa: F401


revision = "0001_cloud_multi_user"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    SQLModel.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    SQLModel.metadata.drop_all(bind=op.get_bind())
