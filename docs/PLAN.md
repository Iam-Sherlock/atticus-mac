# Jarvis plan

The goal: a personal AI assistant for the Mac that feels like Jarvis from the Iron Man films. You talk to it, it talks back, it shows you things, it acts for you, and it takes initiative.

Inspiration: [HeyClicky](https://www.heyclicky.com), a buddy that lives beside your cursor, sees your screen, talks, points and draws. This app already does most of that. What it lacks is the Jarvis feel: a wake word, natural conversation, a personality, initiative, and screens beyond the Mac.

## Status

| Phase | What | Status |
|---|---|---|
| 0 | Rebrand to Jarvis | Done in code. **Swift not yet compiled**: first job on a Mac is `./build.sh` and fixing any errors. |
| 1 | Voice and persona | Next |
| 2 | Conversation | Planned |
| 3 | Cursor buddy | Planned |
| 4 | Canvas explanations | Planned |
| 5 | Cast to the TV | Planned |
| 6 | Initiative | Planned |
| 7 | Diagnostics | Planned |
| 8 | Reach (home, phone) | Planned |

Work one phase at a time. Each phase is one push; the owner builds on their Mac and reports before the next starts.

## Decisions already made with the owner

- **Name:** Jarvis, everywhere. Renamed in place, not in a separate folder.
- **Activation:** "Hey Jarvis" wake word **and** the existing shortcut.
- **Canvas:** a new dedicated canvas window (not Obsidian, not the on-screen overlay). Also save an Obsidian-compatible `.canvas` file.
- **TV:** the owner has a **Chromecast / Google TV**, not AirPlay.
- **What goes on the TV:** whatever is asked. "Cast the canvas" shows only the canvas; "cast my screen" shows the whole screen.
- **Voice:** a British system voice. No cloning of the film actor's voice.
- **Tokens:** drawing must be cheap. The model sends structure, the app does layout.

## What already exists (build on it, do not rebuild)

- Screen reading, pointing (ring and pointer), and **Draw on screen**: a whiteboard overlay with steps, captions and spoken steps (`drawing()` / `draw()` in `jarvis.py`, `ScreenDrawing` in `Jarvis.swift`).
- Read-aloud through `/usr/bin/say` (`readAloudArguments`), on when the `speak` setting is on.
- On-device speech recognition (`SpeechAnalyzer` / `SpeechTranscriber`), hold-to-talk and toggle modes.
- Dictation, background agents, Meeting Copilot, memory rules, a personal profile, routines (launchd), watches, calendar, Spotify, window placement across displays.
- Thinking-orb animation (`ui/orbs.js`).

## Phase 0: Rebrand (done)

- All names, identifiers, files and paths are Jarvis (`com.jarvis.app`, `~/.config/jarvis`, `JARVIS_*`).
- Tip jar, store/licence check and the default analytics key are removed. Settings and setup no longer offer data sharing.
- `build.sh` carries an older install over once (settings, memory, learned commands, routines) and stops the old app.
- New banner. The demo GIF and README video were deleted because they showed the old name.

Left for the owner:
- Rename the GitHub repo (ten links still contain the old repo name; GitHub redirects after a rename).
- Enable Issues on the repo so the feedback button has somewhere to go.
- Record a new demo GIF or video.
- Delete `~/Applications/Atticus.app` and `~/.config/atticus` once Jarvis works.
- Merge the work branch into the default branch so the one-line installer installs Jarvis.

## Phase 1: Voice and persona

- **Wake word.** A setting, off until switched on. Continuous on-device recognition; hearing "hey jarvis" opens the box exactly as the shortcut does, the rest of the sentence is the ask, and a pause sends it (reuse toggle mode's pause handling).
- It must pause itself while dictating, during Meeting Copilot, while Jarvis is speaking (so it does not hear itself), and when the lid is closed.
- **Spoken by default.** Replies are read aloud unless turned off; short spoken form, full text in the box.
- **Voice.** Prefer a British voice (a Siri British voice if installed, else "Daniel"); keep the existing "never a novelty voice" rule.
- **Persona.** Calm, dry, brief; addresses the owner as "sir" or by name (a setting). This costs prompt characters: stay inside the 10,000 budget.
- Costs to tell the owner: the orange mic indicator stays on, and some battery use. Audio never leaves the Mac. False triggers and battery need measuring on a real Mac.

## Phase 2: Conversation

- After an answer, keep listening for a few seconds so a follow-up needs no wake word.
- Barge-in: speaking while Jarvis talks stops the voice and takes the new ask.
- Keep the short-term thread so "and the second one?" works.

## Phase 3: Cursor buddy

- A small orb that sits beside the cursor and flies to whatever Jarvis points at, in the HeyClicky manner.
- Build on the existing pointer shape and ring, and the orb animation. It must never take focus and clicks must pass through.

## Phase 4: Canvas explanations

Example ask: "Hey Jarvis, explain how phone calls work. Do they reach a satellite? Explain in canvas."

- **New helper:** `jarvis.py --canvas '<JSON>'`, with `--canvas --help` for the schema (keeps the base prompt small). No screenshot and no coordinates, so it is far cheaper than `--draw`.
- **Spec the model sends** (structure only):
  ```json
  {"title": "How a phone call travels",
   "nodes": [{"id": "a", "text": "Your phone", "icon": "phone"}, {"id": "b", "text": "Cell tower", "icon": "tower"}],
   "edges": [["a", "b", "radio"]],
   "steps": [{"say": "Your phone talks to the nearest tower by radio.", "show": ["a", "b"]}]}
  ```
- **New page** `ui/canvas.html` in its own window: lays the graph out itself (layered layout), small built-in icon set (phone, tower, satellite, server, cloud, person, globe…), pan and zoom, Back / Next / Replay, caption bar.
- **Voice in step:** each step reveals its nodes and edges while the voice speaks its `say`; advance when the `say` process exits, not on a timer.
- **Follow-ups** extend the same canvas: pass the current spec back as context, as `drawing_context()` does for drawings.
- **Saved copy:** write a JSON Canvas (`.canvas`) file so it opens in Obsidian.
- For the example, the honest answer is that ordinary calls go phone → tower → fibre network → tower → phone; satellites are only for satellite phones and emergency SOS.

## Phase 5: Cast to the TV (Chromecast)

A Mac app cannot natively mirror to a Chromecast. The design is: serve the canvas as a page on the local network and tell the TV to load it.

- **Step 1, before building anything else: a two-minute check on the owner's TV.** The approach relies on a published web receiver that loads arbitrary URLs (the one `catt cast_site` uses, "DashCast"). `catt` still ships this (release in September 2026) but it was **not confirmed** against a current Google TV. If it fails, fall back to driving Chrome's own Cast dialog.
- **Discovery:** find `_googlecast._tcp` devices. One TV: just cast. Several: ask once and remember.
- **Sender:** the Cast protocol in plain Python standard library (TLS to port 8009, length-prefixed protobuf frames with JSON payloads). Small enough to hand-encode; unit-testable against a fake receiver.
- **Local server:** only while casting, at a random token URL, read-only. Serves the canvas page, step updates (server-sent events) and each step's narration audio (made with `say -o`).
- **Sound on the TV:** the TV page plays the narration and drives the reveal from it, so picture and voice stay together there; the Mac stays silent.
- **Permissions:** add `NSLocalNetworkUsageDescription` and `NSBonjourServices` to the `Info.plist` in `build.sh`.
- **Instant commands:** "cast this to my TV", "stop casting".
- **Whole screen ("cast my screen"):** the same TV page showing live screen frames (ScreenCaptureKit → JPEG → local server). Expect roughly 10–15 frames a second at 720p and no Mac audio: fine for documents and slides, not for video. Show a clear "casting" indicator with a stop button.
- Known limit: the receiver renders at 1280×720 and Chromecast hardware is slow.

## Phase 6: Initiative

- Morning briefing (calendar, weather, anything waiting).
- "Your meeting starts in five minutes."
- "That download / build / export finished."
- Build on routines, watches and the calendar helper. Background waiting must cost $0.

## Phase 7: Diagnostics

- "Run diagnostics": battery, storage, network, what is using the CPU, answered instantly with no AI.

## Phase 8: Reach

- Smart home (HomeKit through Shortcuts, or Home Assistant).
- Calls and messages through the owner's iPhone. Anything that sends asks first.

## How to verify

- Python and pages: `python3 -m unittest discover -s tests`, plus the browser harnesses in `tests/*.html`.
- Swift, speech, wake word, casting: only on a Mac, and casting only with the real TV. Do not report these as working until the owner has run them.
