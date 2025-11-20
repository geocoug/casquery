# casquery

[![ci/cd](https://github.com/geocoug/casquery/actions/workflows/ci-cd.yaml/badge.svg)](https://github.com/geocoug/casquery/actions/workflows/ci-cd.yaml)

Query the **EPA Substance Registry Service (SRS)** using **CAS Registry Numbers (CASRN)**.

`casquery` provides:

- A command-line tool for searching CASRN records
- Normalization of messy CAS numbers
- CAS resolution (superseded → current CASRN)
- Batch processing of CSVs
- Multiple output formats (table, JSON, XML, CSV)

It works both as:

- A **standalone script** (`python casquery.py`)
- A **PyPI-installable CLI** (`casquery …`)

## Installation

```sh
# From PyPI
pip install casquery
# Or pip install git+
pip install "git+https://github.com/geocoug/casquery.git"
```

## Command Line Usage

```sh
# Help
casquery --help
casquery search --help

# Search EPA SRS
casquery search 375-73-5 29420-43-3

# Search with synonyms
casquery search --synonyms 375-73-5

# Output formats
casquery search 375-73-5 --format json
casquery search 375-73-5 --format xml
casquery search 375-73-5 --format csv

# Normalize CAS numbers
casquery normalize 1234567
# → 1234-56-7

# Resolve superseded CAS numbers
casquery resolve 29420-43-3

# Batch-process a CSV (Input CSV must contain a column of CASRN values.)
casquery batch input.csv --column analyte_cas --output cleaned.csv
```

## Examples

Search for two CAS numbers

```sh
casquery search 7440-66-6 7440097

╭───────────────────────────────────────────────╮
│        EPA SRS CASRN Search Results           │
╰───────────────────────────────────────────────╯
cas_rn     systematicName     epaName     currentCasNumber
---------  ------------------  ----------  -----------------
7440-66-6  Zinc                Zinc        7440-66-6
7440-09-7  Potassium           Potassium   7440-09-7
```

Output JSON instead of a table

```sh
casquery search --format json 7440-66-6 7440-09-7

[
  {
    "cas_rn": "7440-09-7",
    "systematicName": "Potassium",
    "epaName": "Potassium",
    "currentCasNumber": "7440-09-7"
  },
  {
    "cas_rn": "7440-66-6",
    "systematicName": "Zinc",
    "epaName": "Zinc",
    "currentCasNumber": "7440-66-6"
  }
]
```
