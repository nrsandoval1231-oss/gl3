from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from gridlens.settings import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass
