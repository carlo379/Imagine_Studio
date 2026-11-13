# Music video guide (speech-led, beat-locked)

Make a one-minute music video where the character **speaks** the lyrics (Grok Imagine Video lip-syncs speech, not
singing) and every cut lands on the song's bars. Modeled on the Claudia workflow: song first, lyric sheet, beat map,
audited storyboard, measured takes, every word on screen, one local render. All routes live under
`/agent/v1/music-video`, are local and free, and **never generate media**. Takes come from the normal production flow
(shot kit, approved plan, human verdicts) and are attached here by reference.

## Hard rules

- Audio Grok generates while *simulating singing* is **never used**. Only a take that was asked to speak a line
  (kind `spoken`) may contribute its soundtrack, and only as speech. Every other shot is visual-only: audio `none`, and
  its prompt must not ask the model to sing, speak, lip-sync or quote words. The audit and the renderer both enforce it.
- Spoken takes are only trimmed at the start (picture and sound together), never retimed, so lip-sync is untouched.
  Visual-only takes are not slowed either, unless you choose to (slowed motion steps visibly).
- A take's first two frames are never shown (the first is the sharper input still and pops), and the first shot
  always starts at 0, so the picture stays locked to the song.
- No grade or grain until the human asks for it: color is made in the pictures.
- The downbeat phase and section names are guesses; confirm them by ear (`phase` in a patch re-derives the bars).

## Runbook for agents: start here

Follow these steps in order. **H** marks a checkpoint where you stop, show the human what is asked, and wait for
their decision in their own words. Silence never approves spending. Every route below is under `music-video/`,
local and free unless it says otherwise. Generation goes through Studio's normal flow (the
[autonomous production guide](AUTONOMOUS_PRODUCTION_GUIDE.md)), with its rules: an approved plan or
`approved: true`, the human's verbatim words, one take at a time, and a review before the next.

**Before you start.** Read `GET roles` at the Agent API root (the director and reviewer models the human chose) and
`GET music-video/schema`. Local
transcription needs the optional engine and a converted Whisper model (`model_folder`). Previz, stills, plates and
code shots need Node and a headless Chromium. Renders take minutes on a real song: with the SDK, pass
`timeout=900` to `client.request` for `render`, `release`, `previz/render` and `cut/sheets`. Download anything a
route writes with `GET projects/{id}/files`, then `GET projects/{id}/files/{file_id}`.

1. **H: Concept.** Agree on the premise, the one recurring device, and who speaks which lines. Then pick the
   delivery mode (table below).
2. **H: Song, by ear.** The human picks the song take by listening. A description or a word match is not a
   hearing. Upload the master and both stems (`POST editing/media` at the API root), then `POST projects`.
3. **Timing.**
   - `POST projects/{id}/analyze`.
   - **H:** the human confirms the downbeat by ear (`PATCH phase` if it is wrong).
   - `POST projects/{id}/transcribe` with `source: vocal`, then poll `GET transcribe-jobs/{id}` until `done`.
   - `POST projects/{id}/align` with the job's `words`.
   - `POST projects/{id}/line-times/refine` (moves lines onto the vocal stem).
   - `GET projects/{id}/lint`.
4. **Board.**
   - `POST projects/{id}/board/draft`.
   - `POST projects/{id}/previz` (`story`), then `POST projects/{id}/previz/render` and give the human the MP4.
   - `GET projects/{id}/look` for the color script.
   - `GET projects/{id}/audit`, and fix pacing, setups and the hook before going on.
5. **H: References.** Character sheet, any other designs, and the set: paint one with `POST projects/{id}/plates`
   (`use_as_set`) or use the human's. The human answers "is this them?" on each.
6. **Keyframes.**
   - `POST projects/{id}/keyframes` with the `references`, then `POST projects/{id}/previz/stills`.
   - **H:** the stills batch and its cost ceiling (`GET projects/{id}/keyframes`).
   - Generate the stills through Image Studio under that approval, and record them as `candidates`
     (`PATCH projects/{id}/keyframes`).
   - For each candidate, run a consistency review: `POST projects/{id}/keyframes/packet`, a new reviewer session,
     then `POST projects/{id}/keyframes/reviews`.
   - `POST projects/{id}/keyframes/sheet`.
   - **H:** the human approves each still; record it with `approve` and their words.
