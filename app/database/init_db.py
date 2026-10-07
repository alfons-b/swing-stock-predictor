from app.database.base import Base
from app.database import models  # noqa: F401
from app.database.session import get_engine


def initialize_database() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
