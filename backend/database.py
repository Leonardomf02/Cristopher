from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cristopher.db")
# Para quem abre a base com o sqlite3 directo. Na NAS é /data/cristopher.db: um
# "cristopher.db" escrito à mão abria uma base vazia ao lado do código.
DB_PATH = DATABASE_URL.replace("sqlite:///", "")

# timeout: quanto se espera por um lock antes de "database is locked" (eram 5s).
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})

if DATABASE_URL.startswith("sqlite"):
    # WAL: quem lê deixa de esperar por quem escreve. Na NAS a CPU e o disco são
    # lentos e o agendador escreve ao mesmo tempo que as páginas lêem.
    @event.listens_for(engine, "connect")
    def _modo_wal(ligacao, _registo):
        cursor = ligacao.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