7. **Prompts.**
   - `POST projects/{id}/prompts/draft`, then edit with `PATCH projects/{id}/board` (prompts and purposes).
   - `GET projects/{id}/prompts`; `GET projects/{id}/audit` must be `ok`.
   - Shots that need no generation (graphics, staged inserts) can be made free with `POST projects/{id}/code-shots`.
8. **Scenes and plan.**
   - `POST projects/{id}/scenes` (one Studio scene per shot), then `POST projects/{id}/keyframes/handoff`.
   - Finish each scene's shot kit (action, `complex_action`).
   - **H: Prompts and cost.** The human approves the production plan once.
9. **Takes**, one at a time under the plan.
   - Before attaching, compare candidates with `POST projects/{id}/triage` if you like.
   - Attach each take with `POST projects/{id}/takes` (for a spoken shot, add `heard_words` from a transcript of the
     take).
   - The human's verdict comes before the next take. Retake a spoken shot whose placement is not `ok`.
   - `POST projects/{id}/takes/last-frame` opens a continuing shot on the previous take's last frame.
10. **Cut.**
    - `POST projects/{id}/render-plan`, then `POST projects/{id}/render`.
    - `POST projects/{id}/cut/sheets` (check `flash`), then two fresh-eyes reviews (`POST projects/{id}/cut/reviews`).
    - Fix blocking shots by reshooting with a better prompt or frame, never by patching frames.
11. **H: v1.** "Accept, or what's wrong?" Apply only the notes given (the newest note wins), then re-render.
12. **Release.**
    - `POST projects/{id}/release` (formats, thumbnails, captions).
    - Give the human the files and the publishing checklist. Publishing is theirs to do.

