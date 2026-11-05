"""Run or debug this file directly in PyCharm using the existing project venv."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="ClassBridge backend development server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # Resolve relative SQLite/storage paths identically from IDE and terminal.
    # This must happen before app.main imports the database configuration.
    os.chdir(Path(__file__).resolve().parent)
    import uvicorn

    # A single process lets IDE breakpoints hit API and local background tasks.
    uvicorn.run("app.main:app", host=args.host, port=args.port,
                reload=False, workers=1, access_log=False)


if __name__ == "__main__":
    main() 
