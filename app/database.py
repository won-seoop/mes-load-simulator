import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Overridable so the test suite can point at an isolated sqlite file
# instead of the real ./mes.db used by the running server.
DATABASE_URL = os.environ.get("MES_DATABASE_URL", "sqlite:///./mes.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
