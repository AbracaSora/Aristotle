"""Fixed curriculum, immutable presets and user-owned final tests. No data seeding."""

import sqlalchemy as sa
from alembic import op

revision = "0003_curriculum_tests"
down_revision = "0002_semantic_learning"
branch_labels = None
depends_on = None


def upgrade():
    upgrade_submission_scope()
    create_subjects_and_chapters()
    create_standard_questions_and_points()
    create_preset_tasks()
    create_final_tests()
    index_tests_and_create_sets()


def upgrade_submission_scope():
    if op.get_context().dialect.name == "sqlite":
        with op.batch_alter_table(
            "attempts", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s"}
        ) as batch:
            batch.drop_constraint("uq_attempts_user_id_submission_id", type_="unique")
            batch.create_unique_constraint(
                "uq_attempt_task_submission", ["user_id", "task_id", "submission_id"]
            )
    else:
        op.drop_constraint("attempts_user_id_submission_id_key", "attempts", type_="unique")
        op.create_unique_constraint(
            "uq_attempt_task_submission", "attempts", ["user_id", "task_id", "submission_id"]
        )


def create_subjects_and_chapters():
    op.create_table(
        "curriculum_subjects",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "curriculum_chapters",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["curriculum_subjects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def create_standard_questions_and_points():
    op.create_table(
        "standard_questions",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["key"], ["questions.key"]),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "curriculum_points",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("graph_version", sa.String(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["chapter_id"], ["curriculum_chapters.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def create_preset_tasks():
    op.create_table(
        "preset_tasks",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("preset_set_id", sa.String(), nullable=False),
        sa.Column("preset_set_version", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "preset_set_id", "preset_set_version"),
        sa.UniqueConstraint("task_id"),
    )


def create_final_tests():
    op.create_table(
        "final_tests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("knowledge_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("preset_set_id", sa.String(), nullable=False),
        sa.Column("preset_set_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("generation_context", sa.JSON(), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("submission_id", sa.String(), nullable=True),
        sa.Column("submission_hash", sa.String(), nullable=True),
        sa.Column("client_context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=True),
        sa.Column("submitted_at", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "status IN ('generating','ready','generation_failed','submitted')", name="test_status"
        ),
        sa.CheckConstraint("version > 0", name="positive_test_version"),
        sa.ForeignKeyConstraint(["knowledge_id"], ["curriculum_points.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "knowledge_id", "version"),
        sa.UniqueConstraint("user_id", "request_id"),
    )


def index_tests_and_create_sets():
    op.create_index(op.f("ix_final_tests_user_id"), "final_tests", ["user_id"], unique=False)
    op.create_index(
        "uq_final_test_active",
        "final_tests",
        ["user_id", "knowledge_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('generating', 'ready')"),
        sqlite_where=sa.text("status IN ('generating', 'ready')"),
    )
    op.create_table(
        "preset_sets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("knowledge_id", sa.String(), nullable=False),
        sa.Column("question_keys", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_id"], ["curriculum_points.id"]),
        sa.PrimaryKeyConstraint("id", "version"),
    )


def downgrade():
    # A downgrade refuses conflicting IDs rather than deleting historical attempts.
    with op.batch_alter_table("attempts") as batch:
        batch.drop_constraint("uq_attempt_task_submission", type_="unique")
        batch.create_unique_constraint(
            "uq_attempts_user_id_submission_id"
            if op.get_context().dialect.name == "sqlite"
            else "attempts_user_id_submission_id_key",
            ["user_id", "submission_id"],
        )
    op.drop_table("preset_sets")
    op.drop_index(
        "uq_final_test_active",
        table_name="final_tests",
        postgresql_where=sa.text("status IN ('generating', 'ready')"),
        sqlite_where=sa.text("status IN ('generating', 'ready')"),
    )
    op.drop_index(op.f("ix_final_tests_user_id"), table_name="final_tests")
    op.drop_table("final_tests")
    op.drop_table("preset_tasks")
    op.drop_table("curriculum_points")
    op.drop_table("standard_questions")
    op.drop_table("curriculum_chapters")
    op.drop_table("curriculum_subjects")
