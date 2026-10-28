# Configuration without shared credentials

The committed `subscription-tester/studio-config.json` contains application
limits. Mock mode is the default CLI behavior, even though the configuration
allows explicitly authorized live requests when started with `--live`.
Do not put credentials in this JSON file.

Local optional environment configuration:

| Name | Example (placeholder only) | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | `YOUR_OWN_KEY` | Explicitly selected, separately billed OpenAI API image models |
| `IMAGINE_CAMERA_REFERENCE_BROWSER` | `/absolute/path/to/test-browser` | Optional test-only browser pixel comparison |

No key is required for mock mode. Subscription connections use the application's
sign-in flow. Keep private environment files, provider credentials, `.state/`,
and browser profiles on the local machine. Do not attach them to issues or upload
them to GitHub. Configure any optional transcription model through the editor's
revisioned transcription settings; the app does not download models automatically.

The repository's LaunchAgent is an uninstalled template. Replace its placeholders
before installing it. Setup never imports production content. Existing installations use the explicit migration below.

## Private user storage

The app starts with no projects, assets or generated media. Each user creates or
imports their own work. All projects, media, exports, history, account profiles,
agent tokens and diagnostics live outside the application checkout:

- macOS: `~/Library/Application Support/Imagine Studio/`
- Linux: `$XDG_DATA_HOME/imagine-studio/` (default `~/.local/share/imagine-studio/`)
- Windows: `%LOCALAPPDATA%/Imagine Studio/`

Set `IMAGINE_STUDIO_DATA_DIR` to choose another private location outside the
checkout. `studio/` contains workspace data; `hermes/` contains the isolated
subscription profile. The SDK reads its default agent token from this location.
Optional private `.env.local` configuration also lives here, never in source.
`--state-dir` may select an external studio workspace; it cannot point inside the
checkout. No workspace is imported automatically on a fresh install.

For existing installations, stop every server and worker, then run
`python3 scripts/migrate_user_data.py --server-stopped` from the repository root.
This atomically moves the old storage directory without opening its files and
refuses to merge with an existing destination. Keep a filesystem backup first.
Cross-volume moves fail safely; choose a destination on the same volume for
migration, then relocate the private directory with the server stopped if needed.
Restart the server after migration. Never copy private storage into GitHub or
include it in application packages. Keep this directory when upgrading or
uninstalling the code unless you explicitly want to delete your work.

## Linux media toolchain

Linux startup requires both FFmpeg and FFprobe 9.0.1 or newer. Both must be on the
server's PATH; changing only your interactive shell PATH does not change a running
service's environment. Restart the service after upgrading. The app does not
silently use an older fallback. See the [Linux installation instructions](../subscription-tester/README.md#linux-ffmpeg).
