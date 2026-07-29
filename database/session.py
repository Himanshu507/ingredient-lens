from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    engine: Engine = create_engine(database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)
