import csv
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from casquery import casquery

runner = CliRunner()


# -----------------------
# Helpers / fixtures
# -----------------------


@pytest.fixture(autouse=True)
def no_progress(monkeypatch):
    """Disable rich.progress.track in tests to avoid noisy output."""

    def _track(iterable, **kwargs):
        return iterable

    monkeypatch.setattr(casquery, "track", _track)
    yield


# -----------------------
# normalize_cas tests
# -----------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234567", "1234-56-7"),
        ("1234-56-7", "1234-56-7"),
        ("12 34 56 7", "1234-56-7"),
        ("  375-73-5  ", "375-73-5"),
        ("375735", "375-73-5"),
    ],
)
def test_normalize_cas_valid(raw: str, expected: str) -> None:
    assert casquery.normalize_cas(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",  # empty
        "1",  # too short
        "12",  # too short
        "123",  # first group only 0 digits (invalid by our rule)
        "12345678901",  # too long (> 10 digits)
    ],
)
def test_normalize_cas_invalid(raw: str) -> None:
    assert casquery.normalize_cas(raw) is None


# -----------------------
# casrn_search tests
# -----------------------


def test_casrn_search_basic(monkeypatch) -> None:
    """casrn_search should return sorted rows with basic metadata."""

    def fake_send_request(url: str) -> list[dict] | None:
        # Extract CAS from the URL (.../cas/{cas}?qualifier=exact)
        cas = url.rsplit("/", 1)[-1].split("?", 1)[0]
        data: dict[str, dict[str, Any]] = {
            "375-73-5": {
                "systematicName": "Perfluorobutane sulfonic acid",
                "epaName": "PFBS",
                "currentCasNumber": "375-73-5",
            },
            "29420-43-3": {
                "systematicName": "Perfluorobutanesulfonic acid, potassium salt",
                "epaName": "PFBS potassium salt",
                "currentCasNumber": "375-73-5",
            },
        }
        if cas in data:
            return [data[cas]]
        return []

    monkeypatch.setattr(casquery, "send_request", fake_send_request)

    rows = casquery.casrn_search(["29420-43-3", "375-73-5"], synonyms=False, verbose=False)

    # Should return 2 rows
    assert len(rows) == 2

    # Should be sorted by currentCasNumber then cas_rn
    cas_list = [r["cas_rn"] for r in rows]
    assert cas_list == ["29420-43-3", "375-73-5"]

    # Check fields
    pfbs_potassium = rows[0]
    pfbs_acid = rows[1]

    assert pfbs_potassium["currentCasNumber"] == "375-73-5"
    assert pfbs_acid["currentCasNumber"] == "375-73-5"


def test_casrn_search_synonyms(monkeypatch) -> None:
    """casrn_search should join synonyms when requested."""

    def fake_send_request(url: str) -> list[dict] | None:
        cas = url.rsplit("/", 1)[-1].split("?", 1)[0]
        if cas == "375-73-5":
            return [
                {
                    "systematicName": "Perfluorobutane sulfonic acid",
                    "epaName": "PFBS",
                    "currentCasNumber": "375-73-5",
                    "synonyms": [
                        {"synonymName": "PFBS"},
                        {"synonymName": "Perfluorobutane sulfonate"},
                    ],
                },
            ]
        return []

    monkeypatch.setattr(casquery, "send_request", fake_send_request)

    rows = casquery.casrn_search(["375-73-5"], synonyms=True, verbose=False)
    assert len(rows) == 1
    row = rows[0]
    assert row["synonyms"] == "PFBS;Perfluorobutane sulfonate"


# -----------------------
# batch tests
# -----------------------


