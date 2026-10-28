# Third-party notices and public-source clearance

Original Imagine Studio code is MIT licensed; see LICENSE. Third-party materials
retain their own terms and are not relicensed by the MIT grant. Bundled React,
React DOM and scheduler license texts are in THIRD_PARTY_LICENSES.txt.

## Material included in public source

- `tests/fixtures/ducking-speech.wav` (under subscription-tester): LibriSpeech
  dev-clean utterance `2277-149896-0026`, CC BY 4.0. Corpus authors: Vassil
  Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur. Source:
  https://www.openslr.org/12/ . License: https://creativecommons.org/licenses/by/4.0/ .
  The FLAC recording was decoded to mono 16 kHz PCM WAV. Source archive/member,
  conversion details and hashes are in the adjacent fixture Markdown file.
  The recording remains CC BY 4.0. No endorsement is implied.
- Frontend dependency license texts accompany the served bundles. Python and npm
  dependencies are installed from the requirements files and package lock; their
  own license files must remain with any separately redistributed package copies.
- Hermes is fetched only by optional subscription setup at commit
  `357f51c49106f47136caf9b01015467b7b633fe8`. Its source/license stay in the ignored
  `.deps/hermes` folder. It is not part of the public source snapshot. FFmpeg is
  also a separately installed tool, not a bundled binary.

## Material excluded from the public source snapshot

- Copied provider documentation and the downloaded voice catalog. Public docs
  link to the providers' originals instead of redistributing their snapshots.
- Historical production records, migration scripts, issue documents, internal
  handoffs, audits and reports. No production asset or document permission is
  inferred from the application license.
- Historical speech fixtures. Only the attributed LibriSpeech recording is included.
- The old mock MP4. Public setup creates a local mathematical FFmpeg test pattern
  if the file is absent; no original binary clip is redistributed.

Use `scripts/prepare_public_source.py` and follow docs/PUBLIC_RELEASE.md. The private upstream repository retains historical materials for local
development; those files and their history are not included in this edition. The snapshot contains no original .git history.
This exclusion policy is the clearance path for material whose public distribution
permission has not been established; it is not a claim that such permission was
obtained. A source manifest records exactly what was included and excluded.
