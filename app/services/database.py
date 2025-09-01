# from sqlmodel import Session, SQLModel, create_engine

# DATABASE_URL = "sqlite:///./datasets.db"

# connect_args = {"check_same_thread": False}
# engine = create_engine(DATABASE_URL, connect_args=connect_args)

# def create_db_and_tables():
#     SQLModel.metadata.create_all(engine)

# def get_db():
#     with Session(engine) as session:
#         yield session

import os
import importlib
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base


SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./datasets.db")

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base = declarative_base()
Session = scoped_session(SessionLocal)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_db_and_tables():
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        raise