def test_batch_adds_metadata(monkeypatch, tmp_path: Path) -> None:
    """batch should add normalized + SRS metadata columns to the CSV."""

    # Prepare input CSV
    input_csv = tmp_path / "input.csv"
    with input_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_id", "cas_rn"])
        writer.writeheader()
        writer.writerow({"sample_id": "S1", "cas_rn": "375735"})
        writer.writerow({"sample_id": "S2", "cas_rn": "29420433"})

    output_csv = tmp_path / "output.csv"

    def fake_casrn_search(cas_rn_list: list[str], synonyms: bool = False, verbose: bool = False):
        # cas_rn_list will contain normalized CAS numbers
        out = []
        for cas in cas_rn_list:
            if cas == "375-73-5":
                out.append(
                    {
                        "cas_rn": "375-73-5",
                        "systematicName": "Perfluorobutane sulfonic acid",
                        "epaName": "PFBS",
                        "currentCasNumber": "375-73-5",
                    },
                )
            elif cas == "29420-43-3":
                out.append(
                    {
                        "cas_rn": "29420-43-3",
                        "systematicName": "Perfluorobutanesulfonic acid, potassium salt",
                        "epaName": "PFBS potassium salt",
                        "currentCasNumber": "375-73-5",
                    },
                )
        # Sort same as real casrn_search
        out.sort(key=lambda r: (r.get("currentCasNumber") or "", r.get("cas_rn") or ""))
        return out

    monkeypatch.setattr(casquery, "casrn_search", fake_casrn_search)

    # Call batch directly (as a function, not via CLI)
    casquery.batch(
        input_csv=input_csv,
        column="cas_rn",
        output_csv=output_csv,
        verbose=False,
    )

    # Read the output and verify
    with output_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        out_rows = list(reader)

    assert len(out_rows) == 2

    # Check columns exist
    for col in [
        "casquery_normalized",
        "casquery_resolved",
        "casquery_systematicName",
        "casquery_epaName",
    ]:
        assert col in reader.fieldnames

    r1 = out_rows[0]
    r2 = out_rows[1]

    # Order depends on input file order, so find by sample_id
    row_s1 = r1 if r1["sample_id"] == "S1" else r2
    row_s2 = r1 if r1["sample_id"] == "S2" else r2

    assert row_s1["casquery_normalized"] == "375-73-5"
    assert row_s1["casquery_resolved"] == "375-73-5"
    assert row_s1["casquery_epaName"] == "PFBS"

    assert row_s2["casquery_normalized"] == "29420-43-3"
    assert row_s2["casquery_resolved"] == "375-73-5"
    assert "potassium" in row_s2["casquery_systematicName"]


# -----------------------
# CLI tests (Typer)
# -----------------------


def test_cli_version() -> None:
    result = runner.invoke(casquery.app, ["-V"])
    assert result.exit_code == 0
    assert casquery.__version__ in result.stdout


def test_cli_search_json(monkeypatch) -> None:
    """search subcommand with JSON output should print valid JSON."""

    def fake_casrn_search(cas_rn_list, synonyms=False, verbose=False):
        return [
            {
                "cas_rn": "375-73-5",
                "systematicName": "Perfluorobutane sulfonic acid",
                "epaName": "PFBS",
                "currentCasNumber": "375-73-5",
            },
        ]

    monkeypatch.setattr(casquery, "casrn_search", fake_casrn_search)

    result = runner.invoke(
        casquery.app,
        ["search", "375-73-5", "--format", "json"],
    )
    assert result.exit_code == 0

    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert data[0]["cas_rn"] == "375-73-5"


def test_cli_search_table(monkeypatch) -> None:
    """search subcommand with table output should succeed and show CAS in output."""

    def fake_casrn_search(cas_rn_list, synonyms=False, verbose=False):
        return [
            {
                "cas_rn": "375-73-5",
                "systematicName": "Perfluorobutane sulfonic acid",
                "epaName": "PFBS",
                "currentCasNumber": "375-73-5",
            },
        ]

    monkeypatch.setattr(casquery, "casrn_search", fake_casrn_search)

    result = runner.invoke(
        casquery.app,
        ["search", "375-73-5", "--format", "table"],
    )
    assert result.exit_code == 0
    # Rich prints a table, just sanity-check CAS appears
    assert "375-73-5" in result.stdout


def test_cli_normalize_command() -> None:
    result = runner.invoke(casquery.app, ["normalize", "1234567"])
    assert result.exit_code == 0
    assert "1234-56-7" in result.stdout


def test_cli_resolve(monkeypatch) -> None:
    """resolve should print message mapping given CAS to current CAS."""

    def fake_casrn_search(cas_rn_list, synonyms=False, verbose=False):
        return [
            {
                "cas_rn": "29420-43-3",
                "systematicName": "Perfluorobutanesulfonic acid, potassium salt",
                "epaName": "PFBS potassium salt",
                "currentCasNumber": "375-73-5",
            },
        ]

    monkeypatch.setattr(casquery, "casrn_search", fake_casrn_search)

    result = runner.invoke(casquery.app, ["resolve", "29420-43-3"])
    assert result.exit_code == 0
    assert "375-73-5" in result.stdout
