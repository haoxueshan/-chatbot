from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config,pool,text
from app.config import settings
from app.db import Base
import app.models
config=context.config
if config.config_file_name:fileConfig(config.config_file_name)
config.set_main_option('sqlalchemy.url',settings.database_url.replace('%','%%'))
target_metadata=Base.metadata
if context.is_offline_mode():
    context.configure(url=settings.database_url,target_metadata=target_metadata,literal_binds=True,dialect_opts={'paramstyle':'named'})
    with context.begin_transaction():context.run_migrations()
else:
    connectable=engine_from_config(config.get_section(config.config_ini_section),prefix='sqlalchemy.',poolclass=pool.NullPool)
    with connectable.connect() as connection:
        if connection.dialect.name=='postgresql':connection.execute(text('CREATE EXTENSION IF NOT EXISTS vector'));connection.commit()
        context.configure(connection=connection,target_metadata=target_metadata)
        with context.begin_transaction():context.run_migrations()
