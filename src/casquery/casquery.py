#!/usr/bin/env python

from __future__ import annotations

import csv
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from enum import Enum
from pathlib import Path
from typing import Any

import requests
import typer
from rich import box
from rich.console import Console
from rich.progress import track
from rich.table import Table

__version__ = "0.2.2"
__vdate = "2025-11-19"

BASE_URL = "https://cdxapps.epa.gov/oms-substance-registry-services/rest-api/substance/cas"

console = Console()
app = typer.Typer(add_completion=False, help="CAS RN utility for EPA SRS.")


# ---------- Core helpers ----------


class OutputFormat(str, Enum):
    TABLE = "table"
    JSON = "json"
    XML = "xml"
    CSV = "csv"


def normalize_cas(cas: str) -> str | None:
    """Normalize a CAS RN to the form 'XXXXXX-YY-Z'.

    Rules:
    - Strip all non-digits.
    - Require between 3 and 10 digits (CAS max).
    - Group as: [all but last 3]-[second to last 2]-[last digit].
    - First group must be at least 2 digits (per CAS convention).

    Returns None if it can't be normalized.
    """
    digits = re.sub(r"\D", "", cas or "")
    if len(digits) < 3 or len(digits) > 10:
        return None

    first = digits[:-3]
    second = digits[-3:-1]
    check = digits[-1]

    if len(first) < 2:
        return None

    return f"{first}-{second}-{check}"


def send_request(url: str) -> list[dict] | None:
    """Send an HTTP GET request and return parsed JSON or None on failure."""
    try:
        response = requests.get(url, timeout=5)
        if not response.ok:
            console.print(f"[yellow]Warning:[/yellow] Received status {response.status_code} for {url}")
            return None
        return response.json()
    except requests.RequestException as err:
        console.print(f"[bold red]Request error:[/bold red] {err}")
        return None


def casrn_search(
    cas_rn_list: list[str],
    synonyms: bool = False,
    output_format: OutputFormat = OutputFormat.TABLE,
) -> list[dict[str, Any]]:
    """Query EPA SRS for a list of CAS RN and return results as a list of dicts."""

    header = ["cas_rn", "systematicName", "epaName", "currentCasNumber"]
    if synonyms:
        header.append("synonyms")

    rows: list[dict[str, Any]] = []

    use_progress = output_format == OutputFormat.TABLE

    iter_cas = track(cas_rn_list, description="Querying EPA SRS") if use_progress else cas_rn_list

    for cas_rn in iter_cas:
        cleaned_norm = normalize_cas(cas_rn)
        cleaned = cleaned_norm if cleaned_norm else re.sub(r"[^a-zA-Z0-9-]", "", cas_rn)

        url = f"{BASE_URL}/{cleaned}?qualifier=exact"
        result = send_request(url)

        row: dict[str, Any] = dict.fromkeys(header)
        row["cas_rn"] = cleaned

        if result:
            r0 = result[0]
            row["systematicName"] = r0.get("systematicName")
            row["epaName"] = r0.get("epaName")
            row["currentCasNumber"] = r0.get("currentCasNumber")

            if synonyms:
                syns = r0.get("synonyms", [])
                row["synonyms"] = ";".join(s.get("synonymName", "") for s in syns if s.get("synonymName")) or None

        rows.append(row)

    rows.sort(
        key=lambda r: (
            r.get("currentCasNumber") or "",
            r.get("cas_rn") or "",
        ),
    )

    return rows


# ---------- Output helpers ----------


def print_table(rows: list[dict[str, Any]]) -> None:
    """Render the results as a Rich table."""
    if not rows:
        console.print("[yellow]No results returned.[/yellow]")
        return

    headers = list(rows[0].keys())

    table = Table(
        title="EPA SRS CASRN Search Results",
        box=box.MINIMAL_DOUBLE_HEAD,
        show_lines=False,
        header_style="bold cyan",
    )

    for col in headers:
        table.add_column(col)

    for row in rows:
        table.add_row(*[("" if row[col] is None else str(row[col])) for col in headers])

    console.print()
    console.print(table)
    console.print()


