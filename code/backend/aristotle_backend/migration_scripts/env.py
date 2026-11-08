from alembic import context
from aristotle_backend.db import Base

config = context.config

if context.is_offline_mode():
    context.configure(
        url=config.attributes["url"],
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
else:
    connection = config.attributes["connection"]
    version_schema = (
        connection.exec_driver_sql("SELECT current_schema()").scalar_one()
        if connection.dialect.name == "postgresql"
        else None
    )
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        version_table_schema=version_schema,
    )

with context.begin_transaction():
    context.run_migrations()
