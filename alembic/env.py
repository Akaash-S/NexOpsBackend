import asyncio
import sys
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Ensure backend directory is in sys.path
sys.path.append(os.getcwd())

from sqlmodel import SQLModel
from app.core.config import settings
import app.models  # ensures SQLModel.metadata is fully populated

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_target_db_url() -> str:
    """Retrieve target passed via -x target=migration|staging|production.
    Fails loudly with ValueError if unspecified or invalid.
    """
    target = context.get_x_argument(as_dictionary=True).get("target")
    if not target:
        raise ValueError(
            "A target environment must be specified. "
            "Please run migration with -x target=migration|staging|production"
        )
    
    if target == "migration":
        return settings.direct_async_migration_database_url
    elif target == "staging":
        return settings.direct_async_staging_database_url
    elif target == "production":
        return settings.direct_owner_async_database_url
    else:
        raise ValueError(
            f"Invalid target environment '{target}'. "
            "Allowed values are: migration, staging, production"
        )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_target_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connect_args = {}
    if settings.requires_ssl:
        connect_args["ssl"] = True

    db_url = get_target_db_url()
    connectable = create_async_engine(
        db_url,
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    # Run the async migration runner using asyncio.run
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

