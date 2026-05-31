from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

DATABASE_URL = settings.database_url
engine = create_engine(

    DATABASE_URL,

    pool_size=20,

    max_overflow=40,

    pool_timeout=30,

    pool_recycle=1800

)
 
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
