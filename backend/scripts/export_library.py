"""Copy every PDF, slide deck or document uploaded in the admin library on this computer into the shared
library folder (Resource_File/library/<TRAINING-CODE>/), so it can be committed and everyone gets the same files.

    python -m scripts.export_library

Then commit Resource_File/library and push. On other computers, startup (or scripts.import_library) imports them.
"""
from app.database import SessionLocal, init_db
from app.services import library


def main():
    init_db()
    with SessionLocal() as db:
        r = library.export_to_folder(db)
    print(f"copied {r['copied']} files into {library.library_root()} ({r['already_there']} already there, "
          f"{r['missing']} uploads whose file is no longer stored)")
    for f in r["files"]:
        print("  ", f)


if __name__ == "__main__":
    main()
