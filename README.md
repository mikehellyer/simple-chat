# Simple-Chat

Pass messages between your own computers on the same network — no
accounts, no internet, no server. Run Simple-Chat on each machine and
they find each other by themselves.

- **Machines on the left**, online ones first with a green dot; unread
  counts in blue.
- **Delivery ticks**: ⏳ waiting / ✓ delivered. A message to a machine
  that's switched off waits and is delivered when it's next on.
- **Links are clickable**, and every message has a *copy* link — handy
  for passing URLs, codes and snippets between machines.
- **Lives in the tray** when you close the window, so messages keep
  arriving, with a desktop notification for each.
- **Scan the network** (button under the list, or File menu) knocks on
  every address on your network for machines running Simple-Chat — for
  networks where routers or Wi-Fi settings block the automatic broadcasts.
  Machines it finds are remembered and kept in touch with directly.
- Machines on another subnet or VPN: *File → Add a machine by address*.

Builds for Linux (.deb, PC and Raspberry Pi), macOS (.dmg) and Windows
(installer). The app checks GitHub for new versions and offers an
Update button — it never updates by itself.

## How it works

- **Finding machines**: each copy broadcasts a small UDP "I'm here"
  packet on port 47474 every 5 seconds.
- **Messages**: sent over TCP (port 47475, or any free port), one JSON
  line each; the receiver acks every message, so nothing is marked
  delivered until it's really there.
- Chats are kept in SQLite in the app's data folder.

Everything stays on your network. There's no encryption or password:
anyone on the same network running Simple-Chat can message you, so
it's meant for a home network.

## Development

```bash
python3 -m venv venv
venv/bin/pip install -r requirements-dev.txt -e .
venv/bin/python -m simple_chat.app
QT_QPA_PLATFORM=offscreen venv/bin/pytest
```

Try two "machines" on one computer with a second profile, which has
its own identity and chats:

```bash
venv/bin/python -m simple_chat.app --profile test
```