def rows_to_csv_stdout(rows: list[dict[str, Any]]) -> None:
    """Write rows as CSV to stdout."""
    if not rows:
        return
    headers = list(rows[0].keys())
    writer = csv.DictWriter(sys.stdout, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    sys.stdout.flush()


def rows_to_json_stdout(rows: list[dict[str, Any]]) -> None:
    """Write rows as JSON to stdout."""
    json.dump(rows, sys.stdout, indent=2)
    sys.stdout.write("\n")
    sys.stdout.flush()


def rows_to_xml_stdout(rows: list[dict[str, Any]]) -> None:
    """Write rows as a simple XML document to stdout."""
    root = ET.Element("casResults")
    for row in rows:
        item = ET.SubElement(root, "result")
        for key, value in row.items():
            child = ET.SubElement(item, key)
            child.text = "" if value is None else str(value)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(sys.stdout, encoding="unicode", xml_declaration=False)
    sys.stdout.write("\n")
    sys.stdout.flush()


def write_csv_file(rows: list[dict[str, Any]], out_path: str) -> None:
    """Write results to a CSV file."""
    if not rows:
        console.print("[yellow]No results to write, CSV will not be created.[/yellow]")
        raise typer.Exit(1)

    headers = list(rows[0].keys())

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    console.print(f"\n[bold green]Results written to {out_path}[/bold green]")


# ---------- Global callback (version) ----------


@app.callback(invoke_without_command=True)
def app_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        is_eager=True,
    ),
) -> None:
    """Global options callback."""
    if version:
        script_name = os.path.basename(sys.argv[0])
        console.print(f"[bold cyan]{script_name}[/bold cyan] v{__version__} ({__vdate})")
        raise typer.Exit()

    # If no subcommand was provided and no --version, show help
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(1)


# ---------- Commands ----------


@app.command()
def search(
    cas_rn: list[str] = typer.Argument(
        ...,
        help="CAS RN or list of CAS RN to search in EPA SRS.",
    ),
    synonyms: bool = typer.Option(
        False,
        "--synonyms",
        "-s",
        help="Include chemical synonyms in the output.",
    ),
    output_format: OutputFormat = typer.Option(
        OutputFormat.TABLE,
        "--format",
        "-F",
        help="Output format: table, json, xml, csv.",
        case_sensitive=False,
    ),
    file: bool = typer.Option(
        False,
        "--file",
        "-f",
        help="Write results to casquery.csv instead of printing to stdout.",
    ),
) -> None:
    """Search the EPA Substance Registry Service (SRS) by CAS RN."""

    rows = casrn_search(
        cas_rn_list=cas_rn,
        synonyms=synonyms,
        output_format=output_format,
    )

    if file:
        write_csv_file(rows, "casquery.csv")
        return

    match output_format:
        case OutputFormat.TABLE:
            print_table(rows)
        case OutputFormat.JSON:
            rows_to_json_stdout(rows)
        case OutputFormat.XML:
            rows_to_xml_stdout(rows)
        case OutputFormat.CSV:
            rows_to_csv_stdout(rows)


@app.command()
def normalize(
    cas_rn: list[str] = typer.Argument(
        ...,
        help="One or more CAS RN strings to normalize.",
    ),
) -> None:
    """Normalize a raw CAS string into the standard CAS format (X...X-XX-X).

    This method does NOT validate that the CAS RN is real.
    It simply applies the CAS hyphenation rules to digit sequences and
    returns a best-effort normalized string.

    Behavior:
    - Removes all non-digit characters from the input.
    - Requires 3-10 digits (CAS numbers cannot exceed 10).
    - Formats as: [all digits except last 3]-[next 2 digits]-[last digit].
    - Returns None if the input cannot be sensibly reformatted.

    This is useful for cleaning messy input (e.g., “1234567”, “12 34-56 7”),
    but it does NOT imply that the resulting CAS number actually exists.
    """
    for raw in cas_rn:
        norm = normalize_cas(raw)
        if norm:
            console.print(f"[cyan]{raw}[/cyan] -> [green]{norm}[/green]")
        else:
            console.print(f"[cyan]{raw}[/cyan] -> [red]invalid / cannot normalize[/red]")


