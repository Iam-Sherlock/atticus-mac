# Jarvis

A voice-first Mac assistant, being built into a personal AI in the spirit of Jarvis from the Iron Man films. Hold Control+Option+Space (or, soon, say "Hey Jarvis"), speak, and it moves windows, reads the screen, draws explanations, dictates, runs background agents and remembers you.

**Read `docs/PLAN.md` before any roadmap work.** It holds the phases, the decisions already made with the owner, and what is done.

## Layout

| Path | What it is |
|---|---|
| `Jarvis.swift` | The whole native app in one file: hotkey, on-device speech, overlay box, drawing overlay, Settings and setup windows, Meeting Copilot, the `--hands` accessibility helper. |
| `jarvis.py` | The brain in one file: instant commands (no AI), system prompt, AI client driver (Claude Code, Devin, Pi, local), helper CLI the model calls (`--look`, `--draw`, `--place`, `--web`, …), memory, routines, learned commands. |
| `ui/*.html`, `ui/*.js` | Pages shown in `WKWebView`: `ui.html` (ask box), `settings.html`, `onboarding.html`, `agents.html`, `meeting.html`. |
| `build.sh` | Compiles, assembles `~/Applications/Jarvis.app`, signs, installs the launch agent, restarts the app. Also carries an install over from the app's earlier name. |
| `tests/` | `test_*.py` (unittest) and `*.html` browser harnesses for the pages. |
| `docs/PLAN.md` | Roadmap and decisions. |

How the two halves talk: the app runs `jarvis.py` and reads its stdout line by line. Each line starts with a tag: `· note`, `▸ step`, `✓ answer`, `! failure`, `i tip`, `✎ {json}` (a drawing or receipt), and a few more. The model calls back into `jarvis.py` helper flags, and `jarvis.py` calls the app binary for native work (`Jarvis --hands …`, `--draw-target`). Settings are one JSON file both sides read: `~/.config/jarvis/settings.json`.

## Build and run

Needs macOS 26, Apple's command line tools and Python 3.

```bash
./build.sh
```

That rebuilds and restarts the app. After a rename or new bundle ID macOS asks for permissions again.

## Test

```bash
python3 -m unittest discover -s tests
```

- On Linux about 160 tests skip (anything needing Cocoa or `swiftc`). On a Mac they compile small Swift fixtures and run.
- Tests that would drive real windows only run with `JARVIS_VM=1` or `JARVIS_ALLOW_HOST_UI=1`; otherwise they skip so they never take over your screen.
- Tests always use a scratch `JARVIS_DIR`, never the real settings folder.
- Page harnesses: serve the repo root (`python3 -m http.server`) and open `tests/ui.html`, `tests/settings.html`, `tests/onboarding.html`, `tests/agents.html`, `tests/meeting.html`. Each prints its checks and turns green or red. They pass in Chromium as well as WebKit.
- After building: `python3 jarvis.py --selftest`, and `~/Applications/Jarvis.app/Contents/MacOS/Jarvis --selftest`.

## Things that will bite you

- **Tests slice the source by exact strings.** Many tests do `source[source.index('…'):source.index('…')]` on `Jarvis.swift` and the pages. Rewording, reflowing or deleting a line can break a test far away. Run the full suite after any edit and update the markers deliberately.
- **Test order matters.** Files run alphabetically and share module state in `jarvis`. A test that sets a global (for example `STOPPING`) must reset it.
- **System prompt budget.** Under 10,000 characters in source, enforced by tests. Every ask pays for it. New model-facing instructions go behind a `--help` flag the model reads on demand (see `DRAW_HELP`), not into the base prompt.
- **Cost and speed budget.** Instant commands use no AI. AI asks stay under a median of $0.002 and 6 s (`python3 jarvis.py --budget`). Anything that waits in the background costs $0 while waiting.
- **Safety rules are product behaviour.** Deletes, sends, purchases and file changes ask first; `rm`, `sudo`, disk tools and shutdown are blocked; the app never takes focus. Do not weaken these for convenience.
- **Swift cannot be verified off a Mac.** If you are not on macOS, say so, keep Swift edits small, and have the owner run `./build.sh`.

## Conventions

- Two big single files by design. Do not split them into modules or add package dependencies; the app ships with only Python's standard library and system frameworks.
- Dense style, long lines, and a trailing comment that says *why* (`# never on the very first ask`). Match it.
- User-facing text is short and plain. No jargon in the box, Settings or setup.
- Commit messages describe what changed for the person using the app, in plain words.
- Nothing personal in commits: settings, memory, logs, keys (`.gitignore` covers the usual files).
- `CLAUDE.md` is tracked; keep machine-specific notes in `CLAUDE.local.md`, which is ignored.

## Name and origin

- The product is **Jarvis**. The old name must not come back in code, UI or docs.
- In the code it still appears in exactly two places, on purpose (these notes and `docs/PLAN.md` also name it where they must): the carry-over block in `build.sh` (it has to find the old install), and the GitHub repo name `Iam-Sherlock/atticus-mac` inside links, until the owner renames the repo.
- This is a fork of an MIT-licensed project. `LICENSE` and `LICENSE-Plip` keep the original copyright lines and must stay.
- No ties to the original author's services: no tip jar, no store, and no usage data (the reporting code is inert unless `JARVIS_POSTHOG_KEY` is set).
- "J.A.R.V.I.S." is a Marvel name. No film imagery or audio, and no cloning of the film actor's voice.

## Git

- Work branch: `claude/stoic-albattani-f88byp`. The default branch still holds the pre-rebrand code until that branch is merged, and the README's one-line installer pulls the default branch.
- No pull request unless the owner asks.
