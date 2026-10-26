# keep-cli

A command line for Google Keep. Read your notes, write new ones, run checklists,
move whole folders in and out, and script any of it.

Google doesn't publish an API for ordinary Keep accounts — the official one is
for Workspace administrators only. This tool uses [`gkeepapi`](https://github.com/kiwiz/gkeepapi),
which talks to the same internal endpoints the Android app uses. That works well,
but it's worth knowing up front: it's unofficial, Google could change it without
warning, and signing in is more awkward than it should be.

---

## Quick start

```bash
git clone <this repo> keep-cli && cd keep-cli

python3 -m venv .venv                 # Python 3.10 or newer
.venv/bin/pip install -e ".[keyring]"

./keep login --account you@gmail.com  # walks you through it
./keep status
./keep labels
```

`./keep` runs from a checkout without installing anything globally.

To get `keep` on your PATH, either `pip install .` (which installs a `keep`
entry point), or symlink the wrapper:

```bash
ln -s "$PWD/keep" ~/bin/keep      # or anywhere on your PATH
```

The wrapper resolves symlinks, so it still finds the repo's `.venv` when
invoked through a link from elsewhere.

---

## Signing in

This is the only genuinely annoying part, and it's Google's fault rather than
the tool's. There's no OAuth flow available for consumer Keep, so you have to
fetch a cookie from your browser by hand, once.

Run `./keep login` and it prints these steps as you go:

1. **Open <https://accounts.google.com/EmbeddedSetup> in Chrome.** Use an
   incognito window signed in *only* as the account you want. Several Google
   accounts in one Chrome profile is the most common reason this fails.

2. **Sign in and click "I agree".** The page will then sit on a loading spinner
   forever. **That's normal** — it's waiting to hear from an Android device that
   doesn't exist. Ignore it; the cookie you need has already been set.

3. **Open DevTools → Application → Storage → Cookies → `https://accounts.google.com`**,
   and click the row named **`oauth_token`**. Copy the value from the **Cookie
   Value pane at the bottom** of the panel — not from the table cell, which
   truncates long values without telling you. It starts with `oauth2_4/`.

4. **Paste it at the prompt.** Input is hidden.

Things that will waste your time if you don't know them:

- **The cookie is single use.** If the exchange fails, that value is spent.
  Delete the `oauth_token` cookie, reload the page, and copy a fresh one.
- **It expires in minutes.** Copy it and paste it straight away.
- **A fresh cookie sometimes fails the first time** with `BadAuthentication`
  for no visible reason. Try once more with another fresh cookie before
  concluding something is broken.

What you get back is a **master token**, which doesn't expire on its own.
You only do this once per machine.

---

## Where the token lives

Read this bit. The master token is **full access to the Google account** — not
just Keep. Google offers no narrower credential through this route, so treat it
exactly like a password.

There are three places it can live, and you choose:

| Backend | Where | Good for |
|---|---|---|
| `env` | `KEEP_MASTER_TOKEN` in the environment | agents, containers, CI — nothing on disk |
| `file` | `~/.config/keep-cli/token-<account>`, mode 0600 | any OS, no platform services |
| `keyring` | macOS Keychain / Windows Credential Locker / Linux SecretService | a personal machine |

```bash
./keep login --store file      # portable, no Keychain involved
./keep login --store keyring   # default when the keyring package is installed
```

Reads try the environment first, then the file, then the keyring — so setting
`KEEP_MASTER_TOKEN` always wins and needs no setup at all. `./keep status` tells
you which one is actually in use.

**The token is never stored in this repo.** `keep-cli` refuses to write it
anywhere inside a git working tree, and `.gitignore` blocks the obvious
filenames as a second line of defence. Putting a full-account credential in a
repo you intend to share or push would hand over the whole account.

### Moving a session to another machine, container or agent

```bash
./keep login --show-token       # prints the master token and a device id
```

Then on the other side, with no browser dance at all:

```bash
export KEEP_MASTER_TOKEN='<token>'
export KEEP_ACCOUNT='you@gmail.com'
keep device-id <device id>      # the token is bound to this
keep status
```

This is the right route for handing access to an automated agent: nothing is
written to disk, and you revoke it by signing the device out of your Google
account.

### Logging out

```bash
./keep logout                                    # forget the stored token
```

That removes the local copy. To actually revoke access, sign the device out at
[myaccount.google.com/device-activity](https://myaccount.google.com/device-activity)
— the login registers a synthetic Android device that shows up there.

---

## Using it

Every read command takes `--json` for machine-readable output, which is what
you want when scripting or handing this to an agent. Add `--resync` to ignore
the local cache and re-read everything from the server.

### Reading

```bash
./keep labels                          # every label and how many notes
./keep list                            # recent notes
./keep list --label ideas --limit 20
./keep list --pinned                   # or --archived
./keep search "garden of eden"         # titles and body text
./keep search "bug" --label notes
./keep get <id>                        # one note in full
```

Listings show `id [labels] Colour FLAGS title`, where flags are `P` pinned,
`A` archived, `L` it's a checklist rather than a note.

### Writing

```bash
./keep new --title "Idea" --text "body text"
./keep new --title "From a file" --file notes.md
cat notes.md | ./keep new --title "From stdin" --file -

./keep edit <id> --text "replace the whole body"
./keep edit <id> --append "add one more line"
./keep edit <id> --title "a better title"
```

### Checklists

```bash
./keep new --list --title Shopping --item milk --item eggs
./keep additem <id> "bread"
./keep check <id> milk          # ticks every item matching that text
./keep uncheck <id> milk
```

### Organising

```bash
./keep pin <id>        ./keep unpin <id>
./keep archive <id>    ./keep unarchive <id>
./keep color <id> 4                 # 1-11, see the palette below
./keep label <id> add work
./keep label <id> rm work
./keep recolor ideas 3              # every note in a label at once
```

### Deleting

```bash
./keep trash <id>      # into the bin, recoverable
./keep untrash <id>
./keep delete <id>     # permanent, skips the bin entirely
```

### Sharing

```bash
./keep share <id> --add someone@gmail.com
./keep share <id> --rm someone@gmail.com
./keep share <id>                   # just show who it's shared with
```

### Attachments

```bash
./keep media <id>                   # list images, drawings, audio
./keep media <id> --download ./out  # save them
```

**Downloads work; uploads don't.** `gkeepapi` has no upload path, so you can
read and save attachments that already exist but can't add new ones from here.
Use the Keep app for that.

### The colour palette

Keep's picker, left to right, skipping the default white swatch:

| 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|----|----|
| Red | Orange | Yellow | Green | Teal | Blue | DarkBlue | Purple | Pink | Brown | Gray |

---

## Moving folders in and out

### Importing

```bash
./keep import ./my-notes --dry-run     # always look first
./keep import ./my-notes
```

Each **top-level folder becomes a label**, and each file in it becomes a note.
Files sitting loose in the source folder get `--default-label`, or no label.
By default it reads `.md`, `.txt`, `.markdown`, `.org` and `.rst`; files and
folders starting with `_` or `.` are skipped.

```bash
./keep import ./my-notes \
    --title-prefix \            # titles like "ideas 003 - first line..."
    --color ideas=3 --color views=4 \
    --default-label inbox
```

**It's resumable.** Every created note is recorded, so re-running only imports
what's new — safe to interrupt, and safe to run again after adding files.

**It's slow on purpose**, roughly a note per second. See the gotchas below.

### Exporting

```bash
./keep export ./out                     # markdown, one folder per label
./keep export ./out --label ideas
./keep export ./out --format json       # everything in one file
```

Export is the natural way to hand your notes to something else — an agent, a
search index, a backup. The JSON form keeps labels, colours, pin/archive state
and checklist items.

### Fixing the order

```bash
./keep reorder --label views     # grid order follows the numbers in titles
./keep reorder --label views --reverse
```

You'll want this after an import. Why it's needed is the first gotcha:

---

## Two things about Keep that will confuse you

**Keep's grid order is a random number, not a date.** Notes are displayed by an
internal `sort` field, highest first — and Keep assigns every new note a
*random* value in the billions. So notes created in a careful order still show
up shuffled, and no amount of fixing timestamps helps. `keep reorder` rewrites
those values into a sequence. (Timestamps can't be set at all, incidentally —
the server accepts a client-supplied one and then silently reverts it, so
backdating imported notes is impossible.)

**Keep timestamps a note when a sync arrives, not when you create it.** Sync 25
notes at once and all 25 land within milliseconds of each other, in arbitrary
order. That's why importing syncs once per note and takes about a second each.
It's slower, and it's the only way to get a predictable sequence.

---

## Requirements

- Python 3.10 or newer
- `gkeepapi`, `gpsoauth` (installed automatically)
- `keyring`, optional — only if you want the OS credential store

Works on macOS, Linux and Windows. The keyring backend uses whatever credential
store your OS provides; the `file` and `env` backends involve no platform
services at all.

---

## Project layout

```
keep              # run it from a checkout without installing
keepcli/
  cli.py          # the commands
  auth.py         # login, and the three token backends
  client.py       # connecting, plus Keep's quirks in one place
  config.py       # settings in ~/.config/keep-cli/
  importer.py     # import, export, reorder
```

Settings live in `~/.config/keep-cli/config.json` (account and device id — nothing
secret). A state cache lives in `~/.cache/keep-cli/`; delete it any time, or pass
`--resync`.

## Limitations

- **Unofficial.** Google can break it without notice.
- **No attachment uploads.** Downloads only.
- **No reminders.** `gkeepapi` doesn't expose them.
- **Timestamps are read-only**, set by the server.
- **The credential is account-wide.** There is no Keep-only token available
  through this route.

## Licence

MIT.
