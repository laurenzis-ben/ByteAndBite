"""ByteAndBite – Rezept-Pipeline CLI."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

import config
from pipeline.normalize import normalize_batch
from pipeline.nutrition import enrich_nutrition
from pipeline.store import store_recipes

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ByteAndBite Rezept-Pipeline: Rezepte aufbereiten und speichern."
    )
    parser.add_argument(
        "--source",
        choices=["dataset", "scraper"],
        default="dataset",
        help="Datenquelle (default: dataset)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Anzahl zu verarbeitender Rezepte (default: 10)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=config.DEFAULT_OUTPUT_DIR,
        help="Ausgabeverzeichnis für JSON-Dateien (default: ./output)",
    )
    parser.add_argument(
        "--skip-nutrition",
        action="store_true",
        help="Nährwertlookup überspringen (schnellerer Test)",
    )
    parser.add_argument(
        "--scraper-query",
        default="Hauptgericht",
        help="Suchbegriff für den Chefkoch-Scraper (default: Hauptgericht)",
    )
    parser.add_argument(
        "--data-path",
        type=Path,
        default=None,
        help=(
            "Pfad zur lokalen recipes.json (Kaggle-Download). "
            "Ohne dieses Flag: automatischer Download via Kaggle-API."
        ),
    )
    parser.add_argument(
        "--db",
        action="store_true",
        help="Rezepte in PostgreSQL speichern (statt JSON-Dateien).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help=(
            "PostgreSQL-Verbindungs-URL. Überschreibt DATABASE_URL aus .env. "
            "Format: postgresql+asyncpg://user:pass@host:port/dbname"
        ),
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    if not config.OPENAI_API_KEY:
        console.print("[bold red]Fehler:[/] OPENAI_API_KEY nicht gesetzt. Bitte .env anlegen.")
        sys.exit(1)

    # DB-Engine bei Bedarf initialisieren
    if args.db:
        from db.session import create_tables, init_engine
        init_engine(args.db_url)
        await create_tables()
        console.print("[dim]Datenbanktabellen bereit.[/]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:

        # ── 1. Daten laden ────────────────────────────────────────────────────
        task = progress.add_task(f"[cyan]Lade {args.limit} Rezepte ({args.source})…", total=None)
        if args.source == "scraper":
            from pipeline.acquire.scraper import ScraperSource
            source = ScraperSource(query=args.scraper_query)
        else:
            from pipeline.acquire.dataset import DatasetSource
            source = DatasetSource(data_path=args.data_path)
        raw_recipes = source.fetch(args.limit)
        progress.update(task, description=f"[green]✓ {len(raw_recipes)} Rezepte geladen")

        # ── 2. LLM-Normalisierung ─────────────────────────────────────────────
        task = progress.add_task("[cyan]Normalisiere via GPT-4o…", total=None)
        processed = await normalize_batch(raw_recipes)
        progress.update(task, description=f"[green]✓ {len(processed)} Rezepte normalisiert")

        # ── 3. Nährwerte ──────────────────────────────────────────────────────
        if not args.skip_nutrition:
            task = progress.add_task("[cyan]Nährwerte via USDA FoodData Central…", total=None)
            processed = await enrich_nutrition(processed)
            progress.update(task, description="[green]✓ Nährwerte angereichert")
        else:
            console.print("[yellow]─ Nährwertlookup übersprungen (--skip-nutrition)[/]")

        # ── 4. Speichern ──────────────────────────────────────────────────────
        if args.db:
            from pipeline.store_db import save_recipes_to_db
            task = progress.add_task("[cyan]Speichere in PostgreSQL…", total=None)
            saved = await save_recipes_to_db(processed)
            progress.update(task, description=f"[green]✓ {saved} Rezepte in DB gespeichert")
        else:
            task = progress.add_task("[cyan]Speichere JSON…", total=None)
            saved = store_recipes(processed, args.output)
            progress.update(task, description=f"[green]✓ {saved} Rezepte gespeichert")

    if args.db:
        db_url = args.db_url or config.DATABASE_URL
        console.print(
            f"\n[bold green]Fertig![/] {saved} neue Rezepte in PostgreSQL gespeichert.\n"
            f"  Datenbank: [cyan]{db_url}[/]"
        )
    else:
        console.print(
            f"\n[bold green]Fertig![/] {saved} neue Rezepte in [cyan]{args.output}[/]\n"
            f"  Manifest: [cyan]{args.output / 'manifest.json'}[/]"
        )


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
