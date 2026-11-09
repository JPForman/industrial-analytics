from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base, kept free of settings/engine so other services (the ingestor)
    can import the models without the API's configuration (e.g. JWT_SECRET)."""
