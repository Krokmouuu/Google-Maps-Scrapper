import argparse
import csv
import os
from typing import List, Tuple

import pandas as pd

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    TK_AVAILABLE = True
except ModuleNotFoundError:
    tk = None
    filedialog = None
    messagebox = None
    ttk = None
    TK_AVAILABLE = False


def read_csv_with_fallback(path: str) -> pd.DataFrame:
    """Read CSV with common encoding fallbacks to preserve accents and symbols."""
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    last_error = None
    for enc in encodings:
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError as exc:
            last_error = exc
        except Exception:
            # Keep trying fallbacks for malformed exports.
            pass
    raise RuntimeError(f"Could not read CSV with tested encodings: {last_error}")


def preferred_columns(columns: List[str]) -> List[str]:
    """Show business-friendly columns first when present."""
    wanted_order = [
        "name",
        "address",
        "phone_number",
        "website",
        "place_type",
        "reviews_count",
        "reviews_average",
        "opens_at",
        "introduction",
    ]
    existing = [c for c in wanted_order if c in columns]
    remaining = [c for c in columns if c not in existing]
    return existing + remaining


def dataframe_to_rows(df: pd.DataFrame) -> Tuple[List[str], List[List[str]]]:
    # Replace NaN by empty string for cleaner display.
    display_df = df.fillna("")
    columns = preferred_columns(display_df.columns.tolist())
    display_df = display_df[columns]

    rows: List[List[str]] = []
    for _, row in display_df.iterrows():
        values = [str(row[col]).strip() for col in columns]
        rows.append(values)
    return columns, rows

def sort_dataframe(df: pd.DataFrame, sort_by: str = "", desc: bool = False) -> pd.DataFrame:
    if not sort_by:
        return df
    if sort_by not in df.columns:
        raise ValueError(f"Column not found for sorting: {sort_by}")
    return df.sort_values(by=sort_by, ascending=not desc, kind="mergesort")


if TK_AVAILABLE:
    class CsvViewer(tk.Tk):
        def __init__(self, csv_path: str):
            super().__init__()
            self.title("CSV Viewer")
            self.geometry("1280x720")
            self.minsize(1000, 580)

            self.csv_path = csv_path
            self.df = read_csv_with_fallback(csv_path)
            self.columns, self.rows = dataframe_to_rows(self.df)
            self.sort_states = {col: False for col in self.columns}

            self._build_ui()
            self._populate_table()

        def _column_width(self, col: str) -> int:
            if col in {"name", "address", "website", "introduction"}:
                return 280
            if col in {"phone_number"}:
                return 170
            return 130

        def _build_ui(self) -> None:
            top = ttk.Frame(self, padding=8)
            top.pack(side=tk.TOP, fill=tk.X)

            ttk.Label(top, text=f"File: {self.csv_path}").pack(side=tk.LEFT, padx=(0, 10))
            ttk.Label(top, text=f"Rows: {len(self.rows)}").pack(side=tk.LEFT, padx=(0, 10))
            ttk.Button(top, text="Open Another CSV", command=self._open_another_csv).pack(side=tk.RIGHT)

            table_container = ttk.Frame(self)
            table_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

            self.table = ttk.Treeview(table_container, columns=self.columns, show="headings")
            self.table.grid(row=0, column=0, sticky="nsew")

            yscroll = ttk.Scrollbar(table_container, orient=tk.VERTICAL, command=self.table.yview)
            xscroll = ttk.Scrollbar(table_container, orient=tk.HORIZONTAL, command=self.table.xview)
            self.table.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
            yscroll.grid(row=0, column=1, sticky="ns")
            xscroll.grid(row=1, column=0, sticky="ew")

            table_container.rowconfigure(0, weight=1)
            table_container.columnconfigure(0, weight=1)

            self._refresh_headers()

        def _refresh_headers(self) -> None:
            for col in self.columns:
                self.table.heading(
                    col,
                    text=col,
                    command=lambda c=col: self._sort_by_column(c),
                )
                self.table.column(col, width=self._column_width(col), anchor=tk.W)

        def _sort_by_column(self, col: str) -> None:
            ascending = self.sort_states.get(col, False)
            self.df = self.df.sort_values(by=col, ascending=ascending, kind="mergesort")
            self.sort_states[col] = not ascending
            self.columns, self.rows = dataframe_to_rows(self.df)
            self._populate_table()

        def _populate_table(self) -> None:
            for item in self.table.get_children():
                self.table.delete(item)

            for row in self.rows:
                self.table.insert("", tk.END, values=row)

        def _open_another_csv(self) -> None:
            selected = filedialog.askopenfilename(
                title="Choose a CSV file",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            )
            if not selected:
                return
            try:
                self.csv_path = selected
                self.df = read_csv_with_fallback(selected)
                self.columns, self.rows = dataframe_to_rows(self.df)
                self.sort_states = {col: False for col in self.columns}
                self.table["columns"] = self.columns
                self._refresh_headers()
                self._populate_table()
                self.title("CSV Viewer")
            except Exception as exc:
                messagebox.showerror("Error", f"Could not load file:\n{exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="View a CSV in a clean interface.")
    parser.add_argument(
        "-f",
        "--file",
        type=str,
        default="result.csv",
        help="Path to CSV file (default: result.csv)",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=100,
        help="Number of rows to show in terminal mode (default: 100)",
    )
    parser.add_argument(
        "--sort-by",
        type=str,
        default="",
        help="Column name to sort by (terminal mode and initial GUI)",
    )
    parser.add_argument(
        "--desc",
        action="store_true",
        help="Sort in descending order (default: ascending).",
    )
    return parser.parse_args()


def ensure_csv_exists(path: str) -> str:
    if os.path.isfile(path):
        return path
    raise FileNotFoundError(
        f"File not found: {path}\nUse: python visualiser.py -f your_file.csv"
    )

def display_in_terminal(csv_path: str, max_rows: int, sort_by: str = "", desc: bool = False) -> None:
    """Fallback display when Tk is unavailable on the system Python."""
    df = read_csv_with_fallback(csv_path).fillna("")
    df = sort_dataframe(df, sort_by=sort_by, desc=desc)
    columns = preferred_columns(df.columns.tolist())
    df = df[columns]

    # Make long text columns easier to read in terminal output.
    for col in ["name", "address", "website", "introduction"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()

    print(f"File: {csv_path}")
    print(f"Total rows: {len(df)}")
    print("-" * 120)
    print(df.head(max_rows).to_string(index=False))
    if len(df) > max_rows:
        print("-" * 120)
        print(f"Display limited to {max_rows} rows. Use --rows to show more.")


def main() -> None:
    args = parse_args()
    csv_path = ensure_csv_exists(args.file)

    try:
        # Quick structural check to fail early on invalid CSV.
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            csv.Sniffer().sniff(f.read(4096))
    except Exception:
        # Not fatal; pandas can still open many non-standard CSV files.
        pass

    if not TK_AVAILABLE:
        print("Tkinter unavailable (_tkinter missing). Using terminal output mode.")
        display_in_terminal(
            csv_path,
            max_rows=max(1, args.rows),
            sort_by=args.sort_by,
            desc=args.desc,
        )
        return

    app = CsvViewer(csv_path)
    if args.sort_by:
        try:
            app.df = sort_dataframe(app.df, sort_by=args.sort_by, desc=args.desc)
            app.columns, app.rows = dataframe_to_rows(app.df)
            app._populate_table()
        except Exception as exc:
            print(f"Sort ignored: {exc}")
    app.mainloop()


if __name__ == "__main__":
    main()
