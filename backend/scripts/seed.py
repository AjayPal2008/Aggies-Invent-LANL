"""Rebuild the database from the connectors.

    python -m scripts.seed            # load whatever is in DATA_DIR
    python -m scripts.seed --reset    # regenerate sample data, wipe the DB, reload
"""
import argparse

from app.database import Base, SessionLocal, engine, init_db
from app.services.sync import sync_all


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="regenerate sample data and drop all tables first")
    args = parser.parse_args()
    if args.reset:
        from scripts import make_sample_data

        make_sample_data.main()
        Base.metadata.drop_all(engine)
    init_db()
    with SessionLocal() as db:
        result = sync_all(db)
        from app.services.demo import load_demo_documents

        if args.reset:
            import shutil
            from app.config import settings

            shutil.rmtree(settings.upload_dir, ignore_errors=True)
        result["demo_documents"] = load_demo_documents(db)
    for source, stats in result.items():
        if isinstance(stats, dict) and "created" in stats:
            print(f"{source}: {stats['created']} created, {stats['updated']} updated, {len(stats['errors'])} warnings")
            for err in stats["errors"][:5]:
                print("   ", err)
        elif isinstance(stats, dict):
            print(f"{source}: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in stats.items()))
        else:
            print(f"{source}: {stats}")
    print("Demo logins (password from DEMO_PASSWORD, default demo1234): admin@lanl.gov, manager@lanl.gov, hire@lanl.gov")


if __name__ == "__main__":
    main()
