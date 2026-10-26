# Handing keep-cli to an agent or another session

Notes for giving an automated assistant — a Claude Code session in another
workspace, a script, a container — access to a Keep account.

## Set it up without a browser

The browser login only has to happen once, on a machine with Chrome. After
that the credential is portable.

On the machine that's already signed in:

```bash
./keep login --show-token
```

That prints the master token and the device id it's bound to. On the other
side:

```bash
export KEEP_MASTER_TOKEN='<token>'
export KEEP_ACCOUNT='you@gmail.com'

git clone <repo> keep-cli && cd keep-cli
python3 -m venv .venv && .venv/bin/pip install -e .
./keep device-id <device id>
./keep status
```

No keyring, no Keychain, nothing written to disk. The agent reads the token
from its environment.

**The device id matters.** The master token is bound to the device id used
during the exchange, and authentication fails without the matching one.

## What the agent should know

**Use `--json` for everything you read.** Output is stable and parseable:

```bash
./keep --json list --label ideas --limit 50
./keep --json get <id>
./keep --json search "deadline"
```

**Ids look like `1a17601774a.998893c34eb09d3a`.** They're stable. Get them from
`list` or `search`; most commands take one.

**Prefer `export` over looping `get`** when reading a lot. One command, one
sync, everything on disk:

```bash
./keep export ./notes --format json
```

Reading 500 notes one `get` at a time means 500 syncs. `export` does it once.

**The cache makes repeat calls fast.** State is cached in `~/.cache/keep-cli/`.
Pass `--resync` when you need to be certain you're seeing current server state —
for example after something else may have written.

## Behaviour worth planning around

**Grid order is a random `sort` value, not a date.** Don't infer chronology
from the order notes come back in. Sort by title, or call `keep reorder` to
impose a sequence. Timestamps can't be written — the server reverts them.

**One sync per write.** Each mutating command syncs before exiting, so a loop
of 100 edits is 100 round trips. For bulk work, prefer `import`, `recolor` or
`reorder`, which batch internally.

**`delete` is permanent.** It skips the bin; there's no undo. Use `trash` unless
you mean it. `untrash` recovers from the bin.

**Uploads aren't supported.** `media --download` works, adding attachments
doesn't.

## Safety

The master token is **full access to the Google account**, not just Keep —
Gmail, Drive, everything. Consequences:

- Don't write it into files the agent might commit. `keep-cli` refuses to write
  it inside a git work tree, but an agent constructing its own config can
  bypass that. Environment variables are the right channel.
- Don't print it in logs or transcripts. `--show-token` is deliberately opt-in.
- An agent with this token can read every note. If that's not intended, make a
  separate Google account and share specific notes to it with
  `keep share <id> --add`.

To revoke: `./keep logout` locally, then sign the device out at
[myaccount.google.com/device-activity](https://myaccount.google.com/device-activity).
The login appears there as a generic Android device.

## A minimal read-only recipe

```bash
export KEEP_MASTER_TOKEN='...' KEEP_ACCOUNT='you@gmail.com'
./keep device-id <id>
./keep --json labels                       # what's here
./keep export /tmp/notes --format json     # pull it all down once
# work from /tmp/notes/notes.json
```
