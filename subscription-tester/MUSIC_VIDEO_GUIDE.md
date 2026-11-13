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
- Takes are slipped by trimming their start (picture and sound together), never stretched, so lip-sync is untouched.
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

## The loop

1. `POST projects` with `title`, `production_id`, `mode`, `master` (an uploaded song), `lyrics`, optional `stems`,
   `song_has_vocals`, `spoken_lines`, `price_per_second`.
2. `POST projects/{id}/analyze`: tempo, beats, bars, downbeat guess, sections. Confirm the phase; fix with `PATCH phase`.
   Then `POST projects/{id}/align` with word times from a transcript of the vocal (a local Whisper model works) so the board
   follows the song's real line times.
3. `GET projects/{id}/lint`: digits, symbols and acronyms to spell out; each line's bar slot and fill.
4. `POST projects/{id}/board/draft`, then `PATCH projects/{id}/board` to write each shot's `prompt` and `purpose`.
   A spoken shot's prompt must quote its lyric line exactly.
5. `GET projects/{id}/audit`: must be `ok` before any spend (bar-line cuts, 7-14 shots a minute, every line covered,
   quote match, audio rules, mode requirements, cost ceiling = seconds x takes x your calibrated price).
6. Generate takes through the production flow with the human's approvals, one at a time. Attach each with
   `POST projects/{id}/takes` (`shot_id`, `source`, optional `heard_words` from a transcript). Spoken shots return the
   measured speech window, the beat placement (`in_point_s` to trim), the pace check and the word-error check. A take
   that cannot land on a beat within 0.35 s, or says the wrong words, needs a retake or a cover shot.
   Every attached take is triaged (see Finishing tools); visual-only shots also get their best window.
7. `POST projects/{id}/render-plan` previews placements, mute spans and the lyric gate. `POST projects/{id}/render`
   writes the cut under the workspace `music-video/` folder (FFmpeg; song ducked under speech; loudness normalized;
   lyrics burned in word by word with Pillow, so FFmpeg needs no text filters).

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
- Humans: open `static/previz.html` over a local web server (module scripts do not load from `file://`), choose the spec
  JSON and the song, and scrub or play with the real audio. A spec can also come from `?spec=URL`.
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
- `PATCH projects/{id}/keyframes` edits `stills` (`name`, `moment`, `prompt`, `t` inside the shot), `references`,
  `candidates` or `price_per_image`. A redrafted board clears the plan.
- `POST projects/{id}/previz/stills` (optional `stills: [{name, t}]`) writes clean PNGs, with no PREVIZ label, timecode
  or lyrics, to `music-video/{id}/stills-r{revision}/`. They are taken at the plan's still times (or each shot's
  opening instant when there is no plan) and recorded on the plan as `previz_still`, so each generated still can be
  compared with its planned composition. Humans can press **Save still** in `static/previz.html`.
- Nothing here generates an image. Generating the batch is a spend the human approves.

Lyric timing on song-carried lines is estimated from the slot, not aligned to the vocal, and the render plan says so.
Changing the mode, lyrics, spoken lines or phase clears the board and its takes.

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
- `POST projects/{id}/keyframes/handoff` with `scenes: {shot_id: scene_id}` puts the approved stills into Studio scenes
  as first (and last) frames. It saves the previz still as the kit's staging reference (Studio keeps it out of the
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

Python: `from music_video import beats, lyrics, speech, board, modes, lyric_text, render, previz, keyframes, triage, sound, grade, review,
release, stemtimes, grokprompt, gates, plates` (standard library, FFmpeg
and Pillow; previz rendering also needs Node and a headless Chromium); tests in `tests/test_music_video_*.py`.
