"""Pickup and weighbridge tracker. Run: python baselines/operator_performance_app.py

Uses only the Python standard library (including Tkinter). Save records with
Export CSV and restore them with Import CSV; records are not automatically saved.
One row represents one scheduled pickup with an assessed punctuality status.
Import replaces the current records after confirmation. Export uses the same schema.
Older CSV files with a delay_hours column can still be imported; it is ignored.
"""
from __future__ import annotations

import csv
from collections import Counter
from datetime import date
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

PUNCTUALITY = ("Early", "On time", "More than 2 hours late", "Missed pickup")
SHARING = ("Sent on time", "Sent late", "Not sent", "Pending")
FIELDS = ("pickup_id", "operator", "pickup_date", "punctuality", "sharing")


def validate(record):
    row = {key: str(record.get(key) or "").strip() for key in FIELDS}
    if not row["pickup_id"] or not row["operator"]:
        raise ValueError("Pickup ID and operator are required.")
    try:
        date.fromisoformat(row["pickup_date"])
    except ValueError as exc:
        raise ValueError("Pickup date must be YYYY-MM-DD.") from exc
    if row["punctuality"] not in PUNCTUALITY:
        raise ValueError("Choose a listed punctuality option.")
    if row["punctuality"] == "Missed pickup":
        # No completed pickup means no weighbridge ticket is expected.
        row["sharing"] = ""
    elif row["sharing"] not in SHARING:
        raise ValueError("Choose a listed weighbridge sharing option.")
    return row


