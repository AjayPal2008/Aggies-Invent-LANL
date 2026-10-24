"""Run once before starting the web workers: create/upgrade tables and load data if the database is empty.

Docker runs this in a one-shot "migrate" container so several app workers and replicas
never race to create tables or import the same data.
"""
import logging
import time

from sqlalchemy import func, select, text

from app import models
from app.database import SessionLocal, engine, init_db

logging.basicConfig(level=logging.INFO)


def wait_for_db(seconds: int = 60):
    deadline = time.time() + seconds
    while True:
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            return
        except Exception:
            if time.time() > deadline:
                raise
            time.sleep(1)


def main():
    wait_for_db()
    init_db()
    with SessionLocal() as db:
        if db.scalar(select(func.count(models.Employee.id))):
            from app.services.library import sync_library

            stats = sync_library(db)  # only adds library items that are missing, so updates reach existing databases
            db.commit()
            logging.info("Database already has data; library sync added %s", stats)
            return
        from app.services.demo import load_demo_documents
        from app.services.sync import sync_all

        logging.info("Empty database: running first sync")
        sync_all(db)
        load_demo_documents(db)


if __name__ == "__main__":
    main()
