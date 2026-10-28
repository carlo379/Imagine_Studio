# Public source release policy

This is a history-free public source edition. The private upstream repository
and its historical materials are not part of this distribution. The MIT grant covers original
application code; it does not clear third-party material or production records.

Run `python3 scripts/prepare_public_source.py` to create a new, ignored
`dist/github-public-source/` directory. It has no `.git` history. The exporter uses
an explicit source allowlist and records excluded filenames in a local-only audit
manifest outside the public directory. Original files and Git history stay intact.
Review and test that directory before initializing a separate public repository.
This command never creates a remote, publishes, pushes, or changes the running app.

The source snapshot excludes:

- All internal reports, handoffs, production migration scripts, production JSON
  records, audit evidence and root issue documents.
- Copied provider documentation and the downloaded voice-catalog HTML/Markdown.
  Public setup documentation links to provider originals instead.
- Historical recordings and all original Git history.
- The historical mock MP4, whose original encoding recipe is not established.
  On a clean setup, FFmpeg creates a mathematical test pattern locally instead.
- Credentials, environment files, runtime state, dependencies, caches and media
  outside the explicit test-fixture exceptions.
- The legacy prompting handbook. The three active runtime model guides remain.

Included third-party speech: LibriSpeech utterance `2277-149896-0026`, CC BY 4.0.
Attribution, source URL, conversion details and hashes accompany the recording.
Bundled frontend dependency license texts remain with the MIT application license.
See THIRD_PARTY_NOTICES.md. No third-party permission is implied for excluded files.

Private reports are preserved locally, not retrospectively relicensed. A sanitized
snapshot is the publication path; deleting current files alone would not remove
their historical versions from a GitHub push.

Upload only `dist/github-public-source/`, not the working repository or the parent
`dist/` directory. The parent contains a local audit manifest listing excluded
private filenames. Start any public Git history from the snapshot, not by adding
a public remote to this original repository. No remote or push is automated.

User-created projects are never installed with the application. User storage is
outside the checkout; see CONFIGURATION.md. Keep historical production documents
in a separate private archive, not among application sources. Never publish that
archive, user storage, or old Git history. A fresh clone starts empty.

Use `--privacy-terms /private/path/to/identifiers.json` with the exporter to check
owner/project identifiers across guides, source, tests and compiled bundles.
The private identifier list must remain outside this repository. The gate prints
locations only. Also run credential scanning independently. Generic app concepts
and official provider voice IDs are not private project data.
