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
            logging.info("Database already has data; nothing to load")
            return
        from app.services.demo import load_demo_documents
        from app.services.sync import sync_all

        logging.info("Empty database: running first sync")
        sync_all(db)
        load_demo_documents(db)


if __name__ == "__main__":
    main()
