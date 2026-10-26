"""The `keep` command line."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

from . import auth, client, config, importer

HELP_EPILOGUE = """\
examples:
  keep login --account you@gmail.com   sign in (walks you through it)
  keep status                          is it working?
  keep labels                          every label and how many notes
  keep list --label ideas              notes carrying a label
  keep search "garden"                 full text search
  keep get <id>                        one note in full
  keep new --title t --text "..."      create a note
  keep new --list --title Shopping --item milk --item eggs
  keep edit <id> --append "one more line"
  keep check <id> milk                 tick a checklist item
  keep pin <id>  |  keep archive <id>  |  keep trash <id>
  keep share <id> --add a@b.com        collaborators
  keep import ./my-notes               a folder of files -> labelled notes
  keep export ./out --label ideas      notes -> files on disk

every read command takes --json for machine-readable output.
"""


# --- output helpers ------------------------------------------------------

def line(note) -> str:
    flags = "".join([
        "P" if note.pinned else "",
        "A" if note.archived else "",
        "L" if note.type.name == "List" else "",
    ])
    labels = ",".join(client.label_names(note)) or "-"
    return f"{note.id}  [{labels}]  {note.color.name:<8} {flags:<3} {note.title or '(untitled)'}"


def full(note) -> str:
    out = [line(note), "-" * 68]
    if note.type.name == "List":
        for item in note.items:
            box = "[x]" if item.checked else "[ ]"
            out.append(f"  {'  ' * (1 if item.indented else 0)}{box} {item.text}")
    else:
        out.append(note.text)
    extras = []
    if note.images:   extras.append(f"{len(note.images)} image(s)")
    if note.drawings: extras.append(f"{len(note.drawings)} drawing(s)")
    if note.audio:    extras.append(f"{len(note.audio)} audio clip(s)")
    people = [c for c in note.collaborators.all()]
    if people: extras.append("shared with " + ", ".join(people))
    if extras:
        out += ["-" * 68, "  " + " · ".join(extras)]
    return "\n".join(out)


def as_dict(note, text: bool = False) -> dict:
    d = {
        "id": note.id, "title": note.title, "type": note.type.name,
        "labels": client.label_names(note), "color": note.color.name,
        "pinned": note.pinned, "archived": note.archived,
        "collaborators": list(note.collaborators.all()),
        "attachments": len(note.images) + len(note.drawings) + len(note.audio),
    }
    if text:
        if note.type.name == "List":
            d["items"] = [{"text": i.text, "checked": i.checked} for i in note.items]
        else:
            d["text"] = note.text
    return d


def find_note(keep, note_id: str):
    note = keep.get(note_id)
    if note is None:
        raise SystemExit(f"No note with id {note_id!r}. Find ids with:  keep list")
    return note


def body_from(args) -> str | None:
    if getattr(args, "file", None):
        if args.file == "-":
            return sys.stdin.read().strip()
        return pathlib.Path(args.file).read_text(encoding="utf-8").strip()
    return getattr(args, "text", None)


# --- parser --------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="keep", description="A command line for Google Keep.",
        epilog=HELP_EPILOGUE, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--account", help="Google account (default: the configured one)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--resync", action="store_true", help="ignore the local cache")
    s = p.add_subparsers(dest="cmd", required=True)

    q = s.add_parser("login", help="sign in to Keep")
    q.add_argument("--store", choices=auth.BACKENDS, help="where to keep the token")
    q.add_argument("--show-token", action="store_true",
                   help="print the master token so you can use it elsewhere")
    s.add_parser("logout", help="forget the stored token")
    s.add_parser("status", help="check the connection")
    q = s.add_parser("device-id", help="set the device id a token is bound to")
    q.add_argument("value")

    s.add_parser("labels", help="list labels with counts")
    q = s.add_parser("list", help="list notes")
    q.add_argument("--label"); q.add_argument("--limit", type=int, default=50)
    q.add_argument("--archived", action="store_true"); q.add_argument("--pinned", action="store_true")
    q = s.add_parser("search", help="search titles and text")
    q.add_argument("query"); q.add_argument("--label"); q.add_argument("--limit", type=int, default=50)
    q = s.add_parser("get", help="show one note in full"); q.add_argument("id")

    q = s.add_parser("new", help="create a note or checklist")
    q.add_argument("--title", default=""); q.add_argument("--text", default="")
    q.add_argument("--file"); q.add_argument("--label", action="append", default=[])
    q.add_argument("--color", type=int); q.add_argument("--pin", action="store_true")
    q.add_argument("--list", action="store_true", help="make it a checklist")
    q.add_argument("--item", action="append", default=[], help="checklist item (repeatable)")

    q = s.add_parser("edit", help="change a note")
    q.add_argument("id"); q.add_argument("--title"); q.add_argument("--text")
    q.add_argument("--file"); q.add_argument("--append")

    q = s.add_parser("additem", help="add an item to a checklist")
    q.add_argument("id"); q.add_argument("text"); q.add_argument("--checked", action="store_true")
    q = s.add_parser("check", help="tick checklist items matching text")
    q.add_argument("id"); q.add_argument("match")
    q = s.add_parser("uncheck", help="untick checklist items matching text")
    q.add_argument("id"); q.add_argument("match")

    for name, helptext in [("pin", "pin a note"), ("unpin", "unpin a note"),
                           ("archive", "archive a note"), ("unarchive", "unarchive a note"),
                           ("trash", "move to the bin"), ("untrash", "restore from the bin"),
                           ("delete", "delete permanently (no bin)")]:
        q = s.add_parser(name, help=helptext); q.add_argument("id")

    q = s.add_parser("color", help="set a note's colour (1-11)")
    q.add_argument("id"); q.add_argument("n", type=int)
    q = s.add_parser("label", help="add or remove a label")
    q.add_argument("id"); q.add_argument("action", choices=["add", "rm"]); q.add_argument("name")
    q = s.add_parser("share", help="manage collaborators")
    q.add_argument("id"); q.add_argument("--add", action="append", default=[])
    q.add_argument("--rm", action="append", default=[])
    q = s.add_parser("media", help="list or download a note's attachments")
    q.add_argument("id"); q.add_argument("--download", metavar="DIR")

    q = s.add_parser("import", help="turn a folder of files into notes")
    importer.add_import_args(q)
    q = s.add_parser("export", help="write notes out as files")
    q.add_argument("dest"); q.add_argument("--label"); q.add_argument("--format",
                   choices=["md", "json"], default="md")
    q = s.add_parser("reorder", help="make the grid order match title order")
    q.add_argument("--label"); q.add_argument("--reverse", action="store_true")
    q = s.add_parser("recolor", help="set every note in a label to one colour")
    q.add_argument("label"); q.add_argument("n", type=int)
    return p


# --- commands ------------------------------------------------------------

def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    out = None

    if args.cmd == "login":
        email = args.account or config.account()
        if not email:
            email = input("Google account (you@gmail.com): ").strip()
        return auth.login(email, backend=args.store, show_token=args.show_token)

    if args.cmd == "logout":
        email = client.resolve_account(args.account)
        gone = auth.delete_token(email)
        cache = config.cache_file(email)
        if cache.exists():
            cache.unlink()
        print(f"removed token from: {', '.join(gone)}" if gone else "nothing stored to remove")
        if os.environ.get("KEEP_MASTER_TOKEN"):
            print("note: KEEP_MASTER_TOKEN is still set in your environment, so you\n"
                  "      are still signed in. Unset it to finish logging out.")
        return

    if args.cmd == "device-id":
        email = client.resolve_account(args.account)
        config.set_device_id(email, args.value)
        print(f"device id for {email} set")
        return

    if args.cmd == "status":
        email = client.resolve_account(args.account)
        print(f"account      : {email}")
        print(f"token source : {auth.token_source(email)}")
        if not auth.get_token(email):
            print("\nNot signed in. Run:  keep login")
            return
        keep = client.connect(email, fresh=True)
        notes = client.live_notes(keep)
        print("connection   : OK")
        print(f"notes        : {len(notes)}")
        print(f"labels       : {len(list(keep.labels()))}")
        client.save_cache(keep, email)
        return

    keep = client.connect(args.account, fresh=args.resync)
    dirty = False

    if args.cmd == "labels":
        counts: dict[str, int] = {}
        for n in client.live_notes(keep):
            for l in client.label_names(n):
                counts[l] = counts.get(l, 0) + 1
        out = [{"label": k, "notes": v} for k, v in sorted(counts.items())]
        if not args.json:
            for r in out:
                print(f"  {r['label']:<16} {r['notes']:>5}")
            print(f"\n{len(out)} labels")

    elif args.cmd in ("list", "search"):
        notes = (client.by_label(keep, args.label) if args.label
                 else client.live_notes(keep))
        if args.cmd == "search":
            q = args.query.lower()
            notes = [n for n in notes if q in (n.title or "").lower() or q in n.text.lower()]
        if getattr(args, "archived", False):
            notes = [n for n in notes if n.archived]
        if getattr(args, "pinned", False):
            notes = [n for n in notes if n.pinned]
        notes = client.display_order(notes)[:args.limit]
        out = [as_dict(n) for n in notes]
        if not args.json:
            for n in notes:
                print(line(n))
            print(f"\n{len(notes)} shown")

    elif args.cmd == "get":
        n = find_note(keep, args.id)
        out = as_dict(n, text=True)
        if not args.json:
            print(full(n))

    elif args.cmd == "new":
        if args.list or args.item:
            n = keep.createList(args.title, [(i, False) for i in args.item])
        else:
            n = keep.createNote(args.title, body_from(args) or "")
        for name in args.label:
            n.labels.add(client.get_or_make_label(keep, name))
        if args.color:
            n.color = client.PALETTE[args.color]
        if args.pin:
            n.pinned = True
        n.sort = client.next_sort(keep)
        dirty = True
        out = {"id": n.id, "title": n.title}
        if not args.json:
            print(f"created {n.id}")

    elif args.cmd == "edit":
        n = find_note(keep, args.id)
        if args.title is not None:
            n.title = args.title
        if args.append:
            n.text = (n.text.rstrip() + "\n" + args.append).strip()
        else:
            body = body_from(args)
            if body is not None:
                n.text = body
        dirty = True
        out = {"id": n.id, "chars": len(n.text)}
        if not args.json:
            print(f"updated {n.id}")

    elif args.cmd in ("additem", "check", "uncheck"):
        n = find_note(keep, args.id)
        if n.type.name != "List":
            raise SystemExit(f"{args.id} is a note, not a checklist")
        if args.cmd == "additem":
            n.add(args.text, args.checked)
            hit = 1
        else:
            want = args.cmd == "check"
            hit = 0
            for item in n.items:
                if args.match.lower() in item.text.lower():
                    item.checked = want
                    hit += 1
            if not hit:
                raise SystemExit(f"no checklist item matching {args.match!r}")
        dirty = True
        out = {"id": n.id, "affected": hit}
        if not args.json:
            print(f"{args.cmd}: {hit} item(s)")

    elif args.cmd in ("pin", "unpin", "archive", "unarchive",
                      "trash", "untrash", "delete"):
        n = find_note(keep, args.id)
        {"pin":       lambda: setattr(n, "pinned", True),
         "unpin":     lambda: setattr(n, "pinned", False),
         "archive":   lambda: setattr(n, "archived", True),
         "unarchive": lambda: setattr(n, "archived", False),
         "trash":     n.trash, "untrash": n.untrash, "delete": n.delete}[args.cmd]()
        dirty = True
        out = {"id": n.id, "action": args.cmd}
        if not args.json:
            print(f"{args.cmd}: {n.id}")

    elif args.cmd == "color":
        if args.n not in client.PALETTE:
            raise SystemExit("colour must be 1-11:  " +
                             ", ".join(f"{k}={v}" for k, v in client.COLOR_NAMES.items()))
        n = find_note(keep, args.id)
        n.color = client.PALETTE[args.n]
        dirty = True
        out = {"id": n.id, "color": n.color.name}
        if not args.json:
            print(f"{n.id} -> {n.color.name}")

    elif args.cmd == "label":
        n = find_note(keep, args.id)
        lbl = client.get_or_make_label(keep, args.name)
        n.labels.add(lbl) if args.action == "add" else n.labels.remove(lbl)
        dirty = True
        out = {"id": n.id, "labels": client.label_names(n)}
        if not args.json:
            print(f"{n.id} labels: {', '.join(client.label_names(n)) or '-'}")

    elif args.cmd == "share":
        n = find_note(keep, args.id)
        for who in args.add:
            n.collaborators.add(who)
        for who in args.rm:
            n.collaborators.remove(who)
        dirty = True
        out = {"id": n.id, "collaborators": list(n.collaborators.all())}
        if not args.json:
            print("shared with: " + (", ".join(n.collaborators.all()) or "nobody"))

    elif args.cmd == "media":
        n = find_note(keep, args.id)
        blobs = list(n.images) + list(n.drawings) + list(n.audio)
        out = []
        for i, b in enumerate(blobs):
            url = keep.getMediaLink(b)
            out.append({"index": i, "kind": b.blob.type.name if b.blob else "?", "url": url})
        if args.download:
            import urllib.request
            d = pathlib.Path(args.download)
            d.mkdir(parents=True, exist_ok=True)
            for row in out:
                target = d / f"{n.id}-{row['index']}"
                urllib.request.urlretrieve(row["url"], target)
                row["saved"] = str(target)
        if not args.json:
            for row in out:
                print(f"  {row['index']}  {row['kind']}  {row.get('saved', row['url'][:70])}")
            print(f"\n{len(out)} attachment(s)")

    elif args.cmd == "import":
        out = importer.run_import(keep, args)
        dirty = False  # run_import syncs as it goes

    elif args.cmd == "export":
        out = importer.run_export(keep, args)

    elif args.cmd == "reorder":
        out = importer.run_reorder(keep, args)
        dirty = True

    elif args.cmd == "recolor":
        if args.n not in client.PALETTE:
            raise SystemExit("colour must be 1-11")
        notes = client.by_label(keep, args.label)
        for n in notes:
            n.color = client.PALETTE[args.n]
        dirty = True
        out = {"label": args.label, "notes": len(notes), "color": client.COLOR_NAMES[args.n]}
        if not args.json:
            print(f"{len(notes)} notes in {args.label} -> {client.COLOR_NAMES[args.n]}")

    if dirty:
        keep.sync()
    client.save_cache(keep, args.account)
    if args.json and out is not None:
        print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
