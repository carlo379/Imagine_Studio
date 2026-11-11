# Imagine Studio

A local filmmaking studio for AI video. Take a story from idea to a finished, edited
video: series bible and scripts, storyboards, 3D shot staging, image and video generation
with **Grok Imagine** (plus OpenAI images and writing), review, timeline editing and
export. Everything runs on your computer; the browser UI is on localhost.

Humans and AI agents use the same projects and rules. **You can work directly in the
browser, or let an agent (Claude Code, Codex or another) produce for you through the local
Agent API** while you stay in charge of models, plans, spending and taste.

## What it does

- **Develop:** series bibles, characters, locations and props with approved reference
  images; scripts split into scenes; episode books.
- **Storyboard:** shots with 3D staging (posable mannequins, props, camera and lens),
  continuity review and approved starting frames.
- **Generate:** Grok Imagine video with first, last and middle frames, references and
  voices; Grok and OpenAI images; validation and an exact request preview before anything
  is sent.
- **Review and learn:** keep, retry or reject every take; your verdicts become a taste log
  that agents and reviewers read before the next prompt.
- **Edit:** a timeline with trims, transitions, audio, titles and captions, exported locally
  with FFmpeg at no AI cost.

### Autonomous production with control

- **You choose the models:** which one directs and which one reviews each take.
- **Shot kits:** every shot gets 3D staging and approved frames before Grok is used, so the
  video model moves between known pictures instead of inventing everything.
- **Approve a plan once:** the shots, takes per shot and a usage budget. The agent then
  works within it.
- **Every take is reviewed:** an independent AI reviewer session suggests a verdict; you
  decide. Studio tracks how often the reviewer agrees with you.
- **Costs are learned, not guessed:** Studio learns what a take costs from your Grok usage
  readings and estimates each plan.

See the [Autonomous production guide](subscription-tester/AUTONOMOUS_PRODUCTION_GUIDE.md).
Agents should start at [AGENTS.md](AGENTS.md).

## Install

Supported development targets: macOS and Linux. Windows is not yet verified.
Install Python 3.13 or 3.14 (with venv/pip), Node.js 22+, npm, Git, FFmpeg and
FFprobe. On Linux, **both must be 9.0.1 or newer**; see the
[Linux FFmpeg instructions](subscription-tester/README.md#linux-ffmpeg). FFmpeg
must include libx264 and AAC. Allow several GB for dependencies
and fixture-based export tests. Live providers are optional and require your own
accounts; some models incur separate API charges.

From the repository root:

```sh
cd subscription-tester
sh setup.sh --mock-only
.venv/bin/python studio_server.py
```

Open http://127.0.0.1:8765/. Mock mode uses local fixtures and needs no provider
credentials. External image URLs can still contact their hosts. Stop with Ctrl+C.
Use `--port 8766` if the default port is occupied. Never run two server processes
against the same state directory.

For subscription integrations, run `sh setup.sh` to also fetch the pinned Hermes
source, configure your own accounts, then explicitly use `--live`. Setup never
signs in, downloads transcription models, or generates media. Do not copy another
installation's state or credentials. See [configuration](docs/CONFIGURATION.md).

## Develop and verify

```sh
cd subscription-tester
# Full tests import the pinned Hermes auth module with mocked network calls.
sh setup.sh
npm run build
cd ..
python3 scripts/verify.py
```

Verification runs all Python test modules in separate processes and all
JavaScript suites. Each process has a three-minute timeout that also terminates
its fixture-rendering children. Provider calls
are mocked; local FFmpeg/Canvas fixtures are rendered. Optional browser pixel
parity requires a separately configured test browser and otherwise skips. Tests
must never use production credentials or the running production server. Full
verification can take several minutes. CI records its actual FFmpeg version on
Linux and macOS; passing one version does not establish all-version compatibility.

Prebuilt frontend bundles are committed so ordinary startup does not need a
frontend build. Rebuild after changing TypeScript or bundler inputs; commit the
manifest and all referenced chunks together. `package-lock.json` is committed.

## Documentation

- **For agents: [AGENTS.md](AGENTS.md)**, the starting point for any AI agent
- [User guide](subscription-tester/USER_GUIDE.md)
- [Autonomous production guide](subscription-tester/AUTONOMOUS_PRODUCTION_GUIDE.md)
- [Application and integration setup](subscription-tester/README.md)
- [Agent API guide](subscription-tester/AGENT_API.md) and [reference](subscription-tester/AGENT_API_REFERENCE.md)
- [Directing tools](subscription-tester/DIRECTING_TOOLS_GUIDE.md), [Image Studio](subscription-tester/IMAGE_STUDIO_GUIDE.md),
  [Series Bible and episode books](subscription-tester/SERIES_BOOKS_GUIDE.md),
  [Story Studio](subscription-tester/STORY_STUDIO_GUIDE.md),
  [production workspace](subscription-tester/PRODUCTION_WORKSPACE_GUIDE.md),
  [filmmaking tools](subscription-tester/FILMMAKING_TOOLS_GUIDE.md)
- [Model prompting guides](docs/prompting-guides/)
- [Grok Imagine prompting guide](docs/prompting-guides/Grok_Imagine_Prompting_Guide.md)
- [Security and disclosure](SECURITY.md)
- [Contributing and verification](CONTRIBUTING.md)
- [Third-party materials and rights review](THIRD_PARTY_NOTICES.md)

## Source scope and license

    Original application code is MIT licensed. This snapshot intentionally omits
    private history, production records and copied provider documentation. The
    included speech fixture remains CC BY 4.0 with attribution. On first setup,
    FFmpeg creates the mock mathematical test-pattern clip locally. No original
    production media or historical binary mock clip is distributed.
    