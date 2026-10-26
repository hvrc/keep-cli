"""Moving whole folders in and out of Keep, and fixing the grid order.

Two things about Keep drive the design here, both learned the hard way:

1.  Keep orders its grid by a `sort` field, NOT by date. Every new note gets a
    *random* sort value, so notes created in a deliberate order still show up
    shuffled. `reorder` rewrites those values into a sequence.

2.  Keep stamps a note when a sync *arrives*, not when you create it. Syncing
    in batches therefore gives every note in the batch near-identical
    timestamps, in arbitrary order. Importing syncs once per note so each gets
    its own place in the sequence. It is slower, and it is the only way.

Timestamps cannot be set by a client at all — the server silently reverts
them — so backdating imported notes is impossible. The title and the sort
field are the only ordering you control.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import time

from . import client, config

TEXT_SUFFIXES = {".md", ".txt", ".markdown", ".org", ".rst"}


def add_import_args(p) -> None:
    p.add_argument("source", help="folder to import")
    p.add_argument("--label-from", choices=["folder", "none"], default="folder",
                   help="folder name becomes the label (default) or no labels")
    p.add_argument("--default-label", default=None,
                   help="label for files sitting directly in the source folder")
    p.add_argument("--color", action="append", default=[], metavar="LABEL=N",
                   help="colour a label, e.g. --color ideas=3 (repeatable)")
    p.add_argument("--title-prefix", action="store_true",
                   help="put the label and file number in each title, e.g. 'ideas 003 - ...'")
    p.add_argument("--reverse", action="store_true",
                   help="treat the LAST file as oldest instead of the first")
    p.add_argument("--ext", action="append", default=[],
                   help="file extensions to include (default: .md .txt .markdown .org .rst)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int)


def _state_path(source: pathlib.Path) -> pathlib.Path:
    key = hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:16]
    d = config.CACHE_DIR / "imports"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def collect(source: pathlib.Path, suffixes: set[str], default_label: str | None):
    """(label, path) for every importable file, folders first, each sorted by name."""
    items = []
    for d in sorted(p for p in source.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        for f in sorted(d.glob("*")):
            if f.is_file() and f.suffix.lower() in suffixes and not f.name.startswith("_"):
                items.append((d.name, f))
    for f in sorted(source.glob("*")):
        if f.is_file() and f.suffix.lower() in suffixes and not f.name.startswith("_"):
            items.append((default_label, f))
    return items


def make_title(path: pathlib.Path, label: str | None, prefix: bool) -> str:
    body = path.read_text(encoding="utf-8", errors="replace").strip()
    first = next((l.strip() for l in body.splitlines() if l.strip()), path.stem)
    excerpt = first if len(first) <= 60 else first[:60].rsplit(" ", 1)[0] + "..."
    m = re.match(r"^(\d+)[-_]", path.name)
    if prefix and m and label:
        return f"{label} {m.group(1)} - {excerpt}"
    return excerpt


def run_import(keep, args) -> dict:
    source = pathlib.Path(args.source).expanduser()
    if not source.is_dir():
        raise SystemExit(f"{source} is not a folder")
    suffixes = {e if e.startswith(".") else f".{e}" for e in args.ext} or TEXT_SUFFIXES

    colors = {}
    for spec in args.color:
        if "=" not in spec:
            raise SystemExit(f"--color wants LABEL=N, got {spec!r}")
        name, num = spec.rsplit("=", 1)
        colors[name] = client.PALETTE[int(num)]

    items = collect(source, suffixes, args.default_label)
    if args.reverse:
        items = list(reversed(items))

    statefile = _state_path(source)
    state = json.loads(statefile.read_text()) if statefile.exists() else {}
    todo = [(lab, p) for lab, p in items if str(p.relative_to(source)) not in state]
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(items)} file(s) found · {len(items) - len(todo)} already imported · "
          f"{len(todo)} to create")
    if args.dry_run:
        for lab, p in todo[:15]:
            print(f"  [{lab or '-'}] {make_title(p, lab, args.title_prefix)}")
        if len(todo) > 15:
            print(f"  ... and {len(todo) - 15} more")
        return {"found": len(items), "todo": len(todo), "dry_run": True}
    if not todo:
        return {"found": len(items), "created": 0}

    labels = {}
    if args.label_from == "folder":
        for name in {lab for lab, _ in todo if lab}:
            labels[name] = client.get_or_make_label(keep, name)
        keep.sync()

    base = client.next_sort(keep)
    created = 0
    try:
        for i, (lab, path) in enumerate(todo):
            body = path.read_text(encoding="utf-8", errors="replace").strip()
            note = keep.createNote(make_title(path, lab, args.title_prefix), body)
            if lab and lab in labels:
                note.labels.add(labels[lab])
            if lab in colors:
                note.color = colors[lab]
            note.sort = base + i * 1000
            keep.sync()                      # one sync per note - see module docstring
            state[str(path.relative_to(source))] = note.id
            created += 1
            if created % 25 == 0:
                statefile.write_text(json.dumps(state, indent=1))
                print(f"  {created}/{len(todo)}")
                time.sleep(0.5)
    finally:
        keep.sync()
        statefile.write_text(json.dumps(state, indent=1))

    print(f"created {created} note(s)")
    return {"found": len(items), "created": created, "state": str(statefile)}


def run_export(keep, args) -> dict:
    dest = pathlib.Path(args.dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    notes = client.by_label(keep, args.label) if args.label else client.live_notes(keep)
    notes = client.display_order(notes)

    if args.format == "json":
        rows = []
        for n in notes:
            row = {"id": n.id, "title": n.title, "labels": client.label_names(n),
                   "color": n.color.name, "pinned": n.pinned, "archived": n.archived}
            if n.type.name == "List":
                row["items"] = [{"text": i.text, "checked": i.checked} for i in n.items]
            else:
                row["text"] = n.text
            rows.append(row)
        target = dest / "notes.json"
        target.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
        print(f"wrote {len(rows)} note(s) to {target}")
        return {"written": len(rows), "path": str(target)}

    used: dict[str, int] = {}
    for i, n in enumerate(notes, 1):
        stem = re.sub(r"[^a-z0-9]+", "-", (n.title or "untitled").lower()).strip("-")[:50] or "untitled"
        if stem in used:
            used[stem] += 1
            stem = f"{stem}-{used[stem]}"
        else:
            used[stem] = 1
        if n.type.name == "List":
            body = "\n".join(f"- [{'x' if it.checked else ' '}] {it.text}" for it in n.items)
        else:
            body = n.text
        folder = dest / (client.label_names(n)[0] if client.label_names(n) else "unlabelled")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{i:04d}-{stem}.md").write_text(
            (f"# {n.title}\n\n" if n.title else "") + body + "\n", encoding="utf-8")
    print(f"wrote {len(notes)} note(s) under {dest}")
    return {"written": len(notes), "path": str(dest)}


def run_reorder(keep, args) -> dict:
    """Rewrite `sort` so the grid reads in title order (highest sort shows first)."""
    notes = client.by_label(keep, args.label) if args.label else client.live_notes(keep)

    def key(n):
        m = re.search(r"(\d+)", n.title or "")
        return (0, int(m.group(1))) if m else (1, (n.title or "").lower())

    notes = sorted(notes, key=key, reverse=args.reverse)
    base = 1_000_000
    for i, n in enumerate(notes):
        n.sort = base + i * 1000
    print(f"reordered {len(notes)} note(s)"
          f"{' in ' + args.label if args.label else ''}"
          f" — lowest-numbered at the bottom of the grid"
          f"{' (reversed)' if args.reverse else ''}")
    return {"reordered": len(notes)}
