# Sound and delivery guide

How to make the sound of a short ad or film in Studio, hand the cut to Resolve, and check
the finished file before posting. The examples come from a 30-second ad where one invented
sports call is heard through a different device in each of four places, the music's drums
land on the picture's big moment, and the end card has a short voice-over.

Browser pages: `/sound` and `/delivery` (also in **Tools**). Agent routes: see
[the API reference](AGENT_API_REFERENCE.md#sound-delivery-and-resolve).

## On this page

- [1. Voice lines on Grok Lite](#1-voice-lines-on-grok-lite)
- [2. Save the sound as a stem](#2-save-the-sound-as-a-stem)
- [3. One voice through each place's device](#3-one-voice-through-each-places-device)
- [4. Fit the music to the hit](#4-fit-the-music-to-the-hit)
- [5. Hand the cut to Resolve](#5-hand-the-cut-to-resolve)
- [6. Check the final file](#6-check-the-final-file)
- [What we learned](#what-we-learned)

## 1. Voice lines on Grok Lite

When only the sound of a take matters (a narrator, an announcer, a phone voice), make it on
**Grok Imagine Video 1.5 Lite at 480p**: about a quarter of the cost of full Video 1.5 per
second. The picture is thrown away.

```python
out = client.create_voice_line(
    "End card VO",
    voice="a deep, warm British male narrator, normal speed, with quiet emotion",
    lines=[{"text": "Same moment.", "at_s": 1}, {"text": "Everywhere."}, {"text": "Your brand."}])
```

Studio makes a scene with a still, neutral picture, the lines quoted with their times, "No
music", and "No subtitles". Generating it is an ordinary take: show the prompt, get the
human's approval, and generate with `approved=True` and their words.

**Describing the voice.** Lite has no preset voices; it voices what the prompt describes.
- Accent and character work: "a deep British male narrator" changed the voice.
- Pitch words alone do not: "a deeper voice" came out no lower (measured).
- Ask for normal speed and the emotion you want. A slower read sounded flat.

## 2. Save the sound as a stem

```python
stem = client.save_stem(job_id=take["id"])          # or path="/Users/you/Music/song.wav"
```

A stem is a 48 kHz WAV. When a local Whisper model is installed (see the editor's
transcription settings), the stem gets word times, and a voice line's own text is the
hint. Nothing is downloaded.

## 3. One voice through each place's device

`place_stems` builds a full-length stem from pieces placed at timeline times. Each piece can
have its own device sound:

| Device | Sound |
| --- | --- |
| `radio` | Band-passed 400–3000 Hz with soft clipping (a boat's marine radio) |
| `tablet` | Thin, high-passed at 600 Hz |
| `tv` | A small room echo |
| `laptop` | High-passed at 300 Hz, boxy +4 dB at 900 Hz |
| `phone` | 300–3400 Hz |
| `clean` | Full range (the big moment) |

```python
client.place_stems("Broadcast", 30, [
    {"stem_id": call["id"], "from_s": 0.0, "to_s": 4.0, "at_s": 0.0, "device": "radio"},
    {"stem_id": call["id"], "from_s": 4.0, "to_s": 7.0, "at_s": 4.0, "device": "tablet"},
    {"stem_id": call["id"], "from_s": 12.0, "to_s": 13.0, "at_s": 12.0, "stretch_to_s": 3.4, "device": "tv"},
    {"stem_id": call["id"], "from_s": 13.5, "to_s": 14.6, "at_s": 15.48, "device": "clean"},
])
```

Put each piece on its picture cut. Use `stretch_to_s` to hold a sound (a crowd's "ooooh")
across a run of short cuts, and `gain_db` to tame a line that is louder than the big moment.

## 4. Fit the music to the hit

Compose the song to the exact length (in Suno, set Duration to Custom), then **slide the
whole song** so its drum entry or big hit lands on the picture's hit. Never cut it up.

```python
fit = client.music_fit(15.5, 30, stem_id=song["id"])              # proposals from the song's energy
fit = client.music_fit(15.5, 30, stem_id=song["id"], song_event_s=16.93)  # the moment you heard
music = client.write_music("Music", 30, stem_id=song["id"], offset_s=fit["options"][0]["offset_s"],
    keyframes=[{"at_s": 0, "db": -8}, {"at_s": 13, "db": -8},     # under the voices
               {"at_s": 15.5, "db": 0},                            # an even rise to full level on the hit
               {"at_s": 22, "db": 0}, {"at_s": 22.01, "db": -2},   # under the end card
               {"at_s": 25.6, "db": -2}, {"at_s": 25.61, "db": -7}])
```

The proposals (energy rises, kick hits, section starts) are guesses. Listen, and if none is
the moment you want, give it as `song_event_s`. Volume keyframes are straight lines in dB
between points, so a rise from −8 dB at 13 s to 0 dB at 15.5 s is even to the ear.

## 5. Hand the cut to Resolve

```python
out = client.export_to_resolve(title="My ad sound v1", video=[{"path": p} for p in clips],
    audio=[{"stem_id": broadcast["id"], "track": "Broadcast call"},
           {"stem_id": vo["id"], "track": "End VO"},
           {"stem_id": music["id"], "track": "Music"}],
    output_folder="/Users/you/Projects/My ad/edit")
```

- **New timeline:** in Resolve, File → Import → Timeline… and choose the `.fcpxml`. The clips
  sit in order on the video track, and each stem is on its own audio track. The media files
  stay where they are.
- **Add sound to an edit already made in Resolve:** Workspace → Console → Lua, then
  `dofile([[path to the .lua]])`. It duplicates the open timeline and adds each stem on a new
  named audio track, so the original is untouched.

## 6. Check the final file

Run every render through the delivery check before posting, including renders from Resolve.

```python
check = client.check_delivery("/Users/you/Movies/My_Ad_v4.mp4", preset="contest_30s_1080p")
print(check["verdict"], check["reasons"])
if check["fixable"]:
    fixed = client.fix_delivery(check["id"])        # saved as My_Ad_v4_DELIVERY.mp4
```

It measures the codecs, frame size and rate, the exact picture, sound and file lengths (in
frames), integrated loudness, true peak, clipping, the loudest moments, and black or frozen
stretches, and makes a contact sheet. Presets: `contest_30s_1080p`, `x`, `youtube`, or a
custom `spec`.

**The fix** copies the picture untouched and re-encodes only the sound: trimmed or padded to
the exact length, at the spec's sample rate and bit rate, and normalized to the loudness
target under the true-peak limit. It never overwrites a file.

What it caught on the ad:
- Resolve's AAC encoder added about 0.07 s, so the file ran 30.07 s instead of 30.00 s. This
  cannot be fixed on Resolve's timeline; the fix trims the sound only.
- One render's sound was 48 kHz at 320 kbps, not the 44.1 kHz at 192 kbps the brief asked for.
- One line of the call peaked at +0.8 dBFS and was louder than the big moment. The loudest
  moments list shows where; lower that piece's `gain_db` and render again.

## What we learned

- Approve every still before any video, then make sound last, on the finished picture.
- Use Lite for voice-only takes. Describe the accent and character, not the pitch.
- One continuous voice heard through different devices carries a story across cuts in
  different places without lyrics.
- Slide a song, don't cut it: one slide can line up its hit, its crash and its calm passage
  with the picture.
- Measure instead of trusting ears: the clips of a rough cut were about 12 dB apart.
- Check the final file's exact length, frame count, loudness and true peak before posting,
  and read the contest's own rules again before you post.
