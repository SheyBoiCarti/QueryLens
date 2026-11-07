"""Task 08.06 & Phase 08 Unit Tests: RFC 4180 CSV export and formula injection mitigation.

Contracts: C02, C07, C09.
Assertions:
1. Headers and cells beginning with =, +, -, @, tab, CR, LF, pipe are neutralized with prepended quote.
2. Leading whitespace is preserved when neutralizing formulas.
3. RFC 4180 quoting and quote-doubling is applied.
4. Exact numeric decimals and big integers are serialized without float conversion or scientific notation.
5. Post-escaping byte overflow raises error before sending data.
"""

from __future__ import annotations

import pytest

from querylens.export.csv import (
    ResultTooLargeError,
    escape_csv_field,
    generate_csv_string,
)


def test_formula_injection_neutralization() -> None:
    dangerous_inputs = [
        "=SUM(1,2)",
        "+12345",
        "-5000",
        "@CMD",
        "\tcmd.exe",
        "\rcalc",
        "\nnotepad",
        "|malicious",
        "   =1+1",
        "  -99.99",
    ]

    for inp in dangerous_inputs:
        escaped = escape_csv_field(inp)
        # Quoted string starting with single quote inside quotes: "'..."
        # e.g. '"\'=SUM(1,2)"' or '"\'   =1+1"'
        assert escaped.startswith('"\''), f"Failed to neutralize formula prefix for: {inp}"


def test_ordinary_text_and_whitespace_preservation() -> None:
    # Safe text should not have leading single quote added
    normal_text = "  Hello, world!  "
    escaped = escape_csv_field(normal_text)
    assert escaped == '"  Hello, world!  "'

    # Embedded quotes doubled under RFC 4180
    with_quotes = 'Quote: "Hello"'
    escaped_quotes = escape_csv_field(with_quotes)
    assert escaped_quotes == '"Quote: ""Hello"""'


def test_exact_numeric_precision_preserved() -> None:
    big_int = "9007199254740993"
    decimal_str = "12345678901234567890.1234567890"

    # Positive numbers
    escaped_int = escape_csv_field(big_int)
    assert escaped_int == f'"{big_int}"'

    escaped_dec = escape_csv_field(decimal_str)
    assert escaped_dec == f'"{decimal_str}"'

    # Null converts to empty string
    assert escape_csv_field(None) == '""'


def test_generate_csv_string() -> None:
    columns = [
        {"name": "id", "type": "integer"},
        {"name": "name", "type": "string"},
        {"name": "balance", "type": "decimal"},
    ]
    rows = [
        {"id": "1", "name": "Alice", "balance": "100.50"},
        {"id": "2", "name": '=CMD("calc")', "balance": "-50.00"},
    ]

    csv_out = generate_csv_string(columns, rows)
    lines = csv_out.split("\r\n")

    assert lines[0] == '"id","name","balance"'
    assert lines[1] == '"1","Alice","100.50"'
    # Formula neutralized
    assert lines[2] == '"2","\'=CMD(""calc"")","\'-50.00"'


def test_byte_overflow_protection() -> None:
    columns = [{"name": "huge", "type": "string"}]
    # Single row of 2MB
    huge_rows = [{"huge": "A" * 2_000_000}]

    with pytest.raises(ResultTooLargeError):
        generate_csv_string(columns, huge_rows, max_bytes=1048576)
