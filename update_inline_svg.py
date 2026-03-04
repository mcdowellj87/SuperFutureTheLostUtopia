#!/usr/bin/env python3
"""Replace an inline SVG block in an HTML file with content from a source SVG."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path


SVG_BLOCK_RE = re.compile(r"<svg\b[\s\S]*?</svg>", re.IGNORECASE)
STATE_DB_FILE = ".update_inline_svg_state.db"
STATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS last_run (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    svg_id TEXT NOT NULL,
    svg_filename TEXT NOT NULL,
    html_path TEXT NOT NULL
)
"""


def extract_svg_block(svg_text: str) -> str:
    match = SVG_BLOCK_RE.search(svg_text)
    if not match:
        raise ValueError("No <svg>...</svg> block found in source SVG file.")
    return match.group(0)


def replace_or_set_svg_id(svg_block: str, svg_id: str) -> str:
    open_tag_match = re.search(r"<svg\b[^>]*>", svg_block, re.IGNORECASE)
    if not open_tag_match:
        raise ValueError("Invalid SVG block: missing opening <svg> tag.")

    open_tag = open_tag_match.group(0)
    if re.search(r"\bid\s*=", open_tag, re.IGNORECASE):
        new_open_tag = re.sub(
            r'\bid\s*=\s*(".*?"|\'.*?\')',
            f'id="{svg_id}"',
            open_tag,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        new_open_tag = open_tag[:-1] + f' id="{svg_id}">'

    return svg_block.replace(open_tag, new_open_tag, 1)


def update_inline_svg(html_text: str, new_svg_block: str, svg_id: str) -> str:
    target_re = re.compile(
        rf"<svg\b[^>]*\bid\s*=\s*['\"]{re.escape(svg_id)}['\"][\s\S]*?</svg>",
        re.IGNORECASE,
    )
    target_match = target_re.search(html_text)
    if not target_match:
        raise ValueError(
            f'No inline SVG with id="{svg_id}" found in target HTML file.'
        )
    return html_text[: target_match.start()] + new_svg_block + html_text[target_match.end() :]


def init_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(STATE_TABLE_SQL)
        conn.commit()


def load_last_params(db_path: Path) -> tuple[str, str, str] | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT svg_id, svg_filename, html_path FROM last_run WHERE id = 1"
        ).fetchone()
    if row is None:
        return None
    return row[0], row[1], row[2]


def save_last_params(db_path: Path, svg_id: str, svg_filename: str, html_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO last_run (id, svg_id, svg_filename, html_path)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                svg_id = excluded.svg_id,
                svg_filename = excluded.svg_filename,
                html_path = excluded.html_path
            """,
            (svg_id, svg_filename, html_path),
        )
        conn.commit()


def format_last_command(last: tuple[str, str, str] | None) -> str:
    if last is None:
        return "(none yet)"
    svg_id, svg_filename, html_path = last
    return f"python3 update_inline_svg.py {svg_id} {svg_filename} --html {html_path}"


def parse_args(last: tuple[str, str, str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Update an inline SVG in an HTML file from a supplied SVG file in the "
            "same directory as this script. Designed for pipeline use."
        ),
        epilog=f"Last used: {format_last_command(last)}",
    )
    parser.add_argument("svg_id", nargs="?", help="Inline SVG id to replace in target HTML.")
    parser.add_argument(
        "svg_filename",
        nargs="?",
        help="SVG filename located in the same directory as this script.",
    )
    parser.add_argument(
        "--html",
        default="intro.html",
        help="Target HTML file path (default: intro.html).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report changes without writing files.",
    )
    return parser.parse_args()


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    db_path = script_dir / STATE_DB_FILE
    init_db(db_path)
    last = load_last_params(db_path)
    args = parse_args(last)

    if args.svg_id is None and args.svg_filename is None:
        print(f"Last used: {format_last_command(last)}")
        return 0
    if args.svg_id is None or args.svg_filename is None:
        print("Error: provide both svg_id and svg_filename.", file=sys.stderr)
        print(f"Last used: {format_last_command(last)}", file=sys.stderr)
        return 1

    svg_id = args.svg_id
    svg_filename = args.svg_filename
    html_value = args.html

    svg_path = script_dir / svg_filename
    html_path = Path(html_value)

    if not svg_path.is_file():
        print(f"Error: SVG file not found: {svg_path}", file=sys.stderr)
        return 1
    if not html_path.is_file():
        print(f"Error: HTML file not found: {html_path}", file=sys.stderr)
        return 1

    svg_text = svg_path.read_text(encoding="utf-8")
    html_text = html_path.read_text(encoding="utf-8")

    try:
        svg_block = extract_svg_block(svg_text)
        svg_block = replace_or_set_svg_id(svg_block, svg_id)
        updated_html = update_inline_svg(html_text, svg_block, svg_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    save_last_params(db_path, svg_id, svg_filename, str(html_path))

    if updated_html == html_text:
        print("No changes needed.")
        return 0

    if args.dry_run:
        print(
            f"Dry run: would update inline SVG id=\"{svg_id}\" in {html_path} "
            f"from {svg_path.name}."
        )
        return 0

    html_path.write_text(updated_html, encoding="utf-8")
    print(
        f"Updated inline SVG id=\"{svg_id}\" in {html_path} "
        f"from {svg_path.name}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