@app.command()
def resolve(
    cas_rn: str = typer.Argument(
        ...,
        help="CAS RN to resolve to the current CAS according to EPA SRS.",
    ),
) -> None:
    """Resolve a CAS RN to its currentCasNumber using EPA SRS."""
    norm = normalize_cas(cas_rn)
    if not norm:
        console.print("[red]Input CAS RN is not structurally valid.[/red]")
        raise typer.Exit(1)

    rows = casrn_search([norm], synonyms=False, output_format=OutputFormat.TABLE)
    if not rows or rows[0].get("currentCasNumber") is None:
        console.print("[yellow]No resolution information found for this CAS RN.[/yellow]")
        raise typer.Exit(0)

    current = rows[0]["currentCasNumber"]
    if current == norm:
        console.print(f"[green]{norm}[/green] is already the current CAS RN (no supersession).")
    else:
        console.print(f"[cyan]{norm}[/cyan] -> current CAS RN: [bold green]{current}[/bold green]")


@app.command()
def batch(
    input_csv: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Input CSV file containing a column of CAS RN values.",
    ),
    column: str = typer.Option(
        "cas_rn",
        "--column",
        "-c",
        help="Name of the column in the CSV that contains CAS RN values.",
    ),
    output_csv: Path = typer.Option(
        Path("casquery_batch.csv"),
        "--output",
        "-o",
        help="Output CSV file path.",
    ),
) -> None:
    """Batch-process a CSV of CAS RN: normalize, resolve, and attach EPA SRS metadata."""

    console.print(f"[bold cyan]CASRN Batch Processing[/bold cyan] v{__version__} ({__vdate})\n")

    with input_csv.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        console.print("[yellow]Input CSV has no rows.[/yellow]")
        raise typer.Exit(1)

    if column not in rows[0]:
        console.print(f"[red]Column '{column}' not found in CSV header.[/red]")
        raise typer.Exit(1)

    unique_norms: set[str] = set()
    for row in rows:
        raw = row.get(column, "") or ""
        norm = normalize_cas(raw)
        row["casquery_normalized"] = norm or ""

        if norm:
            unique_norms.add(norm)

    result_map: dict[str, dict[str, Any]] = {}
    if unique_norms:
        cas_list = sorted(unique_norms)
        resolution_rows = casrn_search(cas_list, synonyms=False, output_format=OutputFormat.TABLE)
        for r in resolution_rows:
            key = r.get("cas_rn")
            if key:
                result_map[key] = r

    for row in rows:
        norm = row.get("casquery_normalized") or ""
        srs = result_map.get(norm) if norm else None

        if srs:
            row["casquery_resolved"] = srs.get("currentCasNumber") or ""
            row["casquery_systematicName"] = srs.get("systematicName") or ""
            row["casquery_epaName"] = srs.get("epaName") or ""
        else:
            row["casquery_resolved"] = ""
            row["casquery_systematicName"] = ""
            row["casquery_epaName"] = ""

    fieldnames = list(rows[0].keys())
    for extra in [
        "casquery_normalized",
        "casquery_resolved",
        "casquery_systematicName",
        "casquery_epaName",
    ]:
        if extra not in fieldnames:
            fieldnames.append(extra)

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    console.print(f"[bold green]Batch results written to {output_csv}[/bold green]")


if __name__ == "__main__":
    app()
