from .db import engine
from .models import Base


def migrate():
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    migrate()
