# Imagine Studio

A local filmmaking workspace for story planning, image and video direction,
asset continuity, review, and timeline editing/export. Humans and agents use the
same saved projects and validation rules. The browser UI runs on localhost.

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

- [User guide](subscription-tester/USER_GUIDE.md)
- [Application and integration setup](subscription-tester/README.md)
- [Agent API](subscription-tester/AGENT_API.md)
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
    