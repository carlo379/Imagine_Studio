# Setup and integrations

Install Imagine Studio, connect optional providers, and maintain the local app.
For everyday tasks, use the [User guide](USER_GUIDE.md). For automation, use the
[Agent API guide](AGENT_API.md).

## On this page

- [Requirements](#requirements)
- [Linux FFmpeg](#linux-ffmpeg)
- [Start the app](#start-the-app)
- [Connect providers](#connect-providers)
- [Configuration and private data](#configuration-and-private-data)
- [Optional local transcription](#optional-local-transcription)
- [Develop and test](#develop-and-test)
- [Optional macOS startup](#optional-macos-startup)
- [Troubleshooting](#troubleshooting)

## Requirements

| Tool | Needed for |
| --- | --- |
| Python **3.13 or 3.14**, with venv/pip | Local server and Python dependencies. |
| Node.js **22+** and npm | Frontend builds, Camera Control exports and JavaScript tests. |
| Git | Source checkout and the pinned Hermes integration. |
| FFmpeg and FFprobe (**9.0.1+ on Linux**) | Video inspection, frame capture and local exports. Include libx264 and AAC. |

macOS and Linux are the supported development targets. Windows is not yet
verified. Allow several GB for dependencies and export-test fixtures. Setup needs
internet access; provider accounts are optional for mock use.

## Linux FFmpeg

Linux requires **FFmpeg and FFprobe 9.0.1 or newer**, with both executables on
PATH. Setup checks this before installing app dependencies; server startup and
the offline verification runner also reject unsupported versions. macOS behavior
is unchanged. Unversioned development builds cannot be verified and are rejected.

Ubuntu 24.04's default FFmpeg 6.1.1 package is too old. Earlier releases are outside
the supported Linux configuration; we have not established 7.x/8.x compatibility.
Install a recent build yourself, or use the optional pinned source-build helper.
From the repository root on Ubuntu/Debian:

```sh
sudo apt-get update
sudo apt-get install -y build-essential pkg-config nasm curl xz-utils libx264-dev libass-dev libfreetype6-dev libharfbuzz-dev libfontconfig1-dev zlib1g-dev fonts-dejavu-core
sh scripts/install_linux_ffmpeg.sh "$HOME/.local/opt/imagine-ffmpeg"
export PATH="$HOME/.local/opt/imagine-ffmpeg/bin:$PATH"
python3 subscription-tester/ffmpeg_runtime.py
```

Keep that PATH in your shell or service environment. The helper builds version
9.0.1 from the [official source release](https://ffmpeg.org/releases/), verifies
its pinned SHA-256, and installs into the supplied prefix without replacing the
system FFmpeg. It needs internet access and time/disk space to compile. It does
not generate media. Normal app setup never installs or upgrades system tools.
Linux CI uses this same build and retains the audio regression tests.

## Start the app

From the repository root:

```sh
cd subscription-tester
sh setup.sh --mock-only
.venv/bin/python studio_server.py
```

Open **http://127.0.0.1:8765/**. Stop the server with **Ctrl+C**.

A fresh installation starts with no projects. Mock mode uses local fixtures and
makes no provider generation calls. Its sample video is a three-second test
pattern, independent of the requested settings. Remote image URLs may still
contact their hosts.

| Option | Command |
| --- | --- |
| Another port | `.venv/bin/python studio_server.py --port 8766` |
| Live mode, after connecting your own accounts | `.venv/bin/python studio_server.py --live` |
| Separate private workspace | Add `--state-dir /absolute/private/path/studio` outside the checkout. |

Stop the current server before switching modes. Never run two servers against
the same workspace directory. A different browser port has separate browser-only
drafts, even when the server workspace is shared.

Setup installs dependencies, builds the frontend, and creates the mathematical
mock fixture locally. It does not sign in, import projects, download transcription
models or submit media generations.

## Connect providers

For subscription integrations, first run `sh setup.sh` without `--mock-only`.
This also fetches the pinned Hermes source. Restart the server with **`--live`**.

| Connection | How to connect | What to expect |
| --- | --- | --- |
| **Grok / Hermes subscription** | Open Account and choose **Sign in with Grok via Hermes**. Complete the provider's device-verification page. | Grok image/video access depends on your account and entitlement. |
| **ChatGPT / Codex subscription** | Install Codex, run `codex login` if needed, then refresh the connection in Studio. | Writing and native Image 2 use the local Codex integration. Native image size and quality are automatic. |
| **OpenAI Image 2.5 API** | Set your own `OPENAI_API_KEY` in the server environment or the private data directory's `.env.local`. | Separate API billing; requires **Approve OpenAI API charges** for generation. |

> **Subscription and API billing are separate.** Studio does not silently switch
> an image generation to another provider or billing route. A connection indicator
> means credentials are present; it does not guarantee quota or model access.

Complete sign-in yourself. Never copy cookies, provider tokens or passwords into
prompts, browser code or repository files. Check reported usage in the app and
provider account; unavailable allowances appear as **unknown**.

The prompt writer tries ChatGPT first when no writer is selected. An eligible
writer failure permits one Grok fallback. This writing fallback does not generate
media. An explicitly selected writer has no automatic fallback.

## Configuration and private data

App limits are in **`studio-config.json`**. Stop the server before editing it,
then restart. Keep credentials and per-user paths out of this shared file.

| Setting | Purpose |
| --- | --- |
| `live_generations_enabled` | Allows or locks live requests; starting the server alone never generates media. |
| `prompt_limit_chars`, `prompt_limit_bytes` | Validation ceilings for the expanded request. These are limits, not writing targets. |
| `upload_limit_mb`, `download_limit_mb` | Local upload and cached-download limits. |
| `poll_interval_seconds`, `poll_timeout_seconds` | Polling behavior; a timeout does not resubmit a generation. |

For current model capabilities, use the UI or API `schema`. Do not bypass
validation by raising limits to values unsupported by the provider.

**Application source and user data are separate.** On macOS, private data defaults
to `~/Library/Application Support/Imagine Studio/`. Linux uses the XDG data
location. `IMAGINE_STUDIO_DATA_DIR` can select another external location.

See [Configuration](../docs/CONFIGURATION.md) for all platforms, workspace layout,
optional environment variables and migration from legacy storage. Stop all servers
before migrating or backing up. Keep backups private; they may contain credentials.

The server binds to loopback and is intended for local use. Do not expose it to
the public internet. Uploading media stores it locally; approved live requests send
the selected inputs to the selected provider. Download completed outputs promptly
because remote links may expire.

## Optional local transcription

SRT import works without a transcription engine. To enable local transcription:

1. From `subscription-tester/`, install the optional dependencies:

   ```sh
   .venv/bin/python -m pip install -r requirements-transcription.txt
   ```

2. Supply a pre-existing CTranslate2 Whisper model folder containing
   `model.bin`, `config.json`, `tokenizer.json` and its other model files.
3. Restart Studio. In **Edit → Captions**, set **Local model folder**, save it,
   and choose **Check local model**.

The app never downloads a model. Transcription runs locally on CPU/int8.
Compatible faster-whisper/CTranslate2 wheels are required for your platform.
If unavailable, use **Import SRT**. Workspace model settings take precedence over
`local_transcription_model` in the app configuration.

## Develop and test

From the repository root:

```sh
cd subscription-tester
sh setup.sh
npm run build
cd ..
python3 scripts/verify.py
python3 scripts/check_docs.py
```

The full offline suites need the pinned Hermes source, even though provider calls
are mocked. Tests use isolated fixtures; never point tests at production storage.
Local FFmpeg fixtures are rendered, but no real provider generation is needed.

Rebuild after editing TypeScript or bundler inputs. Commit the generated manifest
and its referenced chunks together. The build removes retired chunks. The server
uses the manifest for cache-safe asset URLs; restart it after Python changes.

Optional browser pixel comparisons need a test-only headless browser. On Linux,
set `IMAGINE_CAMERA_REFERENCE_BROWSER` to a separately pinned executable. The
bundled browser installer targets macOS arm64.

| Source area | Responsibility |
| --- | --- |
| `studio_server.py` | Local server and media orchestration. |
| `agent_api.py`, `agent_openapi.py`, `agent_client.py` | Agent routes, contract and SDK/CLI. |
| `ui/`, `static/` | Browser UI and committed build artifacts. |
| `video_rules.py`, `prompt_guides.py` | Validation and runtime authoring guides. |
| `editing_studio.py`, `editing_tools.py`, `editing_batches.py` | Timeline editing and bounded local exports. |
| `tests/` | Offline Python and JavaScript suites. |

## Optional macOS startup

`launchagents/imagine-studio.plist.example` is an uninstalled template. Replace
its app/log directory placeholders before installing it. Choose the desired port
and mode explicitly. Credentials and projects stay in private user storage.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Unsupported Linux FFmpeg | Install both tools at 9.0.1+ using [Linux FFmpeg](#linux-ffmpeg) and put them first on the server’s PATH. |
| Setup stops early | Confirm the required Python, Node/npm, Git and FFmpeg tools are on PATH. |
| Address already in use | Stop the other server or select another port. |
| Legacy workspace warning | Stop all workers and follow the [migration instructions](../docs/CONFIGURATION.md#private-user-storage). |
| Provider connection fails | Complete sign-in, refresh connection, then inspect the provider message. Do not replace subscription credentials with an API key. |
| Export or frame capture fails | Confirm FFmpeg/FFprobe and input files are available; inspect the displayed FFmpeg error. |
| UI looks outdated | Rebuild frontend assets after source edits and reload the page. |
| Captions cannot transcribe | Configure the optional engine/model, or import SRT. |

For creating and editing media, continue to the [User guide](USER_GUIDE.md).