**Stop and ask** on any 409 from these routes that names a missing step (`analysis_required`, `board_required`,
`keyframes_required`, `still_not_approved`, `takes_missing`, `board_not_clean`), on `transcriber_unavailable`, and
on every production-rule 409 from the generation routes (see the
[error-code table](AUTONOMOUS_PRODUCTION_GUIDE.md#error-codes-and-what-to-do)).

## Choose a delivery mode

| `mode` | Song | She speaks | Needs |
| --- | --- | --- | --- |
| `spoken_word` | instrumental only | every line | an instrumental track |
| `spoken_hooks` | full song with its vocal | only key lines (hook, chorus, refrain, drop, bridge sections, or `spoken_lines`) | the full song |
| `muted_spans` | full song; the sung vocal is muted under each spoken line | the lines you choose | `stems.vocal` and `stems.instrumental` |

Lines the song's vocal carries become `sung_cut` shots. Pick the mode per project and per situation: spoken-word is
the cleanest; hooks keep the real vocal; muted spans keep the real vocal everywhere except under her speech.

## What the core steps check

- **`POST projects`** takes `title`, `production_id`, `mode`, `master` (an uploaded song), `lyrics`, and optional
  `stems`, `song_has_vocals`, `spoken_lines` and `price_per_second`.
- **`analyze`** measures tempo, beats, bars, a downbeat guess and sections.
- **`transcribe`** runs as a background job on the local model; poll `GET transcribe-jobs/{id}`.
- **`align`** places each lyric line using the job's words.
- **`line-times/refine`** moves each line's edges onto the vocal stem, because recognisers start words early.
  The board, the mute spans and the on-screen lyrics all follow these times.
- **`lint`** lists digits, symbols and acronyms to spell out as sung, and each line's bar slot.
- **`audit`** must be `ok` before any spend. It checks:
  - cuts on bar lines, a first shot at 0, and 7-14 shots a minute
  - every line covered, with an exact quote in the spoken shots
  - the audio rules and the mode's requirements
  - the board gates and prompt checks (see Craft tools)
  - the cost ceiling: seconds x takes x your calibrated price
- **`takes`** triages every take.
  - Spoken shots return the measured speech, the placement (`in_point_s` to trim, with the first syllable within
    0.1 s of a beat, `beat_error_s`), a pace check and, with `heard_words`, a word check. A take that cannot land
    on a beat or says the wrong words needs a retake or a cover shot.
  - Visual-only shots get their best window.
- **`render-plan`** previews placements, mute spans, sound timing, slowed shots and the lyric gate.
- **`render`** writes the cut with FFmpeg: the song ducked (or its vocal muted) under speech, loudness normalized,
  lyrics burned in word by word with Pillow, and file metadata stripped. Download it through
  `GET projects/{id}/files`.

## Previz: a free 3D stand-in video before any paid take

Once the board exists, build a three.js previz on the real song clock. Every shot gets a camera move; the
`bedside_machine` story stages a stick-figure carer and a glowing machine, and the other story (`generic`) a single
stick figure. Judge pacing, framing variety, the reveal and the lyric timing for free, and fix the board first.

- `POST projects/{id}/previz` (`story`, `width`, `height`, `fps`) builds the default spec from the board and the aligned
  lines; `GET` reads it; `PUT` replaces it after strict validation (actors, shots, camera moves, tracks). A redrafted
  board clears the previz.
- `POST projects/{id}/previz/render` (`start`, `end`) writes an MP4 with the song under it, headlessly (about 40 s
  for a 65 s video at 540x960). It needs Node and a Chromium-family browser: set `IMAGINE_PREVIZ_BROWSER`, or it uses
  Studio's pinned test browser, Playwright's cached headless shell, then Chrome. It uses a throwaway profile, never
  yours.
- Humans: open **`/previz`** in Studio (for example http://127.0.0.1:8765/previz), choose the spec JSON (the agent
  can save it from `GET projects/{id}/previz`) and the song, then scrub or play with the real audio. **Save still**
  saves a clean PNG of the current moment.
- Frames are deterministic: the same time always gives the same picture, so the viewer and the render agree.
- The previz is a stand-in. It never reaches the video model, and the 3D staging render still must not be sent to the
  video model. A clean previz still may be given to the image model as a composition reference, the same way Studio's
  shot-kit staging is used to make a first frame.

## Keyframe plan: cheap stills before any video

Before any video take, plan one still per shot and make the stills with an image model (the OpenAI subscription does
not use the Grok video allowance). The approved stills later become the takes' first frames.

- `POST projects/{id}/keyframes` (`references`, `candidates`, `price_per_image`, optional `story`) drafts the plan from
  the board and the previz. Every shot gets an opening frame (its first visible instant). The spoken reveal also gets a
  closing frame, because it ends in a clear state. Each still has a `moment` (what the frame shows, read from the previz
  at that instant: framing, poses, the machine's eyes and glow), a draft `prompt`, and its time `t`.
- `references` maps `character`, `machine`, `set` and `style` to uploaded asset ids (approved character sheet, machine
  design, room). Drafted prompts name only the references that are attached, and attaching one later updates any
  prompt you have not edited.
- `GET projects/{id}/keyframes` returns the plan, its checks and the batch estimate: stills x candidates = images, and
  a cost ceiling when `price_per_image` is set. The checks require a character reference (and the machine design for
  `bedside_machine`) and an opening frame for every board shot. They also catch board changes. They refuse prompts
  that quote words, contain the lyric line, or ask anyone to sing or speak. A still is a picture, and image models
  paint quoted words as text. `previz_stale` is true when the previz changed after the plan was drafted.
- `PATCH projects/{id}/keyframes` edits `stills` (`name`, `moment`, `prompt`, `t` inside the shot, and the review
  fields below), `references`, `candidates` (per still) or `price_per_image`. A redrafted board clears the plan.
- `POST projects/{id}/previz/stills` (optional `stills: [{name, t}]`) writes clean PNGs, with no PREVIZ label, timecode
  or lyrics, to `music-video/{id}/stills-r{revision}/`. They are taken at the plan's still times (or each shot's
  opening instant when there is no plan) and recorded on the plan as `previz_still`, so each generated still can be
  compared with its planned composition. Humans can press **Save still** in `/previz`.
- Nothing here generates an image. Generating the batch is a spend the human approves.

Changing the mode, lyrics, spoken lines or phase clears the board and its takes; so do `analyze`, `align` and
`line-times/refine`. Redraft the board afterwards.

## Finishing tools

All local and free; none generates media.

**Take triage and best window.** `POST projects/{id}/takes` scans each take at low resolution for pops (a sudden
frame-to-frame change: a morph, a jump), flicker, black frames and frozen stretches, and returns them by time with a
verdict (`clean`, `check`, `flawed`). For visual-only shots it then picks the best `window` for the slot: no flagged
frames, close to the planned opening frame, and the strongest movement on a beat. A window never shows a take's
first two frames (the first is the sharper input still and pops), and spoken placements trim them too, reporting any
beat error this causes. Takes are not slowed: slowed motion steps visibly. Slowing a visual-only shot to 0.8x is an
explicit choice (`allow_retime: true`, or `window: {in_point_s, speed}`), and the render plan names every slowed
shot (`slowed_shots`). Prefer a cut-away, another take or a reshoot. Spoken shots are never retimed; their triage
lists the flaws inside the part that will be used.
`POST projects/{id}/triage` (`shot_id`, `source`) scans a candidate take without attaching it, so takes can be
compared before choosing. The render uses each window, and the render plan lists flaws still in use (`flagged_in_use`).

**Sound design.** `GET`/`PATCH projects/{id}/sound`:
- `reveal`: the music falls away `lead_s` before the last spoken line (or `shot_id`), by `depth_db`, and recovers over
  `release_s` after it. This is on by default.
- `hum`: a quiet low machine hum made by FFmpeg (`level_db`, `freq`), swelling by `swell_db` into the reveal. It is
  off by default.
- `voice.room`: a little room echo on the spoken take, so it sits in the scene.

The render plan shows the timing under `sound`. Only the spoken take and the song (or its stems) are used.

**Color script and grade matching.** `GET projects/{id}/look` returns each shot's lighting phrase and palette by
section (by default cold blue verses, a warmer hook and the machine's cyan at the end) and draws the strip under
`music-video/{id}/`. `PATCH projects/{id}/look` sets `sections` (`{name: {phrase, palette}}`), `grain` (0-1),
`match` and `match_strength`. Keyframe prompts take their light from the color script, so color is made in the
pictures. Grading is off until the human asks for it: with `match: true` each take's color is pulled toward its
shot's approved opening still (one limited gain and offset per clip, so it cannot flicker), and `grain` adds one
texture over the whole cut. Cutaways take the look of the section they sit in.

**Still review and hand-off.**
- `PATCH projects/{id}/keyframes` with `stills: [{name, candidates: [asset ids]}]` records generated candidates.
  Pass `agent: {model, session_id}` so the reviewer can be checked as independent.
- `approve: {asset_id, human_words}` records the human's choice in their own words. Use `made_from_first` on a
  closing still made by editing the approved opening one.
- `POST projects/{id}/keyframes/sheet` draws comparison sheets: the previz composition, then candidates A, B, C...
  with the lyric line, approvals outlined and review suggestions shown.
- `POST projects/{id}/scenes` creates one Studio scene per board shot, once, and remembers the mapping.
- `POST projects/{id}/keyframes/handoff` puts the approved stills into those scenes as first (and last) frames. By
  default it covers every shot whose stills are all approved; pass `scenes: {shot_id: scene_id}` to choose. It saves the previz still as the kit's staging reference (Studio keeps it out of the
  video request) and fills the camera and the end state (or free motion). Write the action and decide
  `complex_action` in the kit.

**Consistency review.** `POST projects/{id}/keyframes/packet` (`still`, `asset_id`) returns the packet for one
candidate: references, the candidate, the planned composition, the look, free local checks (frame shape, size) and the
brief. Run the review in a new session on the reviewer model the human chose and give it only the packet. Submit
with `POST projects/{id}/keyframes/reviews`: scores for `person`, `machine`, `room` and `look`, plus issues. Studio
refuses the wrong model or the director's own session and computes the suggestion: `consistent`,
`usable_with_fixes` or `regenerate`. The human still approves.

**Release kit.** `POST projects/{id}/release` (`formats` from 9:16, 16:9, 1:1 and 4:5; `thumbnails`; `captions`;
`max_side` for quick drafts) renders each frame shape. 16:9 shows the whole vertical picture over a blurred fill. It
checks the first two seconds (black or dark opening, nothing moving, first cut later than 3.5 s), picks thumbnail
frames (sharp, bright, colorful, away from cuts) and writes `lyrics.srt`. It also runs the flash check (more than
three flashes in any second fails) and returns a publishing checklist (the platform's AI-content label, no personal
details, no generated likeness of a real person). Every render strips file metadata, so no song IDs or tool tags
leave with the video.

## Craft tools (from Claudia's recipe and failure log)

**Line times from the vocal stem.** Speech recognisers can place a word up to 2 s early after a pause, which clips
first words. After `align`, `POST projects/{id}/line-times/refine` moves each line's start and end onto the vocal
stem's voiced edges (needs `stems.vocal`) and reports what moved. It clears the board, so redraft it afterwards.

**Grok prompts.** `POST projects/{id}/prompts/draft` (`shots`, `overwrite`, `speaker`) writes prompts in Grok's short
first-frame form for shots still marked TODO. Each prompt says "as in the first frame", gives a second-by-second
action from the keyframe moment, one camera line from the previz move, and "No on-screen text". A spoken shot gets
its line quoted with commas instead of full stops (a full stop makes the take pause), a smile in the eyes and lips
closed until the voice begins.

`GET projects/{id}/prompts` lints every prompt for:
- mood words the model obeys literally (deadpan, knowing, eyes on the lens)
- posture rules that freeze the performance
- a smiling mouth while speaking
- text and lettering
- looking past the lens
- a pull-back (Grok pushes in instead)
- big camera moves
- repeated sentences and lists of fixes
- length, and takes longer than 8 s

The board audit includes these as `prompt_*` findings.

**Board gates** (in the audit):
- the same camera setup twice in a row
- two shots opening on the same image
- shots under 1 s
- four shots of the same length in a row
- a slow hook (no cut by 3.5 s, or a slow wide opening)
- a close-up whose frame was not edited from a wider frame of the same place (set the still's `derived_from`)
- a continuation not opening on the previous take's own last frame

`POST projects/{id}/takes/last-frame` (`shot_id`, `to_shot`) saves a take's last used frame as an image and adds it
as the next shot's opening candidate, marked `continues`.

**Fresh-eyes review of the cut.** `POST projects/{id}/cut/sheets` (`file` from a render) draws one sheet per shot
(eight frames as cut), runs the flash check and returns the reviewer brief. Two reviewers, each in a new session on
the chosen reviewer model, give a verdict for every shot (`ok`, `polish` or `blocking`, with the problem and a fix)
through `POST projects/{id}/cut/reviews`. An empty review is refused, and so is a session that already reviewed the
cut. Fix blocking shots by reshooting with a better prompt or first frame, never by patching frames; then the human
watches at full speed.

**Shots made in code.** `POST projects/{id}/code-shots` (`shot_id`) renders a visual-only shot from the project's
stage spec without labels or lyrics, on the song clock, and attaches it as the take. It is free, exact and
repeatable. `POST projects/{id}/plates` paints a cut-paper set plate in code (`background`, `layers` of rect,
ellipse, polygon or path with a `depth` for cast shadows, a fixed `palette`, `grain`), or takes SVG you wrote (no
scripts, images or external links). It saves the plate as an image asset; with `use_as_set` it becomes the keyframe
plan's set reference. Ask the image model to rebuild it as a real, physical set for every still, so the world stays
one place.

## For humans in the browser

The music-video toolkit is agent-first: your agent runs it through the Agent API and stops at each checkpoint for
your decision. In Studio you can open `/previz` to watch the stand-in video with the song, and you review stills,
takes and cuts as the agent shows them. The other music-video steps have no Studio screens yet.

Python: `from music_video import beats, lyrics, speech, board, modes, lyric_text, render, previz, keyframes, triage, sound, grade, review,
release, stemtimes, grokprompt, gates, plates` (standard library, FFmpeg
and Pillow; previz rendering also needs Node and a headless Chromium); tests in `tests/test_music_video_*.py`.
