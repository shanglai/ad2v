"""Operator CLI for the worker."""

import json
from pathlib import Path

import typer

from recon_worker.events import listen
from recon_worker.jobs import run_nightly

app = typer.Typer()


@app.command("run-nightly")
def run_nightly_cmd(path: Path) -> None:
    transactions = json.loads(path.read_text())
    run_nightly(transactions)


@app.command()
def listen_uploads() -> None:
    listen()


if __name__ == "__main__":
    app()