def summarize(records):
    """Percentages are 0..100; unavailable rates are None.

    On-time rate is strictly 'On time' / all scheduled rows, including missed.
    Late rate is 'More than 2 hours late' / all scheduled rows, including missed.
    Sharing rates exclude missed pickups and Pending. Statuses are manually
    assessed against the agreed ticket deadline; no deadline is inferred here.
    """
    counts = Counter(r["punctuality"] for r in records)
    completed = [r for r in records if r["punctuality"] != "Missed pickup"]
    shares = Counter(r["sharing"] for r in completed)
    eligible = len(completed) - shares["Pending"]
    late = counts["More than 2 hours late"]
    return {
        "scheduled": len(records),
        "on_time_pct": 100 * counts["On time"] / len(records) if records else None,
        "early": counts["Early"],
        "missed": counts["Missed pickup"],
        "late": late,
        "late_pickup_pct": 100 * late / len(records) if records else None,
        "eligible": eligible,
        "pending": shares["Pending"],
        "sharing_pct": {s: 100 * shares[s] / eligible if eligible else None for s in SHARING[:3]},
    }


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Waste operator performance")
        self.geometry("1180x760")
        self.records = {}
        self.dirty = False
        self.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Waste operator performance", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Enter one assessed pickup per row. Select an existing row to edit it. Export CSV to save your work.").pack(anchor="w", pady=6)
        form = ttk.Frame(frame)
        form.pack(fill="x")
        self.values = {k: tk.StringVar() for k in FIELDS}
        labels = ("Pickup ID", "Operator", "Pickup date (YYYY-MM-DD)", "Pickup punctuality", "Timely weighbridge sharing")
        self.inputs = {}
        for i, (key, label) in enumerate(zip(FIELDS, labels)):
            ttk.Label(form, text=label).grid(row=0, column=i, sticky="w", padx=4)
            if key in ("punctuality", "sharing"):
                widget = ttk.Combobox(form, textvariable=self.values[key], values=PUNCTUALITY if key == "punctuality" else SHARING, state="readonly", width=24)
            else:
                widget = ttk.Entry(form, textvariable=self.values[key], width=19)
            widget.grid(row=1, column=i, padx=4, pady=6, sticky="ew")
            self.inputs[key] = widget
            form.columnconfigure(i, weight=1)
        self.inputs["punctuality"].bind("<<ComboboxSelected>>", self.status_changed)
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=8)
        for label, callback in (("Save pickup", self.save), ("Clear form", self.clear), ("Delete selected", self.delete), ("Import CSV", self.import_csv), ("Export CSV", self.export_csv)):
            ttk.Button(actions, text=label, command=callback).pack(side="left", padx=3)
        ttk.Label(frame, text="Use your agreed pickup window for ‘On time’. The chosen options do not cover delays of 0–2 hours outside that window.\nMark sharing ‘Pending’ while its deadline is open; use ‘Not sent’ once overdue. Missed pickups have no sharing status.", wraplength=1100).pack(anchor="w", pady=6)
        filter_row = ttk.Frame(frame)
        filter_row.pack(fill="x", pady=8)
        ttk.Label(filter_row, text="Operator summary:").pack(side="left")
        self.operator = tk.StringVar(value="")
        self.filter = ttk.Combobox(filter_row, textvariable=self.operator, state="readonly", width=32)
        self.filter.pack(side="left", padx=8)
        ttk.Label(filter_row, text="Blank = all operators; summary covers all imported dates.").pack(side="left")
        self.filter.bind("<<ComboboxSelected>>", lambda _: self.refresh())
        self.summary = tk.StringVar()
        ttk.Label(frame, textvariable=self.summary, font=("Segoe UI", 11), justify="left").pack(anchor="w", pady=10)
        table = ttk.Frame(frame)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=FIELDS, show="headings", selectmode="browse")
        for key, label in zip(FIELDS, labels):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=175, minwidth=90)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.select)
        self.clear()
        self.refresh()

    def status_changed(self, _=None):
        missed = self.values["punctuality"].get() == "Missed pickup"
        self.inputs["sharing"].configure(state="disabled" if missed else "readonly")
        if missed:
            self.values["sharing"].set("")
        elif not self.values["sharing"].get():
            self.values["sharing"].set("Pending")

    def clear(self):
        for value in self.values.values():
            value.set("")
        self.values["pickup_date"].set(date.today().isoformat())
        self.values["sharing"].set("Pending")
        self.tree.selection_remove(*self.tree.selection())
        self.status_changed()

    def select(self, _=None):
        selection = self.tree.selection()
        if selection:
            for key, value in self.records[selection[0]].items():
                self.values[key].set(value)
            self.status_changed()

    def save(self):
        try:
            row = validate({k: v.get() for k, v in self.values.items()})
        except ValueError as exc:
            messagebox.showerror("Invalid pickup", str(exc))
            return
        if row["pickup_id"] in self.records and not messagebox.askyesno("Update pickup", "Replace the existing record with this pickup ID?"):
            return
        self.records[row["pickup_id"]] = row
        self.dirty = True
        self.refresh()
        self.clear()

    def delete(self):
        selected = self.tree.selection()
        if selected and messagebox.askyesno("Delete pickup", "Delete the selected pickup?"):
            del self.records[selected[0]]
            self.dirty = True
            self.refresh()
            self.clear()

    def refresh(self):
        operators = sorted({r["operator"] for r in self.records.values()})
        self.filter["values"] = [""] + operators
        if self.operator.get() not in operators:
            self.operator.set("")
        rows = [r for r in self.records.values() if not self.operator.get() or r["operator"] == self.operator.get()]
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            self.tree.insert("", "end", iid=row["pickup_id"], values=[row[k] for k in FIELDS])
        s = summarize(rows)
        pct = lambda value: "N/A" if value is None else f"{value:.1f}%"
        self.summary.set(
            f"On-time pickup rate: {pct(s['on_time_pct'])}    |    Sent on time: {pct(s['sharing_pct']['Sent on time'])}\n"
            f"Pickup rate over 2 hours late: {pct(s['late_pickup_pct'])}    |    Sent late: {pct(s['sharing_pct']['Sent late'])}\n"
            f"Missed pickup count: {s['missed']}    |    Not sent: {pct(s['sharing_pct']['Not sent'])}\n"
            f"Number of scheduled pickups: {s['scheduled']}    |    Pending ticket count: {s['pending']}\n\n"
            f"Early pickups: {s['early']} (separate from on-time). Pickups over 2 hours late: {s['late']}.\n"
            f"Pickup rate denominator: all {s['scheduled']} scheduled pickups, including missed pickups.\n"
            f"Sharing denominator: {s['eligible']} completed pickups with a resolved sharing status; pending and missed excluded."
        )

    def import_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            imported = {}
            with open(path, newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                if not set(FIELDS).issubset(reader.fieldnames or []):
                    raise ValueError("Required CSV columns: " + ", ".join(FIELDS))
                for line, raw in enumerate(reader, start=2):
                    try:
                        row = validate(raw)
                        if row["pickup_id"] in imported:
                            raise ValueError("Duplicate pickup ID.")
                        imported[row["pickup_id"]] = row
                    except ValueError as exc:
                        raise ValueError(f"Row {line}: {exc}") from exc
            if self.records and not messagebox.askyesno("Replace records", "Replace all current records with the imported CSV? Export first if you need to keep them."):
                return
            self.records = imported
            self.dirty = False
            self.refresh()
            self.clear()
        except (OSError, ValueError, csv.Error) as exc:
            messagebox.showerror("Import failed", str(exc))

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="operator_pickups.csv", filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(self.records.values())
            self.dirty = False
            messagebox.showinfo("Export complete", f"Saved {len(self.records)} pickups.")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    def close(self):
        if not self.dirty or messagebox.askyesno("Unsaved records", "Close without exporting your changes?"):
            self.destroy()


if __name__ == "__main__":
    App().mainloop()
