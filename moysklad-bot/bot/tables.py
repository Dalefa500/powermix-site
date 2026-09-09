from __future__ import annotations

from html import escape


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    """Monospace, column-aligned table for Telegram — wrapped in an HTML
    <pre> block so it renders like a little spreadsheet instead of a wall
    of "label: value" lines.
    """
    esc_headers = [escape(h) for h in headers]
    esc_rows = [[escape(str(cell)) for cell in row] for row in rows]

    widths = [len(h) for h in esc_headers]
    for row in esc_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells: list[str]) -> str:
        *rest, last = cells
        parts = [cell.ljust(widths[i]) for i, cell in enumerate(rest)]
        parts.append(last)
        return "  ".join(parts)

    lines = [fmt_row(esc_headers), fmt_row(["-" * w for w in widths])]
    lines += [fmt_row(row) for row in esc_rows]
    return "<pre>" + "\n".join(lines) + "</pre>"


def render_table_chunks(
    headers: list[str], rows: list[list[str]], max_rows: int = 60
) -> list[str]:
    """Split rows into several self-contained tables of at most max_rows
    each, so a single Telegram message never exceeds Telegram's ~4096
    character limit for long lists (e.g. years of accumulated stock items).
    """
    if not rows:
        return [render_table(headers, rows)]
    return [
        render_table(headers, rows[i : i + max_rows]) for i in range(0, len(rows), max_rows)
    ]
