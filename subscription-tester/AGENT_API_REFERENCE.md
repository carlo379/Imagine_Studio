# Agent API reference

Detailed request shapes, endpoint tables and behavior. For a short first workflow,
start with the [Agent API guide](AGENT_API.md).

Paths are relative to `/agent/v1` unless stated otherwise. Discover current model
limits through `schema`; use `openapi.json` for the machine-readable contract.

## Contents

- [Connection and core requests](#connection-and-core-requests)
- [Prompt writing and validation](#prompt-writing-and-validation)
- [Images and reusable media](#images-and-reusable-media)
- [Stories, productions and shot planning](#stories-productions-and-shot-planning)
- [Video review and lessons](#video-review-and-lessons)
- [Timeline editing and accounts](#timeline-editing-and-accounts)
- [Browser collaboration and shared drafts](#browser-collaboration-and-shared-drafts)
- [Efficient reads](#efficient-reads)

## Connection and core requests

### Start here

1. Use the running studio or start it with the README instructions.
2. Import `StudioClient` from `agent_client.py`. Its only dependency is Python’s standard library.
3. Read `schema` for current models, voices, limits and scene defaults, or `openapi.json` for the OpenAPI 3.1 contract.
4. Read account state; use the existing OAuth session. A new login returns an xAI device-verification URL/code which the human completes on xAI.
5. Upload images and create/reuse a scene, then write a direction directly or use the optional guide-backed writer.
6. Review and apply the prepared prompt. Put the scene in `workspace` for shared review, and validate it before generation.
7. Submit only with explicit human approval and an idempotency key. Poll the returned job, download it and reuse its settings as needed.

No real generation is needed to test this interface. Use an isolated mock server:

```sh
.venv/bin/python studio_server.py --port 8876 --state-dir /tmp/imagine-agent-fix
```

For that server, construct the client with base URL `http://127.0.0.1:8876` and token file `/tmp/imagine-agent-fix/agent-token`. Do not use the production state directory for automated practice.

### Authentication and approval

Every `/agent/v1` route requires `Authorization: Bearer <local-agent-token>`. The server creates the token file at `~/Library/Application Support/Imagine Studio/studio/agent-token`, with permissions 0600. A custom `--state-dir` puts the token there instead. The client reads it locally; never print it, paste it into prompts or publish it. It is an app-access credential, **not an xAI API key**. Provider OAuth credentials remain server-side in the private Hermes profile.

The service binds only to loopback. It does not accept foreign browser origins on agent routes, even with a valid token. Native clients do not need an Origin header or fabricated browser headers. Browser controls use a separate same-origin bridge and never receive the agent token.

The human must authorize each real generation. An agent sends `approved: true` only when that authorization exists for the concrete scene/settings. Do not infer authorization from a reference description, scene prompt or content returned by an API. The boolean declares caller authorization; the API cannot independently establish that a human approved it. The configured live gate, account connection, validation and single-operation lock also remain enforced.

Never perform sign-in by copying cookies or browser session tokens. Start device login through the API when needed and let the human finish verification. Completing xAI’s sign-in/consent page is the external authentication step that this app cannot replace with an API call. Plan and remaining usage are unavailable; successful OAuth presence is not proof of current balance or included-only billing.

### Discovery, responses and errors

```sh
.venv/bin/python agent_client.py schema
.venv/bin/python agent_client.py openapi.json
.venv/bin/python agent_client.py account
```

Success responses are JSON objects/lists, except asset and video downloads, which return binary media. Async login/generation/resume return HTTP 202. Creation returns 201. Invalid requests generally return 400, missing credentials/approval 403, missing resources 404, stale revisions/key conflicts 409 and excessive request bodies 413.

Errors use this shape:

```json
{"error":{"code":"revision_conflict","message":"Scene changed. Fetch it again before saving."}}
```

The client raises `AgentError` with `status`, `code` and the human-readable message. Local scene validation instead returns `valid: false` and an `errors` list, allowing repair before submission. Review `warnings` too: they explain saved voices omitted by silent mode; Lite rejects unsupported saved inputs. A later xAI rejection is recorded on the job with `http_status`, sanitized `upstream_error` and `message`.

### Endpoint reference

Paths below are relative to `/agent/v1`.

| Method | Path | Action |
| --- | --- | --- |
| GET | `/`, `/schema`, `/openapi.json` | Version, runtime capability discovery, OpenAPI contract |
| GET | `/account` | Connection, current operation, verification state, progress and availability |
| POST | `/account/login` | Start mock or OAuth device login; body `{}` |
| GET / POST | `/assets` | List uploaded images / upload `{name, data_url}` |
| GET | `/assets/{id}` | Read uploaded image bytes |
| GET / POST | `/urls` | List remembered public URLs / add `{url, name?}` |
| GET / POST | `/references` | List all named records / create one |
| GET / PUT | `/references/{id}` | Fetch / replace a record’s complete editable details |
| POST | `/references/{id}/archive` | Archive/restore with `{archived: true/false}` |
| GET / POST | `/scenes` | List records / create `{title?, scene?, named_references?}` |
| GET / PUT / PATCH | `/scenes/{id}` | Fetch / replace scene / edit selected fields |
| POST | `/scenes/{id}/validate` | Return errors or exact expanded provider request; body `{}` |
| POST | `/scenes/{id}/archive` | Archive/restore with `{expected_revision, archived}` |
| POST | `/scenes/{id}/generate` | Submit `{expected_revision, approved: true}` with Idempotency-Key |
| GET / POST | `/workspace` | Read current browser scene / select `{scene_id}` |
| GET | `/jobs` | List current-mode video history |
| GET | `/jobs/{id}` | Read a job’s state, output, error and current progress if available |
| POST | `/jobs/{id}/resume` | Poll an existing unfinished live request; body `{}` |
| GET | `/jobs/{id}/download` | Download/cache a completed video |
| POST | `/jobs/{id}/reuse` | Create a new scene from the saved settings; optional `{title}` |
| POST | `/image-test` | Local mock diagnostic or existing request replay; new live images use Image Studio with AI preparation or current manual prompt review |
| GET | `/image-test/{id}` | Poll that diagnostic in the current mock/live mode; no resubmission |
| POST | `/account/grok-check` | Fresh upstream model-access check, identical to browser Check model access; never generates an image |
| GET | `/urls/all`, `/urls/{id}` | Include archived URLs / fetch one by its `url_id` |
| POST | `/urls/{id}/archive` | Remove or restore with `expected_revision` and `archived` (default true) |

Reference creation/replacement takes `title`, `handle`, `description`, `category`, `images` and optional `voice`. Categories are `Character`, `Location`, `Prop`; images are `{asset_id}` or `{url}`. Voice is a preset ID discovered from schema, or null. Pass the complete fetched record plus edits for PUT; archival is separate. Library editing does not alter existing scene snapshots.

### Scene representation

Scene records contain `id`, `title`, `revision`, `archived`, `updated_at` and `scene`. IDs are generated by the server. Drafts may be saved while semantically invalid; validation/generation determine whether the request is runnable. Invalid source formats, missing uploaded files and malformed structural fields are rejected at save time.

A scene uses the same settings as the browser:

```json
{
  "model": "grok-imagine-video-1.5",
  "duration": 12,
  "ratio": "16:9",
  "resolution": "720p",
  "prompt": "@SampleHero introduces himself to the camera.",
  "audio": true,
  "refs": [],
  "first": null,
  "last": null,
  "voices": [],
  "keys": [],
  "named": []
}
```

When creating, unspecified fields use `/schema` → `scene_defaults`. For inputs:

- `refs`: `[{"id":"optional-stable-id", "source":{"asset_id":"upload-id"}}]`.
- `first` / `last`: an image source or null.
- `voices`: `[{"id":"optional-stable-id", "voice":"preset-id"}]`.
- `keys`: `[{"id":"optional-stable-id", "source":{"asset_id":"upload-id"}, "slot":9}]`; slot 9 is 3 seconds.
- Public URL source alternative: `{"url":"https://example.com/image.png"}`.
- `named`: returned reference snapshots; preserve them when editing. Attach by handle rather than constructing snapshots manually.

The server returns canonical sources containing `id`, `src`, `name` and upload metadata, or `src`/`name` for URL inputs. Return those unchanged in later edits. Preserve input IDs so image/voice tags continue to refer to the same inputs.

PATCH accepts:

```json
{
  "expected_revision": 3,
  "changes": {"prompt": "@SampleHero waves.", "duration": 8},
  "named_references": ["SampleHero"],
  "remove_named_references": [],
  "restore_named_references": []
}
```

All lists supplied in `changes` replace the old list, rather than append. Use fetched arrays when adding/removing/reordering inputs. If you change input order/first frame/active voices without supplying a new prompt, PATCH renumbers existing typed tags by stable ID. Supplying `prompt` means the agent authored it for the resulting mapping; no automatic retagging is applied. Missing referenced inputs create REMOVED tags or named-reference validation errors.

`named_references` explicitly attaches active saved handles; merely typing `@Name` in an API scene does not attach it. The browser does auto-attach typed names. If a reference is already in the scene, adding its handle again keeps its existing snapshot. To apply a new library version, remove the old scene reference in one PATCH, then attach it in the next PATCH. `restore_named_references` restores missing inputs from that scene snapshot. These operations do not submit generations.

### Complete agent workflow

Run from the app directory or add it to Python’s import path. This example prepares a scene only, leaving generation to a separate explicitly authorized call.

```python
from agent_client import StudioClient

client = StudioClient()
capabilities = client.request("schema")
account = client.request("account")

# Upload local images; no provider upload/generation occurs here.
front = client.upload("/absolute/path/SampleHero-front.png")
opening = client.upload("/absolute/path/studio-opening.png")
ending = client.upload("/absolute/path/studio-ending.png")

reference = client.request("references", "POST", {
    "title": "SampleHero", "handle": "SampleHero",
    "description": "A fictional gardener wearing a green raincoat and gray boots.",
    "category": "Character", "images": [{"asset_id": front["id"]}],
    "voice": "rex",  # Confirm the preset in capabilities["voices"].
})
scene = client.create_scene("SampleHero intro", {
    "duration": 12, "resolution": "720p",
    "prompt": '@SampleHero waves and says: “Welcome to the garden. I’m SampleHero.” No music.',
    "first": {"asset_id": opening["id"]},
    "last": {"asset_id": ending["id"]},
}, named_references=[reference["handle"]])
validation = client.validate(scene)
if not validation["valid"]:
    raise ValueError(validation["errors"])
client.show_in_browser(scene)  # Human can now review the same persisted scene.
```

A handle must be unique, ignoring capitalization, including archived records. For an existing SampleHero, fetch the reference list and reuse it instead of creating a duplicate. Prefer recorded scene snapshots when reproducing an earlier scene. Images + descriptions guide identity but cannot guarantee identical output.

After applying a current guide-backed preparation and obtaining approval for this exact scene and revision:

```python
# Set approved=True only after obtaining human authorization.
job = client.generate(scene, approved=True,
                      idempotency_key="foundation-intro-approved-001")
result = client.wait_for_job(job["id"])
if result["status"] == "done":
    client.download(job["id"], "/absolute/path/SampleHero-intro.mp4")
else:
    print(result.get("message", "Render did not complete."))
```

For practice, use the isolated mock server and complete its mock login before mock generation. If a live account is not connected, `POST account/login` starts device login; poll `account` and hand its verification link/code to the human. Do not call login again while the current flow is waiting.

### Storyboarding, reuse and shared review

```python
# Add a keyframe at 3 seconds; fetch the latest scene before editing.
scene = client.request("scenes/" + scene["id"])
scene = client.edit_scene(scene, {
    "keys": [{"source": {"asset_id": opening["id"]}, "slot": 9}]
})

# Reorder reference inputs, preserving IDs and named snapshots.
scene = client.edit_scene(scene, {"refs": list(reversed(scene["scene"]["refs"]))})

# Restore attachments removed from a named scene snapshot.
scene = client.edit_scene(scene, restore_named_references=["SampleHero"])

# Prepare the next scene from a completed history record.
next_scene = client.request("jobs/" + job["id"] + "/reuse", "POST",
                            {"title": "SampleHero scene 2"})
next_scene = client.edit_scene(next_scene, {"prompt": "@SampleHero turns toward the window."})
client.show_in_browser(next_scene)
```

The browser has **Scenes**, **New scene**, a scene title and an autosave indicator. Initial migration preserves the existing valid browser draft as the current shared scene. Agent edits/selection appear automatically when the browser has no pending local edit. Browser autosave uses the same expected-revision protection as the API.

When HTTP 409 reports a stale edit, fetch again and merge deliberately; do not blindly overwrite. A browser conflict preserves its local draft, offering **Save draft as copy** or explicit discard/reload. Multiple agents and browser tabs must coordinate revisions. Keep one server process per state directory. Scene selection is shared, while unsaved local edits remain in that browser until resolved.

Mock and live jobs have separate histories; scenes, uploads and reference records share a state directory. Use isolated `--state-dir` for test runs. Mock mode never proves real output quality or billing.

### Prevent duplicate generations

Video generation requires an 8–100 character `Idempotency-Key` made of ASCII letters, digits, underscores or hyphens. A repeated key with the same scene ID and approved revision returns the original job, including after restart. It does not submit a second provider request. Reusing the key for another scene/revision returns 409. Fetch jobs to recover after a lost response; do not invent a new key merely because a client timed out.

If an error is repairable and the human authorizes another attempt, edit the scene and use a new key for that new request. A saved request ID should be resumed with `jobs/{id}/resume` rather than generated again. This endpoint resumes polling only, including after a server restart. No automatic generation retries exist.

New live requests through the original diagnostic are blocked in Imagine Studio; use guide-backed preparation and generation in Image Studio. Local mock diagnostics and existing request replays require explicit approval and an 8–100 character `Idempotency-Key` (letters, digits, underscore or hyphen), including the browser `/tester` page. Identical retries return the original request ID and stored result; changed settings with the same key return 409. Poll `GET image-test/{id}`. Interrupted requests become errors on restart and are never automatically submitted again. Studio stores these records locally; the standalone diagnostic harness deduplicates within its process only. The agent prompt limit is the configured limit (currently 4,096); the tester page remains limited to 1,000 characters. This API cannot cancel a provider render, guarantee usage-pool selection, upload a custom video voice, sync the Grok.com reference library or bypass external sign-in/consent.

### Command-line interface

`agent_client.py` can call any documented route. Use a JSON body file to avoid shell quoting errors:

```sh
.venv/bin/python agent_client.py assets --upload /absolute/path/view.png
.venv/bin/python agent_client.py scenes --method POST --data-file /absolute/path/scene.json
.venv/bin/python agent_client.py scenes/SCENE_ID/validate --method POST
.venv/bin/python agent_client.py jobs/JOB_ID
.venv/bin/python agent_client.py jobs/JOB_ID/download --output /absolute/path/result.mp4
```

For approved generation, supply `--method POST`, a JSON file containing the reviewed `expected_revision` and `approved: true`, and `--idempotency-key`. Local bearer credentials are read from the private token file, not passed on the command line. Use `--base-url` and `--token-file` for an isolated mock server.

### Instructions to give an AI agent

> Use Imagine Studio’s local agent API through agent_client.py. Read schema, account state, references and the current workspace before editing. Use AGENT_API.md for endpoints. The matching model guide in [docs/prompting-guides/](../docs/prompting-guides/) is required reading before writing any video or image prompt. Direct authoring is preferred for agents. Read the validation warnings and fix them before asking for generation authorization. Create/edit saved scenes with expected revisions; attach reference handles explicitly. Validate the expanded request and show the scene in the browser for review when appropriate. Never reveal local or provider credentials. Generate only after explicit human approval of the concrete settings, with approved=true and a persistent idempotency key. Fetch the original job after a timeout; resume saved polling instead of creating a duplicate. Report the actual outcome and limitations, not assumed success.


## Prompt writing and validation

### Guide-backed AI prompt preparation

Video prompts may be written directly. Image prompts need current AI preparation or a current recorded manual review. Generation authorization is separate from prompt review. The writer receives the complete guide for the actual target model, independent of the selected writing connection. Preparation authorization and media-render authorization are separate. Mock placeholders are clearly labeled and contact no writer.

| Method | Path | Action |
|---|---|---|
| GET | `prompting/schema` | Discover writers, guide mapping and preparation contract |
| GET | `prompting/{image|video}/{id}` | Current readiness, latest job and applied provenance |
| POST | `prompting/{image|video}/{id}` | Prepare with `expected_revision`, `approved: true`, optional `provider`, `brief`, `instruction`, `force`; requires a unique `Idempotency-Key` |
| GET | `prompting/jobs/{id}` | Poll job, inspect prompt/notes, guide versions and available cache usage |
| POST | `prompting/{image|video}/{id}/apply` | Use reviewed result with `job_id`, job `expected_revision`, `expected_media_revision` and optional edited `prompt`; no render |
| POST | `filmmaking/assets/{id}/prompt-draft` | Build a workshop brief or reuse current prepared text; `expected_revision`, optional `model`/`brief`; no writer or render |

After authorization to use the writing connection, prepare the scene with:

```python
preparation = client.request("prompting/video/" + scene["id"], "POST", {
    "expected_revision": scene["revision"], "approved": True, "provider": "codex",
}, idempotency_key="example-prompt-preparation-001")
# Poll prompting/jobs/{id} until done/error, then inspect result.prompt and notes.
```

After reviewing the completed prompt, apply it and refresh the shared scene:

```python
used = client.request("prompting/video/" + scene["id"] + "/apply", "POST", {
    "job_id": preparation["id"], "expected_revision": preparation["revision"],
    "expected_media_revision": scene["revision"],
})
scene = used["draft"]
validation = client.validate(scene)
client.show_in_browser(scene)
```

Use the final polled job revision. Notes can identify creative conflicts that still need human judgment. Applying checks current source/guide versions and preserves newer edits on conflict. For images, changed prompt/model/settings/references or relevant script/style require fresh AI preparation or a current manual prompt review. Agents may record direct image authoring through `review-prompt` with `authored_by: "agent"`. For videos, AI preparation is optional for humans and agents: see [Agent direct authoring (video)](#agent-direct-authoring-video). `prompt_preparation_current` is informational for videos; stale preparation does not block a manual direction. Missing inputs, invalid reference tags, timing conflicts and current unresolved preparation conflicts still block generation. Human generation authorization and the live-generation lock remain required. Existing opening-frame/video-direction and creative proposal application also record preparation provenance.

Writing usage stores input/output/cached-input/cache-write counts when the transport reports them; null means unknown. Native Codex turns use a stable prefix without unsupported cache parameters. Grok uses its supported stable cache-routing header. No automatic retry/prewarming is made. The old `image-test` route permits local mocks or existing diagnostic replay; new live images must use Image Studio with current AI preparation or a current manual prompt review. Direct agent image prompts must follow the matching Grok Imagine Image 2.0 or GPT Image 2.0/2.5 guide in `docs/prompting-guides/`.

### Prompt writer order and scene continuity

For `POST prompting/image/{id}` and `POST prompting/video/{id}`, omit `provider` to try ChatGPT/Codex first for every media model. A ChatGPT sign-in, availability, usage/rate-limit, timeout or upstream failure permits one Grok fallback attempt. Explicit `provider: "codex"` or `provider: "grok"` is honored without fallback. Validation errors, invalid writer output and live locks do not trigger fallback. The preparation dialog offers the automatic mode plus either explicit writer.

Job JSON exposes `provider` (actual writer), `provider_requested` (`auto` or `explicit`), `fallback_from` and `fallback_reason`. Applied preparation provenance and the dialog's evidence also retain these fields. Fallback never generates media or retries the same writer.

For linked video shots, `creative_context.previous_shot` contains the previous active shot's title, final saved prompt and story direction. It uses the next-lower `shot_order` in the same production, episode and script scene. `scene_standing_holds`, when set, contains that script scene's durable holds. Changes to either source invalidate preparation.

Edit standing holds with the existing revisioned `PUT stories/episodes/{id}` route. Include the existing scene IDs and the optional `standing_holds` string (up to 10,000 characters) in `scenes`, with `expected_revision`. Omitted holds on an existing scene are preserved; an empty string clears them. No new media or writer request is involved.

### Agent direct authoring (video)

Agents may skip the built-in AI writer and submit a direction directly. Direct authoring is preferred for agents. Read and follow [the runtime video guide](../docs/prompting-guides/Grok_Imagine_Prompting_Guide.md) first. The same request validation and prompt checks apply to humans, agents and the built-in writer. Validation returns structured `prompt_issues` and warning messages in `warnings`. Fix the warnings before asking for generation authorization.

The non-blocking warning codes are `voice_tag_repeated` (voice tags belong once in the compiler header), `voice_name_in_body` (use speaker names instead of attached preset names), and `character_without_direction` (mention each image-backed character with an action or hold). Character/asset names and handles are exempt from preset-name warnings; voice-only characters need no visual direction. Warnings do not block generation; errors still do. Human generation authorization (`approved: true`) and an idempotency key are still required.

### Model capabilities

New generation supports only `grok-imagine-video-1.5` and `grok-imagine-video-1.5-lite`. GET `schema` exposes `model_capabilities`; generation validation rejects retired model IDs while saved historical scenes/results stay readable. Video 1.5 allows 14 reference images, three preset voices, four interior keyframes, first/last frames and combined conditioning. Lite allows text or one starting image and audio control, with 1080p upscaled from 720p. Advanced inputs require 1.5 and at most 720p. Both models add `21:9` / `5:2`. Ordinary image-to-video follows the source ratio. Reference workflows validate the FULL expanded prompt against `prompt_limit_bytes` (4096 UTF-8 bytes), rather than character count; validation returns `expanded_prompt_bytes` alongside characters. Preset IDs are case insensitive; arbitrary keyframe seconds normalize to the nearest third-second slot, rejecting rounded collisions and endpoints.

Image settings add `n: 1|2|4`; `image-studio/schema.models` publishes `counts` by connection (native Codex only 1). Grok Image 2.0 adds `1.5k` and submits deferred generation/edits with URL output. Jobs persist the provider request ID before polling. POST `image-studio/jobs/{id}/resume` recovers the same request using GET only; no new idempotency key or generation is submitted. GET `image-studio/jobs/{id}/outputs/{asset_id}` downloads the specific cached candidate. Old `/download` retains first-candidate behavior. Every candidate has independent approval and refinement/transfer IDs.

Image/video jobs retain `requested_model`, nullable `returned_model` and `model_identity`. The returned field is populated only when the provider actually reports it; successful completion and native defaults do not prove model identity. Older history can lack these fields. OpenAI routes/billing remain unchanged; no new key provisioning, fallback or live provider test occurred.

### Action order and shot order

All video authoring uses one coherent dramatic beat per shot and lists actions, speech, gaze changes and reactions in chronological order without timestamp blocks. Duration remains a generation setting. Evidence timestamps and actual keyframe controls are unchanged. The active focused guide is `docs/prompting-guides/Grok_Imagine_Prompting_Guide.md`; the legacy reference handbook is not loaded.

`PUT productions/shots/{id}` accepts revision-protected `shot_order` (integer 0–10000) and `archived` (boolean). Archive is reversible and preserves media and selected takes. Archived shots remain readable by ID and versions; they are omitted from the active outline. Restoring uses the current revision and `archived:false`.


## Images and reusable media

### Image Studio

The same token and browser bridge now expose `/agent/v1/image-studio/*`. Read the [Image Studio Guide](IMAGE_STUDIO_GUIDE.md#agent-interface) for routes, schema, examples, approval and video transfer. The generated contract publishes the Image Studio routes. Dispatcher/OpenAPI drift tests check route and method coverage; consult the workflow guides and runtime schema for service-specific constraints. `StudioClient` adds `create_image`, `validate_image`, `generate_image`, `wait_for_image`, `resume_image` and `download_image_candidate`. Image drafts use immutable named snapshots, selected image views and optimistic revisions. Image submission requires separate human authorization and an idempotency key; candidate appearance approval is required before video use. No live image editing test has been made for this feature.

### OpenAI image providers

Image draft `settings.model` selects `grok-imagine-image-2.0`, `gpt-image-2`, `gpt-image-2.5-flare` or `gpt-image-2.5-sunburst`. Discover each model's permitted controls and billing through `GET /agent/v1/image-studio/schema`; do not reuse Grok resolution values for OpenAI. Model changes retain attached asset snapshots. Native `gpt-image-2` accepts only `auto` quality/resolution.

`GET /agent/v1/image-studio/openai-account` returns cached safe connection status. `POST /agent/v1/image-studio/openai-account/refresh` refreshes it without generating. Credentials remain on the server; agents never supply or retrieve provider keys. Generation uses the existing approved, revision-checked and idempotent image draft endpoint. The chosen model determines billing and there is no fallback. Mock mode covers all providers without provider calls.

### Reuse clipboard images and captured video frames

An agent uploads an image with the existing `POST /assets` route; clipboard access itself belongs to the caller. Both uploaded images and captured frames can be placed with the same route. These operations never generate media or charge provider usage.

```python
# Completed job only. Server decodes the timestamp from its recorded, cached video.
asset = client.request("/jobs/VIDEO_JOB_ID/capture-frame", method="POST",
                       data={"timestamp_s": 1.0})
# New scene defaults to Video 1.5, 5 seconds, 16:9, 480p, empty prompt.
scene = client.request(f"/assets/{asset['id']}/place", method="POST",
                       data={"new_scene": True, "target": "first",
                             "title": "Next scene"})
# Existing scene: obtain its latest revision first.
scene = client.request(f"/assets/{asset['id']}/place", method="POST",
                       data={"scene_id": scene["id"],
                             "expected_revision": scene["revision"],
                             "target": "keyframe", "slot": 3})  # 1 second
```

Targets: `first`, `last`, `reference`, `keyframe`. A keyframe slot is integer seconds × 3, strictly between the endpoints; at most four distinct slots. Video 1.5 references allow 14 images; Lite accepts a first image only. `replace: true` explicitly permits replacing an occupied frame/keyframe. Insertion retags existing IMAGE mentions automatically. Existing scene script links remain attached; newly created scenes start without a story link. Placement does not switch the agent workspace; use `POST /workspace` when desired.

`capture-frame` accepts finite `timestamp_s` from zero through the actual video duration. It accepts an optional `data_url` for the browser's displayed canvas image; this is caller-supplied image data, not verification that its pixels match the timestamp. Without it, ffmpeg and ffprobe must be on PATH. The capture only accesses the selected completed job's recorded video; arbitrary URLs are rejected. Assets retain `source_video_job_id`, `frame_seconds` and `capture_method` provenance. Browser capture is exact to the displayed decoded frame; server extraction selects a frame at/near the requested time (the end timestamp maps slightly before EOF).

Model restrictions, revision conflicts, occupied slots, missing dependencies and invalid timestamps return structured errors. Invalid placement creates no scene. Advanced reference placement changes 1080p to 720p. No implicit generation or retry occurs.

### Approved image to named reference

`POST /image-studio/jobs/{id}/reference-suggestion` with `asset_id` returns editable `title`, `handle`, `description`, `category`, `voice`, `images` and a suggestion note. Optional `category` is Location (default), Character or Prop. Suggestions are derived locally from the immutable job prompt; no provider calls.

`POST /image-studio/jobs/{id}/reference` with `asset_id` saves a named reference. Override `title`, `handle`, `description`, `category`, `voice` or `images` as needed; omitted fields use current suggestions. The output must still be approved in both the job and library. If you specify `images`, retain the original output as `{"asset_id":"OUTPUT_ID"}`. The returned record is reusable through existing named-reference attachment routes. No generation is triggered.

The image job's `transfer` route also accepts `target: "reference"` for direct scene placement with `scene_id` and `expected_revision`.

### Edit an attached Image Studio asset

Edit the shared reference through the existing reference update route, then POST `/agent/v1/image-studio/drafts/{id}/refresh-reference` with `{"expected_revision": 3, "reference_id": "the-reference-id"}` using the current draft revision. The response is the updated draft. This explicitly replaces only that binding snapshot, renames its prompt mentions if the handle changed, and preserves selected views by image-source identity. Removed views become deselected and validation requires review. Other drafts and generation history retain their snapshots. Stale revisions fail without changing the draft. The browser's **Your Assets → Edit** performs these two steps. Prompt autocomplete uses the saved reference library and existing attach operations; it makes no provider call.

Approved-image transfer also supports new scenes: POST `/agent/v1/image-studio/jobs/{id}/transfer` with `asset_id`, `new_scene: true`, `title`, and `target` (`first`, `last`, `reference`, `keyframe`). Keyframes require `slot` (seconds × 3). Omit `scene_id` and `expected_revision` for new scenes. Invalid placement fails before creating a scene; success returns the saved new scene. Existing scenes still require their ID and revision.

Image draft creation and updates automatically attach missing saved references named by exact, case-insensitive `@Handle` mentions in `settings.prompt`. Explicit `named_references` remains supported. Existing snapshots and view selections are preserved; automatic bindings select view 0 and respect the combined five-source limit. Unknown, archived, image-less or over-limit mentions remain in the prompt and fail validation with an actionable message. Draft saves still succeed so the prompt is preserved.

The human UI no longer shows a usage checkbox for subscription operations; clicking Generate/Send authorizes that request. The API transport retains `approved: true` for explicit submissions, idempotency and revision checks. OpenAI API image generation still requires a checked charges checkbox in the UI. Image-output review approval is separate and unchanged.

Script import preview now returns `sections` with `type` (`scene`, `notes`, `other`), title and text; `scenes` remains for compatibility. Review and POST `/agent/v1/stories/episodes/{id}/apply-import` with `expected_revision` and `sections`. Scene sections replace the scene list (unique matching titles retain IDs); supporting sections append labeled text to episode notes. With no scenes, existing scenes stay. Invalid types, notes limits or stale revisions reject the import atomically.


## Stories, productions and shot planning

### Story Studio

Story routes use the same local bearer credential and versioned base URL. `GET stories/schema` returns limits, import formats and verified subscription writing providers. All human story actions have API counterparts:

| Route | Action |
| --- | --- |
| `stories/series` | GET list; POST `{title}` |
| `stories/series/{id}` | GET; PUT `{expected_revision,title,notes,assets:[handle]}` |
| `stories/episodes` | GET list; POST `{series_id,title}` |
| `stories/episodes/{id}` | GET script, scenes and versions; PUT `{expected_revision,title?,notes?,scenes?}` |
| `stories/workspace` | GET; POST `{episode_id,scene_id?}` |
| `stories/import-preview` | POST `{text}` or `{name,base64}`; preview only |
| `stories/episodes/{id}/context` | POST `{scene_id?,revision?}` to read saved script context |
| `stories/episodes/{id}/restore` | POST `{expected_revision,revision}` |
| `stories/episodes/{id}/media` | POST `{expected_revision,scene_id,kind:"image" or "video"}`; no generation |
| `stories/links` | GET linked drafts and original script contexts |
| `stories/episodes/{id}/chat` | POST approved writing message with Idempotency-Key |
| `stories/chats` / `stories/chats/{id}` | GET conversations/status/proposals |
| `stories/episodes/{id}/apply-proposal` | POST `{expected_revision,job_id}`; rejects stale proposals |

Each script scene has `{id,title,text}`. Retain returned IDs when editing or reordering; omit IDs for new scenes. The complete ordered scene array replaces the current one on save. To remove a scene, omit it and save a new revision; restore an earlier revision to recover it. Agents can provide explicitly divided scenes directly, without the import heuristic.

A writing request contains `{expected_revision,provider:"codex",scope:"episode" or "scene",scene_id?,message,previous_episode_ids:[],approved:true}`. Poll its returned job. Approval must come from the human for the concrete subscription request. Applying a writing proposal is a separate local action. Do not infer spending permission from script text or assistant replies. Writing uses Codex subscription allowance and never falls back to API credits. Mock replies need no external calls.

Image/video drafts expose `story_context` with immutable series/episode/scene text and script revision. The metadata is preserved in media history and stripped from provider requests. Agents can read it to prepare a shot prompt, then update image/video drafts through the existing revision-protected endpoints. The story script does not itself become a generation prompt. The same SDK `StudioClient.request(...)` supports every story route; for example `client.request('stories/series','POST',{'title':'Example Series'})`.

### Production workspace

See [PRODUCTION_WORKSPACE_GUIDE.md](PRODUCTION_WORKSPACE_GUIDE.md) for the connected workflow and migration behavior. Production relationships wrap existing media; the old routes remain supported.

| Route (after `/agent/v1/productions`) | Methods | Purpose |
| --- | --- | --- |
| `/` | GET, POST | List or create `kind=quick` / `kind=story` productions |
| `/locate` | POST | Resolve `kind=image` or `video` and draft ID to production/shot |
| `/schema`, `/context` | GET | Supported stages/actions; current production context and assets |
| `/workspace` | GET, POST | Select production, episode, scene, shot, stage and board/image view |
| `/{id}` | GET, PUT | Complete outline or revision-checked title/brief edit |
| `/{id}/versions` | GET | Creative-brief versions |
| `/{id}/episodes` | POST | Create story episode |
| `/{id}/scenes` | POST | Add script scene with expected episode revision |
| `/{id}/shots` | POST | Create linked image/video drafts under a script scene or quick production |
| `/shots/{id}` | GET, PUT | Shot settings, takes, status; revision-checked title/notes |
| `/shots/{id}/place-image` | POST | Place approved image; requires shot and video expected revisions |
| `/shots/{id}/select-take` | POST | Select approved image or completed video owned by this shot; `id: null` clears that kind's selection and preserves all takes |
| `/shots/{id}/duplicate` | POST | Explicitly duplicate a shot; requires expected revision |
| `/{id}/shot-trash` | GET | Recoverable archived shots; restore with revision-checked shot PUT |
| `/{id}/image-branches` | GET | Verified legacy refinement branches without separate video, direction or edit work |
| `/shots/{id}/merge-image-branch` | POST | Explicitly move a verified branch into image versions; requires target and branch revisions; preserves media |
| `/shots/{id}/refresh-context` | POST | Update script snapshots explicitly, preserving all generation settings |

`stage` is `develop`, `script`, `storyboard`, `generate`, or `edit`. `board_view` is `board` or `image`. A shot selection also selects its linked image/video drafts for the browser. New jobs include their originating video draft ID in local metadata; it is removed before calling the provider. Old jobs without an ID are associated only by an exact full settings snapshot that identifies a unique saved video draft. Unmatched histories remain in Existing work.

Image refinement/reuse creates a version in the same shot. Supply `parent_draft_id` when explicitly creating an image version. `GET image-studio/drafts/{id}/versions` lists its family. Refinements send the base image by default; attached identity snapshots remain available with views deselected. `POST image-studio/drafts/{id}/review-prompt` with `{expected_revision, reviewed: true, authored_by: "agent"}` records review of an agent-written image prompt without calling the AI writer. `authored_by` accepts `"agent"` or `"human"`; it is optional and defaults to `"human"` for existing clients and the human UI. Read the matching image model guide first. The draft stores `manual_prompt_review` with revision, author and review time; validation and generation jobs expose `prompt_review_provenance`, and generated-image history shows the author. This is author metadata, not human generation authorization. Changes to prompt, references, aspect ratio, edit region or relevant creative context invalidate the review. Saving only model, quality, resolution or candidate count preserves it. Prompt limits, references, model capabilities, separate human generation authorization (`approved: true`), idempotency keys and candidate approval/review are unchanged. The legacy `image-test` route is unchanged.

`POST /productions/recent` returns `{items, total, production_total, offset, limit, has_more}`. Optional `projects_only: true` restricts results and counts to Story / Series and explicit Quick Video projects. Items publish `is_project` and `project_label` (`Quick Video` or null), as well as media classification. The default page size is 10, the maximum is 100, and offset starts at 0. Items are sorted newest first by `last_updated` (Unix seconds) and include `item_type` (`video`, `image`, `script`, `story`). The original unpaginated list route remains available for existing agents.

### Creative proposals and asset tools

All routes use the existing local bearer token (or same-origin browser bridge). No provider token is returned.

| Route | Purpose |
| --- | --- |
| `GET creative/schema` | Provider labels, scopes and supported action catalog |
| `POST creative/context` | Exact production context; no provider call |
| `POST creative/messages` | One subscription reply; requires `approved=true` and `Idempotency-Key` |
| `GET creative/messages` / `GET creative/messages/{id}` | Activity/history and reply polling |
| `POST creative/messages/{id}/apply` / `undo` | Revision-checked atomic changes or restoration; no generation |
| `GET asset-studio/schema` / `GET asset-studio` | Canonical asset discovery and limits |
| `POST asset-studio`, `GET/PUT asset-studio/{id}` | Create/read/edit assets; edit requires `expected_revision` |
| `GET asset-studio/{id}/versions` | Asset history |
| `POST asset-studio/{id}/restore` | Restore `revision` as a new version, with `expected_revision` |
| `POST asset-studio/{id}/archive` | Archive or restore, with `expected_revision` and `archived` |
| `POST asset-studio/{id}/develop` | Prepare an image draft, optional `prompt`; no generation |
| `POST asset-studio/{id}/adopt` | Add approved `asset_id` or replace `replace_index`, with `expected_revision` |
| `POST asset-studio/development/lookup` | Find asset linked to `draft_id` |
| `GET precision/schema` | Local operations, limits and region behavior |
| `POST precision/edits` | Save local operations as a new image job; review/approve via normal image job route |
| `POST precision/refine` | Prepare AI region refinement; no generation |

Assistant selection fields: `production_id`, optional `episode_id`, `scene_id`, `shot_id`, `scope` (`production`, `episode`, `scene`, `shot`), `stage` (`develop`, `script`, `storyboard`, `generate`, `edit`). Send `provider=codex` or `grok`, `message`, and `approved=true`. Grok `model` is optional/configurable; no provider fallback. Fetch the job until `done` or `error`, then review its `actions`. Never resubmit automatically after a timeout. `apply` and `undo` are idempotent for a completed job; a revision conflict preserves later changes.

Assistant actions are structured proposals, not arbitrary endpoints or executable code. Their values pass the same validation as the human editors. Asset mentions in proposed media prompts are attached automatically when available; canonical version changes invalidate stale proposals. Script changes leave existing media script snapshots intact and mark affected shots for explicit context review. Generation is available separately through the existing image/video APIs and is never implied by creative content.

Local edit body: `asset_id`, optional `draft_id` and `reference_id`, and an `operations` array. Operations are `{kind:crop, region:{x,y,width,height}}`, `{kind:rotate, degrees:90|180|270}`, `{kind:resize, width:int,height:int}`, or `{kind:paint|erase, points:[[x,y],...], width:0.01, color:'#ffffff'}`. Coordinates are normalized; brush width is a fraction of the smaller edge. The output is an unapproved image job, with its original asset ID and operations retained.

AI preparation body: `asset_id`, optional `draft_id`, `expected_revision`, `title`, normalized `region`, and ordinary image `settings`. Editing an existing draft requires its revision. `edit_region` is also a supported ImageSettings field; it requires a local `base` image. Image 2.5 sends a PNG mask on the edits endpoint; subscription transports receive prompt guidance. Keep the normal API charge approval before actual generation.

Python helpers: `creative_context`, `ask_collaborator`, `apply_creative_proposal`, `undo_creative_proposal`, `develop_asset`, `precision_edit`. All other routes remain available through `StudioClient.request`.

### Connected filmmaking tools

`GET filmmaking/schema` discovers providers, tools and plan limits. All routes use the existing workspace bearer token. Production IDs are used in world paths and shot IDs in direction paths; returned world/direction record IDs are distinct storage identities.

| Route | Operation |
| --- | --- |
| `GET/PUT filmmaking/worlds/{production_id}` | Read/save story; save requires `expected_revision` (0 initially), `answers` and optional structured `guide` |
| `POST filmmaking/worlds/{production_id}/plan` | One writing request with `expected_revision`, `provider: codex|grok`, `approved:true` and Idempotency-Key |
| `POST filmmaking/worlds/{production_id}/import-preview` | Local review-only extraction: `name` + `base64` (TXT/MD/Fountain/DOCX ≤2 MB), or `text` (≤60,000 characters); returns `answers`, structured `guide` and extraction notes; writes nothing |
| `GET filmmaking/worlds/{production_id}/jobs` | Mode-specific plan history |
| `GET filmmaking/worlds/{production_id}/assets` | Prepared asset views with candidate and approval state |
| `GET/PUT filmmaking/jobs/{id}` | Poll plan or save reviewed `result` with job `expected_revision` |
| `POST filmmaking/jobs/{id}/fork` | Source job `expected_revision`; copies a completed script into a new editable draft using current world/production revisions; retains earlier visual work |
| `POST filmmaking/jobs/{id}/apply` | Job `expected_revision`, optional reviewed `result`, `image_model: gpt-image-2|grok-imagine-image-2.0`; creates drafts locally |
| `POST filmmaking/assets/{id}/adopt` | World-asset `expected_revision`, approved own candidate `asset_id`; creates/extends canonical identity |
| `GET/POST filmmaking/worlds/{production_id}/workshop` | Read/start visual studio; POST takes `job_id`, job `expected_revision` and subscription `model`; prepares drafts locally |
| `POST filmmaking/worlds/{production_id}/reference` | Upload local `name` + image `data_url`; returns `asset` and extracted `palette` |
| `POST filmmaking/worlds/{production_id}/generate` | Explicit sequential batch: `job_id`, subscription `model`, `approved:true`, `requests:[{view_id,expected_revision,prompt?}]` and Idempotency-Key |
| `GET filmmaking/worlds/{production_id}/bible.pdf` | Illustrated local PDF of reviewed story and confirmed references |
| `PUT filmmaking/entities/{id}` | Save `profile`/`description` with entity `expected_revision` |
| `POST filmmaking/entities/{id}/views` | Add 1–8 named sheets/angles with entity `expected_revision`, subscription `model`, `views:[{label,details?}]` |
| `GET filmmaking/entities/{id}/workshop` | Read the owning workshop, including candidate/view revisions; no mutation |
| `POST filmmaking/entities/{id}/clear-approval` | Clear main identity with entity `expected_revision` while idle; saved uses/history retained |
| `PUT filmmaking/assets/{id}` | Rename optional sheet/coverage with view `expected_revision`, `title` (1–80 chars) |
| `POST filmmaking/assets/{id}/clear-approval` | Clear optional sheet/coverage selection with view `expected_revision` while idle |
| `POST filmmaking/assets/{id}/return-image` | View `expected_revision`, `job_id`, `asset_id`; adopt approved edit from this view, otherwise return unchanged workshop. A return of the already selected image is idempotent |
| `POST filmmaking/assets/{id}/attempts` | View `expected_revision`, nonempty `attempt_ids` (at most 1,000), `action: dismiss\|restore`; returns updated view, not workshop |
| `POST filmmaking/entities/{id}/upload` | Explicitly approve a finished local `asset_id` with entity `expected_revision` (inspiration uploads use `profile.reference_ids`) |
| `POST filmmaking/entities/{id}/clear-approval` | Entity `expected_revision`; clears current entity/view selections, keeps images and historical work; returns workshop snapshot |
| `POST filmmaking/assets/{id}/confirm` | Confirm own candidate `asset_id` with view `expected_revision` and `approved:true`; connects canonical identity to shots |
| `POST filmmaking/assets/{id}/review` | View `expected_revision`, asset `expected_review_revision` (0 initially), own candidate `asset_id`, `action: reject\|trash\|restore`, optional `reason` (500 chars); no generation |
| `POST filmmaking/renders/{id}/cancel` | Stop unsent batch requests; retains current/completed requests |
| `GET/PUT filmmaking/shots/{shot_id}` | Read/save staging with `expected_revision` (0 initially) |
| `GET filmmaking/presets` | Shared UI camera/movement catalog, defaults, frame sizes and local renderer availability |
| `POST filmmaking/shots/{shot_id}/reference.png` | Only saved staging `expected_revision`; returns binary `image/png`, never generates or changes saved data |
| `POST filmmaking/shots/{shot_id}/compose` | Staging `expected_revision`, `expected_image_revision`, `prompt`, PNG `data_url`; transfers to linked image draft |
| `POST filmmaking/shots/{shot_id}/movement` | Video draft `expected_revision`, `prompt`; appends camera direction |

Reference review returns the workshop snapshot. Rejected and trashed candidates are excluded from the shared media library and cannot be approved or reused until restored. Trash keeps cached files; restoring from Trash restores the previous review state, while restoring a rejected candidate returns it to review without approving it. For a main identity, Reject is blocked while an active identity approval still uses it: clear the entity approval first. After clearing approval, Reject can preserve saved references, drafts and immutable snapshots; it returns `review_preserved: {dependencies, count}` when such uses remain. Trash remains blocked by saved dependencies and returns HTTP 200 with `review_blocked: {dependencies, count}` without changing anything. Optional outfit/angle review is scoped to its view, preserves other uses and clears that view’s selection. Clients must inspect `review_blocked` and `review_preserved`, and fetch review revisions from that view’s outputs (not a different library record). Normal Image Studio unapproval also protects images in use. Stale revisions fail with HTTP 409.

Questionnaire fields: `idea`, `genre`, `tone`, `theme`, `audience`, `duration`, `characters`, `locations`, `plot`, `style`, `rules`. The full strict plan schema is published in OpenAPI. Plan bounds are 8 scenes, 20 shots, 12 assets and 4 views per asset. Applying adds a new episode for a story; it preserves existing scripts and media. Changed world/brief revisions block stale application. Applied jobs are idempotent.

Staging is `{camera:{yaw,elevation,distance,target_x,target_y,target_z,lens},subjects:[{name,asset_id:null|string,x,z,rotation,pose,arms,head}],ratio,environment,style}`. Poses: `stand`, `walk`, `sit`, `crouch`, `reach`, `fight`; 1–4 subjects; ratios `16:9`, `9:16`, `1:1`. The PNG must decode to at most 3 MB and 4 million pixels. Source limits and character scope are validated. Repeated transfer replaces the prior tool composition reference. Movement text is limited to 1500 characters and the combined video prompt to 3500.

Only plan building, explicit workshop generation and the existing generation endpoints contact providers. They require human authorization of concrete requests. Save/apply/adopt/staging/compose/movement are local operations; no generation is implicit. Both subscription providers use existing transports without automatic fallback or retry. See [the filmmaking guide](FILMMAKING_TOOLS_GUIDE.md).

#### Local Camera Control reference export

`GET filmmaking/presets` publishes the same seven camera presets, fourteen movement presets, default staging and export dimensions used by the UI. Each camera preset has a stable `id`, display `name`, partial `patch` and complete resolved `camera`. Movements retain their `id`, `name`, `group`, `effect` and editable `prompt`; apply a reviewed prompt through the existing movement route with the **video draft revision**. The camera/export revision is a separate **saved shot staging revision**; composition transfer also needs the current **image draft revision**.

Save staging first, then POST `filmmaking/shots/{id}/reference.png` with exactly `{expected_revision: <staging revision>}`. It returns raw PNG bytes with no approval/idempotency requirement because it is a local render, not provider generation. It rejects inline staging, URLs, executable paths and workspace selectors. A stale revision returns 409; missing staging returns 400; an absent/foreign-workspace shot returns 404. Rendering never uploads the reference or writes creative records. A successful export can be downloaded or transferred through the existing revision-checked compose route:

```python
catalog = client.camera_presets()
direction = client.shot_staging(shot_id)
staging = catalog['defaults']
staging['camera'] = next(p['camera'] for p in catalog['camera'] if p['id'] == 'wide')
direction = client.save_shot_staging(direction, staging)
png = client.camera_reference(direction)  # bytes; does not generate an image
shot = client.request('productions/shots/' + shot_id)
result = client.compose_shot(direction, shot['image']['revision'], 'Use this composition.', png)
```

Browser and server export through the shared `drawReference`/`drawStage` implementation in `ui/filmmaking-model.ts`. The server bundles the same module as `static/camera-renderer.cjs` and runs it in Node with the pinned `@napi-rs/canvas` Skia binding; it never discovers or launches Brave, Chrome, Chromium or any desktop browser. Seven shared presets and all movement text come from `static/camera-presets.json`, consumed by both runtimes. Landscape exports are 1280×720, portrait 720×1280, square 1280×1280. Exported references omit subject-name labels and framing guides, matching the UI PNG; the floor grid/mannequins remain. Asset IDs represent saved character references, never downloaded image URLs. Export draws saved mannequin geometry without loading character media, so archiving a character after saving staging does not block the same local export the UI supports; new staging saves and composition transfer retain their asset validations.

Requires Node.js 22+ and `@napi-rs/canvas@1.0.10`, installed with `npm ci --ignore-scripts --no-audit --no-fund`, plus `npm run build`. The package lock selects prebuilt Apple Silicon macOS or Linux x64/arm64 glibc/musl bindings; no GUI or browser package is required. `renderer.available` means only that Node, the matching native binding and the two checked-in worker bundles exist; it does not check provider/model access or quota. System font scanning is disabled because reference exports contain no text. A missing dependency, failed startup, concurrent export, invalid PNG or 15-second timeout returns an explicit 503; no browser fallback, provider request or automatic retry. On macOS the worker is additionally sandboxed from `~/Library`, `/Applications`, network and unrelated process execution; Linux uses the worker's equivalent path/network/process guards. Actual image/video generations retain their existing human approval and Idempotency-Key requirements.

The optional story `guide` contains `cast` (8), `places` (4), `acts` (8) and imported `script` (60,000 characters). Cards have stable `id`s, typed profile fields, up to 5 local `reference_ids` and 6 hex `palette` colors. The published strict plan adds asset `profile` fields and explicit shot `characters`/`location` relationships; older plans remain accepted. Visual views and batches are durable records. Batches accept 1–8 requests, allow 32 views per entity and never replay after restart. The workshop accepts only existing subscription image models. Confirming a new primary identity invalidates earlier dependent confirmations while retaining their candidates. PDF requires ReportLab (in requirements.txt).

Storybook answers also include optional `title` (120 characters). A focused revision uses the existing plan endpoint with `revision_of`, `expected_job_revision`, zero-based `scene_index` and `instruction` (2,000 characters). It is a separately approved, idempotent writing request. The selected scene is revised into a new version; other scenes, asset identities and shot cast/location links are preserved server-side. New shot/scene counts are rejected for this focused workflow. Completed stories linked to visual work are locked for direct PUT editing; fork first. Starting the visual studio fills blank book cast/place cards and an empty arc from the reviewed script in the same transaction and updates the plan/world revision link.

### Series foundations and episode books

`GET/PUT filmmaking/series/{production_id}/bible` and `GET/PUT filmmaking/episodes/{episode_id}/book` store separate revisioned books. Writes require `expected_revision`; episode title/script actions also use `expected_episode_revision`. Selected asset IDs capture exact inherited reference snapshots. `refresh_inheritance: true` is explicit.

Read/link reusable identities with `filmmaking/series/{id}/library`; explicitly promote an episode entity using `POST filmmaking/series/{id}/library/promote` with `entity_id` and `expected_revision`. `filmmaking/episodes/{id}/library` includes the current episode's identities. Manual visual workshops and generate actions live under `filmmaking/series/{id}/workshop|generate` and `filmmaking/episodes/{id}/workshop|generate`. `GET filmmaking/entities/{id}/workshop` retrieves the identity's exact workshop. Generations require approval, scoped job IDs, expected view revisions and idempotency keys.

Episode actions: `plan`, `complete-production`, `production-review`, `jobs`, `apply`, `script`, `trash-script`, `storyboard`, and `refresh-assets`. Applying targets that selected episode; existing scripts require `replace_existing: true`. Reference refresh accepts explicit shot IDs/revisions, approval and book/episode revisions. Completed takes require a separate explicit override; the UI refreshes unfinished shots only.

`POST filmmaking/episodes/{id}/complete-production` prepares supporting production details while preserving the saved/uploaded script. Send `expected_revision`, `expected_episode_revision`, `provider`, `approved: true`, optional `allow_dialogue_polish` (default false), and an idempotency key. It covers all original scenes (up to 150), with 1–3 shots per scene. The normal AI rewrite path retains its separate 8-scene/20-shot bounds. The returned `world-job` has `purpose: production-details`, immutable `source_script`, canonical `catalog` snapshots, and a `completion` review containing asset mentions and optional dialogue suggestions. Exact unique asset names can match automatically; aliases, duplicate names and unidentified assets require human choices. Asset substitutions affect production prompts/reference links only, never manuscript names.

`POST filmmaking/episodes/{id}/production-review` requires `job_id`, `expected_revision`, `resolutions` (every uncertain mention ID mapped to a compatible catalog asset ID or `new`), and `accepted_dialogue` (only the dialogue unit IDs explicitly approved by the user; default empty). Each suggestion targets a detected spoken line, not action, headings or parentheticals. Applying uses the existing `apply` route after review and rejects changed source text or book revisions. Only approved dialogue replacements are applied, and the original is recoverable through script history. Earlier book chapters, saved foundation, asset selections and other episodes remain unchanged. Production plan edits can change summaries/style and shot directions, but cannot rewrite scene text, restructure scenes or bypass identity review. Episode books also persist `script_options: {allow_dialogue_polish: false}` for the upload/Draft preference.

`GET filmmaking/series/{id}/book.pdf` and `GET filmmaking/episodes/{id}/book.pdf` export saved data and approved references locally, returning application/pdf. Earlier worlds/routes/records remain supported.

Character reference generation requests may include `character_sheet: true` for primary character or outfit sheet views. For an unreviewed template draft this applies the four-view prompt and 3:2 layout at the explicit generation action; a current reviewed prompt is preserved; saved candidates and approval IDs are retained. Approval, expected revisions, scoped job checks and idempotency are unchanged.

Character, location and prop profiles accept up to five `reference_ids`. Main image generation rebuilds draft `extras` from the current saved profile, including when a main location is already approved; old request snapshots and approval stay unchanged. All five inputs are compiled into the selected model transport in order. Location coverage still uses the approved identity only. This workspace retains a five-input limit on both subscription paths; OpenAI’s Images API documents 16 inputs, but that API limit does not establish the Codex subscription limit. Sources: https://developers.openai.com/api/reference/resources/images/methods/edit and https://docs.x.ai/developers/model-capabilities/images/multi-image-editing (checked October 6, 2026).

Clear approval requires idle generation and a current entity revision. It leaves cached files, canonical Asset Studio references and all saved episode/shot/draft/job snapshots intact. Uploaded former identities are retained as candidates. Reapproving the same image restores its prior canonical handle; a different main image can create a new handle while preserving the old one. Selected variations are cleared for future work, and variation generation waits for a newly approved main identity. Repeated clear on an already-unselected entity returns its snapshot without a mutation.

Workshop prompt preparation builds a creative brief and inspiration inputs from current saved details for all three categories, respecting an explicit custom brief. AI writes the final prompt; live generation uses the current reviewed preparation exactly. Episode visual workshops use their own style override or pinned Bible style. A blank pinned style does not silently inherit a newer Bible style.

### Storyboard opening-frame preparation

- `GET filmmaking/shots/{id}/opening-frame` reads the latest proposal without provider usage.
- `POST filmmaking/shots/{id}/opening-frame` with `expected_revision` (shot), `expected_image_revision`, `approved:true` and an `Idempotency-Key` prepares the initial still via the selected image model's writing provider. `force:true` explicitly prepares again; unchanged requests reuse pending/completed results.
- Poll `GET filmmaking/opening-frame-jobs/{id}` for `pending`, `done` or `error`, then inspect `result.prompt`, `opening_state`, exact reference handles and `notes`.
- `POST filmmaking/shots/{id}/opening-frame/apply` with `job_id`, `expected_revision` (job), `expected_image_revision` applies the proposal to the image draft. `replace_prompt:true` explicitly approves replacement of edited prompts/drafts with image takes. Without it, only the unchanged starter draft marked `auto_apply` can be applied. The script, shot direction, model and reference selection are rechecked against captured inputs. Original image settings are backed up.
- `POST filmmaking/shots/{id}/opening-frame/restore` with job/image revisions restores original image settings only before newer edits. `previous_prompt` remains available for manual copying afterward.

No endpoint generates media or alters screenplay/Bible/Storybook content. Preparation uses ChatGPT/Codex subscription writing for OpenAI image models or the existing Grok writing transport for Grok images. Prompt/reference validation uses the selected image model's expanded limit; additional references must fit five total image sources. Included props retain their own name within the parent asset. Jobs persist separately from script planning/history, are mode-scoped, and are not automatically replayed after failure or restart.

### Video direction and timing preparation

- `GET filmmaking/shots/{id}/video-direction` reads the latest proposal, default writing provider, current video model/duration and configured prompt limit without provider usage.
- `POST filmmaking/shots/{id}/video-direction` with `expected_revision` (shot), `expected_video_revision`, `approved:true`, optional `provider:"codex"|"grok"`, optional `instruction` (up to 2,000 characters) and an `Idempotency-Key` prepares visually grounded motion, reference associations and duration. `force:true` requests a fresh proposal. Cached results must match the source/model/reference inputs, provider and normalized instruction. A changed instruction never reuses a proposal created for different directions.
- Poll `GET filmmaking/video-direction-jobs/{id}`. A completed result contains `direction`, `asset_summaries:[{handle,summary}]`, `duration_seconds`, `duration_reason`, `starting_frame_observations`, `notes` and `issues:[{code,severity,message}]`. Image-backed summaries are empty; supporting metadata stays inside the writing context. `instruction` records the human direction used. `prepared_prompt` is editable choreography; expanded sizes include the compiler-added canonical name/image and speaker/audio associations.
- `POST filmmaking/shots/{id}/video-direction/apply` requires `job_id`, `expected_revision` (job) and `expected_video_revision`. Set `replace_settings:true` to replace edited direction/timing or a draft with video takes; otherwise only an unchanged starter draft marked `auto_apply` may be applied. Source changes require preparation again. Prior video settings are backed up.
- `POST filmmaking/shots/{id}/video-direction/restore` with job/video revisions restores previous settings only before newer edits. Previous direction remains available for manual copying afterward.

Each attached named snapshot retains its saved metadata. The writer receives every configured frame and reference image with exact role, name, handle, generation tag and pixel hash. Complete appearance is separated from biography; blank canonical appearance can fall back to the original source card without overwriting saved refinements. Approved image pixels govern visual identity and the first frame governs starting composition/object states. The provider prompt contains one sentence per image-backed character: `Preserve SampleHero's exact appearance as shown in <IMAGE_1> throughout the shot.` No full profiles or image-backed summaries are appended. `@SampleHero2` is an editor handle and becomes the display name SampleHero in provider prose. Voice-only named assets may use a scene-only `video_summary` up to 220 characters.

The complete expanded reference request must fit 4,096 UTF-8 bytes; ordinary workflows use the configured character limit. Duration must fit the selected model and keyframes. Warnings and errors appear only when needed: required dialogue with Audio off remains a deliberate silent output option with a clear warning, while unresolved visual/continuity conflicts or explicit beats beyond duration block submission. `/api/validate` reports `prompt_issues` and `prompt_generation_blocked`; live raw-video submission enforces blocking conflicts too. Script/identity changes, attachment pixels or mapping changes invalidate preparation. Resolution alone remains exempt. Preparation writes no media, modifies no screenplay or approved images, and never retries automatically.

The browser waits for an explicit **Prepare with AI / Prepare again** click so directions can be entered for the first request. Human instructions are supplied separately as `user_instruction`; prior script/asset text remains story data. Repeat requests include the last completed proposal for the same shot as historical `previous_preparation`; actual current inputs take priority even if references or settings changed. User directions may revise AI camera, pacing, performance and timing but do not authorize screenplay, identity or book changes. Resolved differences appear in notes; unresolved constraints appear as structured issues with an actionable message. Submitted instructions persist with the job; unsent drafts stay scoped to the shot and browser workspace.


## Video review and lessons

### Video review and learned prompting

The original video-review feature was tested offline and loaded into the running
service. The iteration additions are tested offline and loaded locally after the
user authorized testing: 403 Python tests, 44 JavaScript suites and the frontend
build pass. Saved local project data remains unchanged; no paid writer or media
request was used for testing. See
implementation notes.

`POST video-review` requires `approved: true`, `video_job_id`, `scene_id`, a
writing `provider` (`codex` or `grok`) and an `Idempotency-Key`. Optional `notes`
and `previous_review_id` focus the review or compare another attempt. An explicit
null previous review requests a standalone review. Duplicate keys return the
same job; changed payloads conflict. Identical completed reviews of an exact
snapshot can be reused; an explicit `force: true` authorizes a fresh review call.
No video generation occurs. Poll `GET video-review/{id}` for findings, inspected
frames/references, hypotheses, a targeted revised direction and usage metadata.

`GET video-review?scene_id={scene_id}&target_video_job_id={video_job_id}` lists
reviews and includes `suggested_previous_review_id` when the target take's frozen
submission identifies the review that produced its prompt. It does not infer the
source from today's editor. The suggestion is optional: an explicit
`previous_review_id: null` continues to request a standalone review.

`POST video-review/{id}/apply` separately requires `approved: true`,
`expected_scene_revision`, `expected_review_revision`, and optionally `prompt`
and `expected_scene_prompt`. Inputs, frozen image hashes, compiled request and
draft/review revisions must still match. A change to approved workspace lessons
does not invalidate an already reviewed proposed prompt or force another writing
call. New reviews retain a separate `base_guide_sha256`; applying their proposal
is blocked if the shipped capability guide changed since that review. Legacy
reviews without this hash rely on the current compilation guards rather than
requiring a paid replacement review. New reviews and refinements capture the
current combined guide and cannot begin writing with stale captured provenance.
Quoted dialogue is preserved unless a human explicitly
supplies `allow_dialogue_changes: true`; the UI retains exact dialogue by default.
The prior direction remains in review history. This operation does not generate
another video.

`POST video-review/{id}/outcome` records an explicitly approved human assessment
with `assessment: "successful" | "improved" | "needs_work"`,
`expected_revision`, optional `notes`, `confirmed_finding_ids` and
`candidate_index`. Legacy `successful: true | false` remains supported.
For an improved take, explicitly identify the individual `met` findings confirmed
by the human. A candidate can propose a tentative lesson only if all its backing
findings are confirmed and met, with the served model confirmed to match the
requested model. The rest of the take may still need work. Unsupported or
uncertain findings cannot become lessons. `candidate_index: null` explicitly
records the assessment only, without selecting a default lesson candidate.
Learning never automatically adopts a proposal or makes a writer call.
Read `GET video-review/lessons/model/{model}` for lessons and `guide_version`.
Approve a lesson with `POST video-review/lessons/{id}/approve`, `approved: true`,
`expected_revision`, `expected_guide_version`, and optional edited `guidance`.
Dismiss proposals or deactivate active lessons with their corresponding routes
and expected revisions. Approve can also restore an inactive lesson. Approved
lessons supplement future AI authoring for that workspace, mode and model;
shipped capability documentation is retained.

`POST video-review/{id}/refine` explicitly requests a focused writing pass. It
requires `approved: true`, `expected_revision`, a writing `provider`, nonempty
`notes` describing the remaining issues, `preserve_finding_ids` for the met
findings to retain, and an `Idempotency-Key`. It reuses the parent review's frozen
request, sampled output frames and reference evidence; it does not extract or
render another video. Poll the returned child review using `GET
video-review/{id}`. Its `parent_review_id` retains the relationship to the prior
report. Inspect and explicitly apply the new proposal separately. Guide approval,
refinement and media generation remain independent actions; approving a lesson
does not start this writing pass.

Video review is based on sampled frames. Exact speech, delivery, acoustics and
lip sync are unassessed; audio inspection checks stream presence only. Sparse
samples cannot prove sustained motion. Historical jobs without frozen request
pixels remain explicitly reconstructed. Review uses the selected writing
connection; generation and adoption remain distinct authorized user actions.


## Timeline editing and accounts

### Editing overview and private workspaces

Agents use the same timeline service as the Edit UI. Read `GET editing/schema` for limits and `GET openapi.json` for the published request contract; read runtime schema for additional validation constraints. A source is `{"kind":"take"|"upload"|"image","id":"workspace-media-id"}`. Inspect it before setting trim bounds; never guess duration or audio availability. Video/image order is clips array order. Audio starts and title ranges use seconds from the start of the assembled edit. Video/audio trims use source seconds. Image clips use in=0 and out=display duration (default three seconds), and generated images require approval. Sources include the selected episode and active grouped descendants, plus workspace assets and uploads.

```python
client = StudioClient()  # Pass token_file for a private workspace.
edit = client.open_edit(production_id, episode_id=None)
sources = client.edit_sources(production_id)
source = sources["takes"][0]["source"]
info = client.inspect_media(source)
edit = client.save_edit(edit, clips=[{
    "id": "opening", "source": source, "in": 0,
    "out": info["duration"], "volume": 1, "label": "Opening"
}])
job = client.export_edit(edit, idempotency_key="unique-export-20261003")
job = client.wait_for_export(job["id"])
if job["status"] == "done":
    client.download_export(job["id"], "finished.mp4")
```

`upload_media(path)` adds video, audio, PNG, JPEG or WebP. `save_edit` can update title, clips, audio, titles and output with the fetched revision. Export requires a unique Idempotency-Key and expected_revision; the completed file belongs to the immutable snapshot in the job. `cancel_export(id)` stops a render without deleting the edit or sources. `GET editing/exports/{id}/manifest` returns the exact snapshot. These operations run locally and consume no provider generation usage.

For AI-assisted editing, request `creative/context` with stage `edit` and production/episode scope. Timeline actions participate in normal review, atomic apply and undo. Script revisions remain available in Edit context.

Private workspace tokens are in `<private-data>/<service>/workspaces/<workspace-id>/agent-token` (or under the main `<private-data>/studio` directory for guests created in personal mode). Never print a token or pass a provider key as agent authorization. A token can access only that workspace's services and media. `GET studio-account` returns safe identity state. `POST studio-account/api-key` stores/removes that workspace's OpenAI key, without returning it. Interactive identity consent/account switching stays bound to a browser session; agents cannot switch identities by naming another workspace.

#### Requestable ChatGPT/Codex reconnection

`POST /agent/v1/studio-account/codex` with **`{}`** returns **202** and requests that a human reconnect ChatGPT for the bearer token's own workspace. It saves a local pending request and never launches Codex, contacts a provider, opens a verification page, or completes verification. Unknown fields (including workspace/account IDs, codes and credentials) are rejected. Repeated requests while pending return the same request ID. After a terminal result, a deliberate new POST creates a new request.

Studio shows a compact prompt on the current page, including an open development sheet. The human clicks **Start sign-in**, which uses the existing cookie-authenticated `POST /api/studio-account/codex` device-auth flow; the human finishes on ChatGPT's sign-in page. Only the human dialog receives its verification link/code. Browser mutations require a real browser session plus the existing same-origin checks; a bearer token cannot start verification through a forged browser request. Starting a pending request uses its opaque `request_id`; a stale or foreign ID returns 409. This action renews credentials in the current workspace and does not switch Studio identity or choose another workspace. In personal mode the existing shared Mac Codex login is retained; private workspaces keep their isolated credential profile.

`GET /agent/v1/studio-account/codex` polls the request, and `GET /agent/v1/studio-account` embeds it as `codex_reconnect`. Both redact device URLs, codes, credentials, cookies and other workspace identities. The request contains only `id`, `status`, `step`, `human_action_required`, safe `error`, `requested_at` and `updated_at` (Unix seconds). Status is **idle** (no request), **pending** (`human_start` or `device_verification`), **connected** (`complete`), or **error** (`error`). No-request fields are null with step `none`. Pending requests waiting for the human survive restart; interrupted verification becomes a safe error on the next read, with no automatic restart. The existing native verification timeout remains ten minutes. `connected` means that this sign-in completed; it does **not** establish model access, quota or image-generation readiness.

Python helpers: `StudioClient.studio_account()`, `request_codex_reconnect()` and `codex_reconnect_status()`. Poll without re-POSTing; while pending, tell the human to use the prompt in Studio. Real generation still separately requires `approved: true` plus `Idempotency-Key`. There is no agent verification-completion, workspace-selection or identity-switch endpoint.

The original personal workspace continues to use `~/Library/Application Support/Imagine Studio/studio/agent-token`. Private workspaces do not inherit its provider connections. Account profiles remain private and local.

#### Production organization and recoverable deletion

- `POST /agent/v1/productions/recent`: `offset` and `limit` page the top-level groups/standalone productions. Supply `parent_id` to page an active Story / Series's members, or `archived: true` to page Trash. `total` is the number in that page's scope; With `projects_only: false`, `production_total` counts all active productions (or all trashed productions). With `projects_only: true`, both counts reflect projects in the requested group scope, and `child_count` counts project children. Items include `is_project`, `project_label`, `group_id`, `child_count`, `item_type` and `last_updated`. Bible-generated/refined images and standalone image drafts are media inside their owning workflow, rather than separate projects. `StudioClient.recent_productions(projects_only=True)` exposes this filter.
- `POST /agent/v1/productions/{id}/membership`: require `expected_revision` and `parent_production_id`. Use an active Story / Series ID to add/move, or explicit `null` to detach. Circular relationships and foreign workspace IDs are rejected. Grouping preserves existing scene/script links and settings.
- `POST /agent/v1/productions/{id}/trash` and `/restore`: require `expected_revision`. Trash is recoverable and retains original media, scripts and edits. Trashed productions cannot be selected. Children of a trashed group appear as standalone while retaining their saved relationship; restoration respects subsequent explicit moves/detachments.

`GET /productions` lists active records. `GET /productions/{id}` can inspect a trashed record for restoration. Discovery/schema and OpenAPI publish these actions; route coverage is checked against dispatchers, not a claim that every UI workflow already has parity. Python client helpers: `recent_productions`, `group_production`, `trash_production`, `restore_production`. No operation generates media or consumes provider usage.


Editing clips may include `transition: {"type":"cut"|"dissolve"|"fade","duration":seconds}`. This is the **incoming** overlap; the first clip must be cut (zero duration). Overlap must be a whole output-frame duration, at least one frame and at most two seconds or half either neighboring clip. `fade` passes through black; `dissolve` blends the images. Missing transition fields remain compatible with cuts. The edit duration is the sum of clip lengths minus incoming overlaps; audio/title positions use that assembled duration.

To split a video, replace it with two source-trimmed copies with distinct item IDs. The left copy keeps its incoming transition; the right copy uses cut. Each resulting clip must contain at least 0.04 seconds and leave enough footage for adjacent overlaps. Split image clips into two in=0 clips with separate display durations. Reorder/remove by saving a new clips array; agents must validate neighboring transitions and audio/title bounds. The UI offers session Undo/Redo; agents can restore a previously read timeline with the current expected_revision. All these actions use the same revisioned save/validation service as the visual editor and never invoke an AI generation.

### Audio

The editor and `editing/*` API share schema version 3. Audio fields are optional. New timelines default to `output.cut_audio_crossfade_frames: 2`; old timelines migrate on read to 0. No stored rows are rewritten on load. Neutral v2 timelines retain the legacy export pipeline.

| Feature | JSON example | Range / default |
|---|---|---|
| Cut smoothing | `{"output":{"cut_audio_crossfade_frames":2}}` | Integer 0–12, new 2, migrated 0; picture and total duration unchanged |
| Item fades | `{"audio_fade_in":0.25,"audio_fade_out":0.5}` | Clip/audio seconds, whole frames, 0 to min(2, half duration), default 0 |
| J/L edit | `{"audio_offset":-0.5}` | Clip seconds, whole frames −2 to 2, default 0; source handles required |
| Normalize | `{"normalize":true}` | Clip/audio boolean, default false; single-pass loudnorm to −16 LUFS |
| Mix target | `{"output":{"loudness_target_lufs":-16}}` | null by default, or −30 to −10 LUFS, TP −1.5 before limiter |
| Named lanes | `{"lane":"music"}` | Audio dialogue/music/sfx, default sfx; clip audio is dialogue |
| Ducking | `{"output":{"ducking":{"enabled":true,"amount_db":10,"attack_ms":80,"release_ms":400}}}` | Disabled by default; amount 0–24, attack 5–500 ms, release 50–2000 ms |

Use the clip inspector for fades/normalize/lead-lag, the offset strip to drag split timing, and Export settings for smoothing, target and ducking. Drag audio labels to lane labels. Mute/solo are preview-only. `editing/inspect` returns a cached first-30-second loudness estimate (`loudness_lufs`, null for silence/unavailable).

Preview uses WebAudio gain ramps and an approximate dialogue-window ducking envelope. Loudness uses a gain estimate, not loudnorm. J/L browser seeking is approximate; source handles and fades are exact on export. Export normalization is documented single-pass (not two-pass); ducking is a sidechain compressor, so reduction depends on dialogue level. Cut smoothing extends outgoing source audio into available handles; exhausted handles fade to silence rather than inventing audio.

### Picture

Optional clip controls default to neutral. Examples (merge into a clip):

- Mirror: `{"flip_h":true,"flip_v":false}` (booleans, default false).
- Crop: `{"crop":{"x":0.1,"y":0,"w":0.8,"h":1}}` (fractions 0–1, width/height ≥0.1, contained in source; default full frame).
- Zoom: `{"zoom":{"scale":1.5,"x":0.5,"y":0.5}}` (scale 1–3, centers 0–1; clamped to avoid empty edges).
- Speed: `{"speed":0.5,"speed_audio":"preserve_pitch"}` (0.25–4; preserve_pitch or mute). Moving duration is `(out-in)/speed`.
- Freeze: `{"hold_start":0.5,"hold_end":1}` (0–10 seconds in whole frames; silent holds).
- Gap: `{"id":"gap","source":{"kind":"gap"},"in":0,"out":1,"color":"#000000"}` (0.04–60 seconds, hex color).

Use Picture in the inspector, Fill frame, the preview crop resize handle and zoom-position drag control. The timeline shows retimed lengths. Split inside the moving part of a held clip, outside its holds. Browser frame seeking/codec rounding may differ by one frame; the export's tpad holds are exact.

### Captions and export

- Cues: `{"captions":[{"id":"c1","start":0,"end":1,"text":"Hello, Eve!","speaker":"Mira"}]}`. Up to 2000 cues, 2000 characters each; positive times within the edit.
- Style: `{"output":{"captions":{"mode":"both","position":"bottom","size":48,"color":"#ffffff","max_chars_per_line":32}}}`. Mode off (default), burn_in, sidecar or both; top/center/bottom; size 16–96; hex color; line width integer 8–80 (default 32).
- `POST editing/timelines/{id}/captions/import` with `{"expected_revision":2,"srt":"1\n00:00:00,000 --> 00:00:01,000\nHello\n"}` imports SRT. Caption rows support editing, nudging, split and merge in the Captions panel.
- `POST editing/timelines/{id}/captions/transcribe` with `{"expected_revision":2}` returns a local caption job. Poll `GET editing/caption-jobs/{id}`. It requires an installed faster_whisper package and existing local model (`local_transcription_model` config path, or workspace transcription-model directory). Nothing is installed/downloaded. Without both, 503 `transcriber_unavailable` directs you to SRT import. Concurrent timeline edits prevent transcript application.
- `GET editing/exports/{id}/captions.srt` downloads a sidecar; edit.json lists export files. Bracketed speaker prefixes round-trip as optional speaker names. Burn-in reuses the literal PNG title renderer.
- Resolution: `{"output":{"resolution":"480p"}}` produces 848×480, 480×848 or 480×480 by ratio. `source` uses the first real video's even-rounded dimensions and warns on mixed sizes; a no-video edit falls back to the selected ratio at 720p. Existing 720p/1080p remain.
- `POST editing/timelines/{id}/preview` with `{"expected_revision":2,"quality":"draft"}` renders all effects at 360p, ultrafast/CRF30. Full remains the default. Drafts are labelled and never marked latest_delivery; frame grabbing works for either.

Captions are shown during browser playback, including sidecar-only captions (which are not burned into that export). Font metrics/wrapping and browser frame seeking can differ slightly; local export is authoritative. Draft previews are lower quality by design. Caption transcription uses original local sources, intersected with trims and mapped through speed, holds and split-audio offsets.

### Workflow and color

- `POST editing/takes/select`: `{"shot_id":"shot-id","take_id":"take-id","expected_shot_revision":3}` delegates to production select-take validation. Sources include shot_revision and selected. Use stars on take cards or a take-backed timeline clip.
- Markers: `{"markers":[{"id":"m1","time":2,"label":"Reaction","note":"Keep Mira still","color":"#aef0ca","clip_id":"clip-id","clip_time":0.5}]}`. Up to 500; label ≤80, note ≤2000; palette mint #aef0ca, yellow #ffdb8a, red #ff8888, blue #88bbff. Absolute markers stay at their timeline time. clip_id+clip_time anchors recompute time when earlier clips change. Missing anchors are rejected. Press M, use the marker list to edit/jump, and read markers in the export manifest (not burned in).
- `GET editing/timelines/{id}/revisions` lists revision, created_at, clip_count, duration and title newest first. `GET …/revisions/{n}` returns a full read-time-migrated body. `POST …/revisions/{n}/restore` with `{"expected_revision":4}` creates revision 5 with old contents; history is untouched. Use Versions → Restore with confirmation. Browser undo/redo remains session-local.
- Clip color: `{"color":{"brightness":0.1,"contrast":1.1,"saturation":0.9,"temperature":0.2}}`. Defaults 0/1/1/0. Ranges: brightness −0.5–0.5, contrast 0.5–2, saturation 0–2, temperature −1–1. Gap color remains a hex string. Export uses eq plus red/blue colorbalance (temperature×0.2). Browser CSS brightness/contrast/saturation and sepia/hue temperature are approximate.

Client helpers: list_revisions, restore_revision, select_take_from_edit, transcribe_captions, import_captions and preview_export. All edits retain expected_revision protection.

#### Workflow safeguards

`POST /prompts/check` accepts `{scene_id}` or `{scene,prompt,shot_id}` and returns non-blocking warning records. Rules are in `prompt_check_rules.json` and follow the runtime video guide. Voice tags belong once in the compiler header, not the body. These checks are conservative text heuristics, not visual inspection.

`GET /usage` returns provider allowances as `unknown` when unavailable, local non-mock daily generation counts by model, and timestamped recent quota/limit errors. Local counts are attempts submitted by this app, not provider billing totals. Grok video, Grok images and ChatGPT image bridges currently expose no numeric media allowance.

Shots accept `video_mode: image_to_video|text_to_video` and `start_frame_asset_id` through revisioned `PUT /productions/shots/{id}`. Image-to-video generation requires `image.asset_id` matching the attached start frame and an approved asset. Missing facts are enumerated in `start_frame_required` (409). `allow_unapproved_start_frame:true` bypasses approval only, is recorded on the job and never bypasses attachment, authorization or idempotency. The browser shows the same gate and an explicit recorded approval override.

`GET/PUT /scene-layouts/{id}` stores scene geography (scene ID) or a shot's end-state override (shot ID). PUT uses `expected_revision` (0 initially), `camera_side`, and `characters:[{name,position:left|center|right,depth:foreground|background,facing:left|right|front|back,target}]`. Facing is always the character's own direction. Writer dependencies and preflight include scene layout, the preceding shot's saved end state, and matching lessons; changes invalidate preparation.

`POST /assets/{id}/annotations` records reviewed `{approved,known_text,pose:{Name:"left"}}`. Pose is explicitly supplied metadata, never inferred from pixels. `POST /lessons` records `{project_id?,failed,worked,entities:[],model?,shot_type?,date?,source_take?}`; absent project_id is global. `GET /lessons` lists and `POST /lessons/search` filters with `{project_id,query,entities,model}`. Preflight cites matching lesson IDs. The scene workflow panel provides a row layout editor, source-take review, lesson entry/search and frame attachment/approval controls.

`POST /assets/{id}/mirror` mirrors an existing local image or completed video take into a new asset with `mirrored_from`; the source is retained. Video audio is stream-copied. Linked videos require `expected_shot_revision`; their derived take remains associated and is not automatically selected. Known text produces a warning. Mirrored images require fresh approval. Image review, video history and editor media cards expose Mirror.

`GET /editing/timelines` lists named timelines, with primary state supplied for legacy records. `POST /editing/timelines/{id}/duplicate` takes `{expected_revision,title?}` and copies into an independent new ID. `POST /editing/timelines/{id}/primary` takes `{expected_revision}` and marks that timeline primary in the episode. Old IDs and exports are unchanged. The editor selector switches saved timelines; Duplicate and Make primary use the same routes.

Ducking now normalizes dialogue/music/SFX stems **before** attenuation when a loudness target is set. The target is a stem target in this mode, not a promise that the final mix has that LUFS. A bounded dry/wet sidechain blend caps reduction at `amount_db`; default 10 dB. The final limiter remains, with no post-duck loudness pass. Attack/release are envelope controls; detector release is calibrated for the elevated key. Preview remains an approximation based on dialogue windows. A fixed local speech fixture verifies 6/10/14/24 dB steady-speech reductions within ±2 dB on FFmpeg 7.1.5 and 9.0.1; onset and release ramps are intentionally transitional. Dialogue-lane background noise can also trigger the detector; it is not semantic speech recognition.

Lesson search also accepts `shot_type`; shots accept optional `shot_type` via their revisioned update route. Writer matching uses character/prop titles and handles, model and shot type, plus project/global scope. Video take text annotations accept `{known_text:true}` on the same annotations route. UI overrides are cleared when selecting a different video scene.

Export failures retain the last 40 FFmpeg stderr lines as `ffmpeg_stderr` on the
export job, with `ffmpeg_exit_code`; `error` includes the diagnostic text. Frame
extraction failures return `preview_failed` with the same diagnostic in the error
message and retain `frame_ffmpeg_stderr` on the job. The editor displays this text.
Audio offsets preserve incoming and outgoing audio crossfades at both cuts and
dissolves; an offset on another clip does not change the transition envelope.

#### Scene timelines and bounded exports

`POST /agent/v1/editing/timelines/open` accepts optional `story_scene_id`,
which must belong to the supplied episode and production. Omit it (or use null)
for the episode assembly. Named duplicates and primary selection operate within
each scene scope. Legacy timelines read as episode scope; IDs and old exports
remain valid without rewriting their stored snapshots. The human editor has a
Scene timeline picker and an Episode assembly option.

`POST /agent/v1/editing/timelines/{id}/render` requires an Idempotency-Key and
`{expected_revision, parent_timeline_id, expected_parent_revision}`. The source
must be a scene timeline and the target an episode timeline in the same
production/episode, with matching frame rates. It exports the immutable source
revision and appends one full-length upload clip to the parent. Re-rendering
replaces the clip linked to that source timeline, retaining its item ID and
incoming transition. Parent trims and effects on that linked clip reset to the
new complete scene; review those edits before rendering again. Clips expose
`render_link: {timeline_id, revision, export_id}` derived from the source media.
Poll the export job: `render_status: inserted`, parent_timeline_id,
parent_revision, rendered_clip_id report insertion. A parent edit during render
leaves the completed export available with `render_status: error` and
`render_error`; it never overwrites the newer edit. Invalid resulting title,
audio, caption or transition bounds also leave the parent untouched. Identical
idempotent retries return the original job. In the UI use Render into episode
and choose the named episode target. Python: `open_edit(..., story_scene_id=...)`
and `render_edit(scene, parent, idempotency_key)`.

Exports exceeding four source/overlay inputs use serial lossless filter batches:
at most four input streams/files and eight filter nodes per FFmpeg process.
FFV1 video and float PCM in temporary NUT files avoid intermediate lossy encoding;
balanced joins and audio sums bound graph growth. Intermediates are removed on
success, failure and cancellation. The job reports batch_input_limit,
batch_peak_inputs, batch_stages and sampled ffmpeg_peak_rss_kib. This bounds
decoders, not OS RSS; large dimensions and long edits still require memory and
local temporary disk. The legacy small neutral export path stays compatible.

#### Editor audio capacity and local transcription

Audio capacity is 200 items **per timeline**, shared across all three audio lanes.
Item 201 returns timeline_limit: "Use at most 200 audio items per timeline."
Clips remain capped at 120 and titles at 100. UI and discovery show the same caps.

- `GET /agent/v1/editing/transcription`: settings revision (0 before first save),
  effective `local_transcription_model` absolute path, engine_available,
  model_present, available and a setup/SRT fallback message.
- `PUT /agent/v1/editing/transcription`: `{expected_revision,
  local_transcription_model}`. Use an absolute folder or null to restore the
  configured/default folder. A stale revision returns 409. Settings are private
  to the current workspace and persist across restarts. No file is downloaded.
- Existing `POST editing/timelines/{id}/captions/transcribe` still takes only
  expected_revision, snapshots the model path, and returns a caption job. If the
  local engine or required model files are missing it returns 503 with
  transcriber_unavailable and tells the caller to import SRT. A queued job uses
  its captured path even if settings change. Timeline revision checks still
  prevent an obsolete transcription from overwriting edits.

Install the optional `requirements-transcription.txt` extra into the app's venv
separately; see README setup notes. Local models need model.bin, config.json and
tokenizer.json. The engine loads with local_files_only=True, CPU/int8; no live
writer/provider or implicit model download is used. Human controls are in Edit →
Captions (model path/save/check, availability, transcribe and Import SRT).

Audio offset validation identifies the clip label and item ID in
`invalid_audio_handle` errors. Negative offsets need unused source audio before
trim-in; positive offsets need unused audio after trim-out, adjusted for clip
speed and limited to whole output frames within ±2 seconds. Sources without
audio return a separate explanatory message under the same error code. Reset
audio_offset to 0 or leave sufficient trim handles; failed saves preserve the
stored timeline revision. The UI constrains both controls to these available
handles and offers an explicit reset if later trims invalidate an offset.


## Browser collaboration and shared drafts

### Shared controls and browser consent

Grok recovery disposal: after reviewing an errored recoverable image job, `POST image-studio/jobs/{id}/discard` with `{confirmed: true, request_id: "<the saved request_id>", reason: "optional explanation"}` (reason up to 500 characters). The job becomes `discarded` with `recoverable: false`, `discarded_at`, `discard_audit_id` and `discard_reason`; the workspace also stores an `image-job-audit` record. Cached outputs, original settings and the request ID remain available in job history. Confirmation and the matching request ID are required, active jobs are rejected, and repeating the confirmed discard does not add another audit entry. Discarding unlocks the draft for another model/request, makes the old job non-resumable, and does not cancel provider work or refund usage. Use `POST image-studio/jobs/{id}/resume` instead to continue GET-only polling/downloading without a new generation POST.

Provider result downloading supports transparent-proxy DNS in `198.18.0.0/15` only for the exact Grok output hosts `imgen.x.ai`, `images.x.ai` and `api.x.ai`. References retain the public-address check. Both paths retain HTTPS validation, no redirects, format/size limits and downloads without provider authorization headers.

Book rename consistency: `PUT filmmaking/series/{id}/bible` and `PUT filmmaking/episodes/{id}/book` propagate character/location/prop name edits through existing `source_card_id` and `entity_id` links in that book's scope. Use the existing card IDs when renaming. Linked entity/profile and sheet labels receive new revisions; an unchanged canonical reference title follows the rename while its handle remains stable. Independent workshop names and view titles are preserved. No saved prompts, media, historical versions or frozen episode foundations are rewritten. Reopening development repairs older stale sheet labels. No additional rename endpoint or provider call is required.

The same book saves merge changed appearance/profile fields into their linked workshop entities and refresh every linked sheet's copied description. Independently refined workshop values retain precedence over the source card. Unchanged saves and reopening development also repair stale sheet descriptions. `PUT filmmaking/entities/{id}` propagates an explicit workshop description edit to its sheets. These metadata updates increment affected record revisions, including approved views, without changing saved image jobs, their prompts or output filenames.

GET filters now work through the bearer API and the browser bridge. Use structured
query parameters in the standard-library client:

```python
reviews = client.request('video-review', params={
    'scene_id': scene_id, 'target_video_job_id': take_id,
})
```

`video_job_id` is also supported; `video-review/lessons` accepts `model`. Duplicate,
blank and unknown query keys are rejected. The CLI accepts a JSON `--params-file`.
OpenAPI now includes video import, atomic shot reordering, shot `story_direction`,
all templated path parameters, explicit empty commands and the formerly opaque
substantive mutation bodies.

For shared browser work, the human enables **Agent draft handoff**. This publishes
read-only book, image, video and timeline drafts plus open editor snapshots for
production briefs, shot direction, development details, camera staging/movement,
Precision edits, collaborator text and prompt instructions/review. Credentials
and embedded media are rejected. Sharing expires after two hours; inactive tab
snapshots expire after ten minutes. An empty list does not prove there are no
unsaved edits in a browser that has not shared them.

`GET handoff/tabs` lists consenting tabs with opaque IDs, revisions, destinations,
view state and editor snapshots. Each editor advertises its supported actions.
The human can separately enable **Agent browser controls** to execute navigation,
draft-resolution and playback requests automatically for two hours. Read-only
sharing alone never enables these actions; without controls permission, the human
can explicitly apply or decline a displayed request. Identity actions always
require human action, even when controls are enabled.

```python
tab = client.browser_tabs()[0]  # Choose the intended tab explicitly.
request = client.request_browser(tab, 'navigate', {
    'route': {'page': 'library', 'collection': 'images'},
    'view': {'query': 'robot', 'filter': 'approved'},
})
status = client.browser_request(request['id'])
```

The underlying route is `POST handoff/tabs/{id}/requests` with
`expected_revision`, `kind` and `payload`. Poll `GET handoff/requests/{id}`; a
queued response is not completion. Status is `pending`, `awaiting_human`,
`executing`, `completed`, `failed`, `rejected` or `expired`. Requests retain the
captured route/editor state, reject stale drafts in the browser, and acknowledge
only after the operation finishes. Revoking sharing also removes controls consent
and expires pending requests. A failed request can have saved drafts before a
later navigation step failed; read the saved state before retrying.

Supported request kinds:

| Kind | Payload |
| --- | --- |
| `navigate` | `route` with page/tool/media/project workspace; optional `view` |
| `resolve` | `editor` key from the tab; `action: save / reload / discard` as advertised |
| `playback` | Timeline `position`, `playing`, `zoom`, `selection` |
| `identity` | `action: signin / switch / cancel / logout / guest / restore-guest` |

View state also supports book `chapter` (0–5), development `section` ("0"–"4",
or "-1" to collapse), `expanded`, `scroll_top`, library `query`/`filter`, and
`field` with optional `expanded_editor` for a named field editor. The target editor
must be open. Navigation respects dirty/recovery guards; resolve the exact draft
first when a guard blocks it. To take over shared content, read its source revision,
save through the normal content API, then request `reload` in its originating tab.
`reload` discards that tab's pending local version, so target only the inspected
snapshot. No agent route grants draft-sharing consent or changes identity directly.

Identity requests open Workspace & account with the requested action. The human
chooses any destination identity and completes verification. The original agent
can observe success, rejection or failure without receiving verification URLs,
codes, destination workspace IDs or new tokens. Account switching does not transfer
the source agent's authority.

`POST documents/book` accepts `{kind: series / episode / world, id, format:
markdown / json}`. It returns `{filename, mime, text}` for the saved book and current
saved plan. `POST documents/render` formats a supplied `{document, title, plan,
family: series / story, format}` without saving it. Browser manuscript previews and
downloads use this same formatter, including pending local content explicitly
supplied by the browser.

`GET demo` returns versioned local sample images and the scene recipe in mock mode.
`POST demo/load` with an empty body and an `Idempotency-Key` creates that same demo
storyboard once; replay returns the existing scene. Both routes reject live mode.
The human Demo button uses this route. It never submits media generation.

For a composite timeline preview, call `POST editing/timelines/{id}/preview` with
`expected_revision`. It starts or reuses a local export of that immutable timeline;
poll `editing/exports/{export_id}`. Once done, `POST
editing/exports/{export_id}/frame` with `timestamp_s` and `expected_revision` (the
exported timeline revision) returns PNG bytes, including titles and transitions.
`client.preview_edit(timeline)` and `client.preview_frame(export, seconds)` wrap
these operations. Preview rendering consumes local compute and creates an export
record, with no writer/media-provider usage. Existing exports and originals stay
available after subsequent timeline edits.

### Revision and response contracts

`POST account/grok-check` uses the same fresh `check_grok_connection()` as browser `POST /api/grok/check`. In live mode it resolves current workspace credentials and calls Grok’s `/v1/models`; it does not substitute cached account state, submit an image, or prove image readiness. A completed check returns `signed_in`, `verified: true` and **`image_access_verified: false`**, including rejected credentials and mock responses. Upstream failure is an error, never a cached success. `StudioClient.check_grok_model_access()` names that limited guarantee.

Remembered public URLs have stable `url_id` (separate from asset IDs), `revision`, `archived`, `src` and `name`. `GET urls` returns active URLs; `GET urls/all` includes archived ones; `GET urls/{url_id}` reads either. `POST urls/{url_id}/archive` requires the current `expected_revision` and optional `archived` boolean (true removes, false restores). A stale revision returns 409. Removing a library URL preserves URLs already saved in scenes, job history and reference snapshots. Adding an archived duplicate or importing stale browser storage never restores it; explicit revision-checked restoration is required. The UI’s Remove URL uses this shared lifecycle. Client helpers: `remembered_urls(include_archived=True)`, `archive_url(record, archived=False)`.

The Series Bible and Episode Book have separate limits from the legacy World Builder guide: **12 cast, 12 places, 16 props, 12 acts**, with **5 inspiration references** per character/location/prop. The legacy guide remains **8 cast, 4 places, 8 acts**, also with **5 references** per profile. `GET filmmaking/schema` and book/workshop read routes identify the relevant scope.

The nine workshop/book methods previously absent from OpenAPI now have explicit request and response contracts: entity workshop read/clear approval; optional view rename/clear approval/return image/attempt review/candidate review; and Series/Episode PDF export. Candidate review requires **both** current view `expected_revision` and candidate `expected_review_revision` (initially 0). Return-image checks the view revision and the immutable job/candidate relationship; it does not save an image draft and therefore has no draft revision field. `filmmaking/worlds/{id}/generate` now publishes its existing required Idempotency-Key header. Client helpers mirror all nine actions.

Route coverage is guarded by `tests/test_agent_contract_drift.py`, which derives route/method predicates from core and delegated dispatchers and compares both directions against generated OpenAPI. It also accounts for the account bridge’s explicitly forbidden identity-switching routes. A new dispatcher syntax must extend the inventory parser instead of silently skipping coverage. Route coverage alone is not a guarantee of complete request validation. The subsequent parity work is implemented and verified in the October 16 completion record; its new regression tests also check HTTP query behavior, contract fields, browser requests and local outputs.

### Return flows and read-only drafts

These routes use the authenticated workspace's local storage. Flow IDs are opaque; an agent cannot choose a different workspace or provide a redirect URL. The human's browser creates a flow when opening Image Studio from a Bible/episode development sheet. Its saved destination includes the project/episode, book chapter (0–5), entity, view, source view revision, selected hero candidate, active/expanded sections, optional angle selection and scroll position. It also identifies the Image Studio draft. This metadata survives a Studio restart independently of browser-local storage. A new departure in the same browser tab supersedes its earlier open return; flows expire after seven days.

| Method | Path | Action |
| --- | --- | --- |
| GET | `/handoff` | Discover return-flow and read-only draft capabilities |
| GET | `/handoff/flows` | List this workspace's return flows, including recent finished/superseded flows |
| GET | `/handoff/flows/{id}` | Read the destination, status and flow revision |
| POST | `/handoff/flows/{id}/request` | Queue return with `{expected_revision}`; the originating browser tab restores it when viewing its matching Image Studio draft |
| POST | `/handoff/flows/{id}/finish` | Close an acknowledged return with `{expected_revision}`; 409 until the browser has restored the destination |
| GET | `/handoff/drafts` | List currently opted-in, unexpired browser draft snapshots; otherwise `[]` |
| GET | `/handoff/drafts/{id}` | Read one snapshot; 404 for expired, revoked, missing or foreign-workspace IDs |

Flow statuses are `open` → `return_requested` → `returned` → `finished`; direct human return can skip `return_requested`. `superseded` flows cannot request another return. For these legacy flow routes, an agent requests the saved return destination instead of changing its fields. General `/handoff/tabs/{id}/requests` operations additionally support explicit destination and view requests, as described above. The originating browser session **and tab** must acknowledge actual restoration; an agent cannot acknowledge it by spoofing browser headers. Other tabs do not receive the request. A request remains pending while that tab is closed or viewing another draft. Request/finish are revision-checked and idempotent with a fresh revision; stale revisions return 409. The browser normally finishes its own acknowledged flow automatically.

The **flow's** `revision` is navigation metadata only. `value.context.expected_revision` is the **source workshop view's** revision. Adopting an edited image still uses the existing `filmmaking/assets/{id}/return-image` route, with its normal source revision and review validations. Conflicts preserve the destination and edited image; a flow request never calls a provider or generates media. Saved books, image drafts, video scenes and timelines still use their normal revision-checked save routes.

```python
flows = client.return_flows()
flow = next(f for f in flows if f['status'] == 'open')
requested = client.request_browser_return(flow)
# Human's originating Studio tab restores the destination and acknowledges it.
state = client.return_flow(requested['id'])
if state['status'] == 'returned':
    state = client.finish_browser_return(state)
# Usually Studio has already advanced state to 'finished'.
pending = client.browser_drafts()
if pending:
    snapshot = client.browser_draft(pending[0]['id'])
```

Draft sharing is **off by default**. The human opens **Agent draft handoff** in Studio and clicks **Share pending drafts**. Only that cookie-authenticated browser session/tab can grant consent or publish snapshots. Sharing lasts two hours; publishing refreshes a ten-minute snapshot every five seconds while the tab is visible. **Stop sharing & remove snapshot** immediately revokes consent and deletes its snapshot. Expired snapshots/consent are removed on the next handoff access. Separate tabs opt in independently.

A snapshot has `id`, its own metadata `revision`, `captured_at`, `expires_at`, `read_only: true`, and `drafts`. The original entries (`book`, `image`, `video`, `timeline`) are null when clean or not open; dirty entries contain `{id, revision, dirty: true, data}`. An additional `editors` envelope contains the open-editor registry, including each editor's source revision, dirty flag, content and supported actions; it may include clean open editors. Source revisions identify saved baselines; they are **not save instructions**. Book data includes unsaved answers/guide/script plan and development details; image/video data includes pending editor settings; timeline data includes pending clips/audio/titles/output and playhead position. Only current editor content is captured, without forcing an autosave. Snapshots are capped at 256 KiB, reject embedded image data and credential fields, and live in a separate local `browser-handoff.json` file with private file permissions.

There is **no agent route to grant consent, publish browser snapshots or directly replace snapshot data**. Reading snapshots and legacy return-flow metadata does not overwrite a saved creative record. General browser-control requests can ask the originating editor to save, reload or discard its inspected draft; execution requires browser-control permission or explicit human application, plus a matching captured state. Agents can also save through ordinary revision-checked content routes and request an editor reload. Human generation approval, Idempotency-Key and device-verification boundaries are unchanged. Native clients receive no browser session hash, tab ownership hash, token, cookie or verification code in handoff responses.


#### Uploaded script duplicate review

`POST filmmaking/episodes/{id}/upload-preview` accepts `{text}` or `{name,base64}` (the same supported files and size limits as import-preview). It compares explicitly labeled metadata paragraphs, Markdown detail sections, and same-name character/location/prop fields against the current Bible, Storybook, and selected asset snapshots. Scene prose and uncertain/unlabeled descriptions are not automatically removed. The response includes `source`, `comparisons`, and `review_token`; each comparison lists every affected target and exact values. No AI request or saved changes occur.

`POST filmmaking/episodes/{id}/upload-apply` accepts `source`, `review_token`, `expected_revision` (book), `expected_episode_revision`, `choices` keyed by comparison ID (`uploaded`, `app`, or `both`), optional `allow_dialogue_polish` (false by default), and `replace_existing: true` when replacing a nonempty draft. Every comparison requires an explicit choice. `uploaded` retains the uploaded span and replaces only the displayed app fields (or removes the earlier uploaded copy). `app` removes only that metadata span from the upload, preserving the app/earlier copy. `both` preserves both. Conflicting selections, stale reviews, over-limit replacements and pending script jobs are rejected before changes. The original upload, previous Script draft and review with before-state snapshots are saved; original text is recoverable through Script version history. Existing storyboard scenes/media and canonical library reference images are untouched. Current writing plans become historical drafts to prevent applying an old plan to the new upload.


#### AI-assisted duplicate review

The Script upload UI uses AI review by default, through the selected ChatGPT or Grok subscription writing connection. Users can choose local comparison instead. AI proposes similar meanings, conflicting facts, and uncertain aliases; each suggestion shows exact uploaded text, exact saved field values, a reason and estimated confidence. No selection is preapproved. Screenplay narrative comparisons and excerpts exceeding field limits are advisory only, with Keep both as the available choice. The AI cannot rewrite content: the server binds proposals to exact source spans and existing server-owned targets.

`POST filmmaking/episodes/{id}/upload-ai-review`: `{text,provider,expected_revision,approved:true}` plus idempotency key. Returns a pending `world-job` with purpose `upload-duplicate-review`. `GET filmmaking/episodes/{id}/upload-ai-review/{review_id}` returns `{id,status,provider,revision,result,error,mock}`. The UI polls while pending. Requests use deduplicated saved fields, without reference image payloads or saved version histories. Restarted or failed requests are not retried automatically; users can retry explicitly or use local comparison. Mock mode reports that no AI provider was contacted.

For AI choices, add the returned `result.review_job_id` to `upload-apply`, along with the source, review token and all existing required fields. The server loads the stored review, rechecks book/Bible/episode revisions, validates every choice and rejects overlapping/conflicting removals. Client-supplied paths, AI-generated rewritten descriptions and edits to the review payload are never used as mutation instructions. Original upload and prior saved state remain recoverable as documented above.


#### Props included in parent assets

Production review resolutions accept existing direct asset IDs, `new`, or `included:<catalog_asset_id>`. All uncertain mention IDs require a choice; exact matches may also be overridden explicitly. Direct matches remain category checked. Included matches apply only to props, whose parent must be a saved Location or Prop. Several mentions may use the same parent; reference images are deduplicated at handoff. Self-containment is rejected.

The AI can suggest `container_candidate_ids` separately from same-category `candidate_ids`; every suggestion still requires user selection. Existing completed plans without this new field remain reviewable. Included objects retain their original names and Prop category in manuscript and production directions. Only parent descriptions and references are reused. Applied plans and storyboard shots retain `contained_assets` with object names and parent IDs/names. No standalone prop is created for an included object.


## Efficient reads

### Workspace and media reads

Use compact display endpoints for navigation and monitoring. Existing complete
production, shot, script, draft, job and export endpoints retain their detailed
snapshots and revision behavior.

| Route | Behavior |
| --- | --- |
| `GET /agent/v1/workspace/status` | Small, owner-scoped `{revision, areas}` change tokens. Compare tokens for equality; they are opaque and may reset after restart. Areas cover productions, editing, video, image, stories, account and inspection. This read does not initialize writers or inspect media. |
| `GET /agent/v1/productions/{id}/summary` | Production details plus compact episode/scene titles and shot rows: revisions, status, selection, image thumbnail source and take metadata. Omits series archives, full scripts, full media drafts and generation request snapshots. Fetch `productions/shots/{id}`, `stories/episodes/{id}` or the existing complete outline when that information is needed. |
| `GET /agent/v1/scenes/{id}/jobs` | History for one saved video scene, including old snapshots that uniquely match that scene. |
| `GET /agent/v1/image-studio/drafts/{id}/jobs` | Image jobs for that draft and its version family, scoped to the current workspace mode. |
| `GET /agent/v1/editing/export-summaries` | Export progress, errors, delivery links and snapshot metadata, without the snapshot's clips/audio/titles/captions/markers. Use `editing/exports/{id}` for the complete immutable snapshot. |
| `POST /agent/v1/library/page` | Read-only library search/pagination. Body: `{collection, query, filter, offset, limit}`. Collections: all, images, videos, scripts, assets, uploads, exports. Query is at most 200 characters; limit is 1–100 (default 40). Response: `{items, originals, total, offset, limit, has_more}`. Card `record` values are summaries. `originals` supplies full-resolution image download metadata for this page. |

For `POST /agent/v1/editing/inspect`, the original `{source}` request still waits
for inspection and returns loudness for audio. An explicit `analyze_loudness: false`
skips loudness while still resolving accurate source metadata. Optional
`{source, background: true, analyze_loudness: false}` returns basic/cached metadata
immediately, with `inspection_status` (`ready`, `pending`, or `uncached`). It never
downloads an uncached take in background mode. Request `analyze_loudness: true`
only when audio normalization needs it. `loudness_current` says whether cached
analysis is available. Re-read after the `inspection` change token changes.
Source-version results persist locally; optional analysis uses at most two workers.
The queue accepts at most 32 distinct pending sources and a later read can retry
when capacity is available. No provider generation is involved.

The human app uses one visible-page change monitor, completion-based scheduling,
request deduplication and revision checks. Agents should likewise avoid overlapping
polls, downloading complete histories to monitor one job, or treating summary
records as complete editable snapshots. Obtain the latest detail and its revision
before writing. All prompt checks, generation authorization, idempotency keys,
reference approvals and candidate review requirements still apply.

Small browser previews use the authenticated `/api/previews/{image|take|upload}/{id}/{160|320|640|1280}?workspace=...`
route. Workspace must match the active browser session. Cached previews are private;
original media and full-resolution download URLs stay unchanged. Video posters are
made only from already-cached local files, with one worker. `X-Preview-State`
reports ready, pending, uncached or unavailable. Pending placeholders are not cached.


### Portable project archives

`POST /agent/v1/productions/{id}/export` with `{}` starts a background export.
`GET /agent/v1/project-archives/{id}` returns `status`, `progress`, `message`, and
on completion `report`, counts and the local browser `download` URL. Poll until
`done` or `error`. Exports never generate media; active project jobs must finish
first. The archive excludes credentials and unrelated workspace content.

ZIP upload/download use the local browser session: `POST
/api/project-archives/import` accepts a raw ZIP body (Content-Type
`application/zip`, local Origin and `X-Tester: local`); `GET
/api/project-archives/{id}/download` streams the finished ZIP. These browser routes
require a workspace session. Import always creates fresh project/asset IDs.
See the User guide for archive contents, completeness reporting and size limits.

## Uploaded recording references

Uploaded WAV/MP3 recordings can be attached to full Grok Video 1.5 drafts at
480p/720p. The scene compiler assigns `<AUDIO_0>` to the recording, just as preset
voices receive audio tags. An optional character association adds its name to
that mapping. Remove preset voices explicitly before attaching a recording.

This implementation uses the documented `reference_audios: [{"url": "..."}]`
contract. xAI documents custom recording access as restricted to trusted partners.
Account entitlement and exact song/lip synchronization remain **unverified**.
Validation succeeds locally with a warning; only a live provider response can
establish account acceptance. There is no silent preset or unconditioned fallback.

Local upload/trim/preview routes and SDK helpers are unchanged:

- `GET audio-references/schema`: implementation support and access status.
- `POST audio-references`: `{name, base64}` with an Idempotency-Key.
- `GET audio-references/{id}` and `/download`: private source metadata/bytes.
- `POST audio-references/{id}/excerpts`: `{start_s, end_s}`.
- `GET audio-excerpts/{id}` and `/download`: private exact excerpt.
- Revisioned scene PATCH `changes.recording`: `{reference_id, excerpt_id,
  character_id?}`; `null` removes the attachment.

Local policy accepts WAV/MP3 up to 64 MiB, sources up to one hour, and excerpts
up to 15 seconds. These are local limits, not verified provider format limits.
No trim changes the shot duration or time-stretches the source. Validation reports
mismatches through `effective_audio_reference` and warnings.

**Submission lifecycle:** local validation performs no upload or network exposure.
After explicit generation approval, the worker starts an isolated one-file HTTP
server on loopback and exposes only its random audio path through the `cf tunnels
quick-start` CLI. The cf CLI must be installed. No Cloudflare account is required.
This development relay closes on job completion/failure and has a one-hour limit.
It never exposes the Studio server or a directory. Anyone holding the full random
HTTPS URL can access the excerpt while the relay is active; no credentials are
included in the URL. Provider failures are reported without automatic retry.
No paid generation occurs from preview or validation. Custom-audio API entitlement
and singing fidelity remain unverified until a real provider render succeeds.
Quick Tunnels are for development/testing; use stable, controlled storage for a
production deployment.

Immutable source/excerpt records retain their hashes. Per-generation
`audio_provider_uploads` records transport, hash, size and maximum lifetime,
without storing a bearer URL. `provider_upload_id` remains null for relayed audio.
Request snapshots freeze the exact recording bytes privately with an audio tag
and hash, alongside the starting frame and visual references.

```python
source = client.upload_audio_reference('/private/vocal.wav', idempotency_key='vocal-import-v1')
excerpt = client.prepare_audio_excerpt(source, 0, 9)
draft = client.attach_audio_reference(draft, source, excerpt, character_id=leo_id)
validation = client.validate(draft)  # inspect warnings and exact effective inputs
# Only after reviewing the concrete request and approving provider use:
# job = client.generate(draft, approved=True, idempotency_key='singing-pilot-v1')
```

Contract sources:
https://docs.x.ai/cookbook/examples/photo-to-talking-character
https://docs.x.ai/developers/files/managing-files
https://docs.x.ai/developers/files/public-urls


### Live recording pilot limitation (2026-10-27)

Live job `674861d1f88a41c8b3a46c4c85304cf1` uploaded the WAV but failed before video submission. The xAI Files public-URL endpoint returned HTTP 400: audio content is unsupported (allowed types listed images, MP4/WebM and PDF). The service classified the WAV as `application/octet-stream` despite the multipart audio/wav declaration. Do not disguise audio as an accepted media type. An alternative provider-fetchable audio URL transport is required; custom recording entitlement on the video endpoint remains untested. Public URLs must inherit the expiring file lifetime (`json={}`), rather than request another full hour after upload. Mock transport tests do not prove live audio support.


### Live HTTPS transport and account denial (2026-10-27)

The one-file relay supersedes the failed xAI Files audio-public-URL approach.
Live job `cfd9417867864ed087ea00a68ec5756b` verified 1,728,138 bytes against the
recording SHA-256, then reached the video-generation endpoint. xAI returned HTTP
403: `Caller-supplied URLs in reference_audios are not enabled for this team.`
No video request ID/output was returned. The relay stopped afterward. This
confirms a team capability denial on this connection; it does not establish
that OAuth can never receive partner access. Have xAI enable the capability
before retrying. Do not attempt alternate credentials or substitute preset speech.

## Song Performance workspace

Plan song-clock shots, review take windows and assemble separate working edits
inside Studio. See Song Performance (internal record omitted from public source) and the
complete Agent API example (internal record omitted from public source). Local import/analysis works
without custom-recording generation permission; no planning action generates video.

Workspace account status keeps `identity_provider` and `grok_identity_available` separate from `grok_connection`: Grok subscription access is not a Studio identity provider. `grok_connection.signed_in` reports the saved connection; `verified: false` means this read did not contact xAI. Use the explicit Grok model-access check to verify it without generating media. Connection checks time out with a recoverable message.

To record a directly authored video prompt, POST `scenes/{id}/review-prompt` with `expected_revision`, `reviewed: true`, and `authored_by: "agent"` (or `"human"`). Validation returns `prompt_provenance` and `prompt_review_provenance`, including whether the review is current. Edits invalidate its revision. This records review only; generation still requires separate human authorization.

### First-frame prompt tags

`<IMAGE_0>` stays in the compiled prompt intentionally. It is xAI positional prompt syntax; `image` is the JSON field carrying the pinned first frame. With `image` set, the starting frame takes `<IMAGE_0>` and `reference_images` starts at `<IMAGE_1>`. Without a starting frame, references start at `<IMAGE_0>`. Last frames and keyframes use their separate controls, not extra numbered reference positions. Studio validates this mapping and rejects missing positions. See [xAI reference-to-video input ordering](https://docs.x.ai/developers/model-capabilities/video/reference-to-video). No live generation was needed to verify the documented contract.

Dialogue preflight adds the non-blocking `dialogue_timing` warning for explicitly quoted spoken lines when `word_count / 2.5 + 1` exceeds the clip duration. The extra second reserves about 0.5s at each end. Script and prompt copies are not counted twice. This is an estimate; the app never edits dialogue, duration or shot structure automatically.


## Workshop prompts, image-sourced Bible changes, and Grok usage

All `filmmaking/series/{id}/...` routes accept either the linked story series ID
or the production ID. Resolution happens before lookups, saved foreign keys and
generation fingerprints, so replaying a generation key with either ID returns
the same batch. An unknown ID asks for a production ID or linked series ID.
Episode routes continue to take episode IDs; `worlds` routes take production IDs.

The character template requests **one image with exactly four views: full body
front, full body side, full body back, and head close-up of the face**. No fifth
or three-quarter view is requested. A caller-supplied prompt is retained verbatim;
the caller must include the four-view instruction when requesting a sheet.

AI writing is optional. To submit your reviewed wording directly through the
workshop, POST `filmmaking/series/{id}/generate` (or the existing `episodes` /
`worlds` generate route) with a unique `Idempotency-Key` and:

```json
{
  "job_id": "workshop-job-id",
  "model": "gpt-image-2",
  "approved": true,
  "requests": [{
    "view_id": "annie-main-view-id",
    "expected_revision": 1,
    "prompt": "Annie in her Bible outfit. One sheet, exactly four views: front, side, back and head close-up of the face. Same identity in every view.",
    "reviewed": true,
    "authored_by": "agent"
  }]
}
```

`reviewed: true` attests review of that request's prompt and inputs; it does not
authorize spending. `approved: true` still requires explicit human approval for
the concrete paid request. `authored_by` accepts `agent` or `human` (direct
workshop requests default to `agent`). Missing review fails live preflight before
submission. Alternatively save/review the linked image draft using the existing
`image-studio/drafts/{id}/review-prompt` route, then generate through the workshop.
Current AI preparations continue to work. No writer or provider retry is added.
`prompt-draft` and render-setting saves retain current reviewed text and review.
The job stores manual review provenance; creative edits invalidate that review.

Poll the returned render and image jobs and inspect the actual candidate. POST
`filmmaking/assets/{view_id}/confirm` with `expected_revision`, `asset_id`,
`approved: true`, and optionally `image_layout`. Layout accepts `main` (default),
`front`, `side`, `back`, `head`, or `character_sheet`. Use `character_sheet` only
after verifying the actual image contains the four required views. Candidate names come from the generation layout: `character_sheet: true` or
`image_layout: "character_sheet"` produces a Character sheet candidate; single
views use Main image or their explicit view layout. Confirmation preserves that
layout unless explicitly changed. Existing incorrect names can be renamed locally. Prompt intent does not certify the
pixels. Single-view images can be confirmed normally as the main identity.
Ordinary confirmation never rewrites descriptive Bible fields.

To deliberately prefer an image's appearance over the Bible:

1. POST `filmmaking/assets/{view_id}/bible-change-preview` with view
   `expected_revision`, `expected_entity_revision`, `asset_id`, and a `changes`
   map of descriptive profile fields, for example `{"hair":"Red"}`, or
   `reference_ids: ["asset-id"]` (up to five available images). Optional
   `image_layout` has the values above. It accepts an available main-reference
   candidate belonging to this view, not a foreign image or outfit variation.
2. Inspect the returned `id` and `diff` entries (`field`, entity `before`,
   `bible_before`, `after`). No generation, AI inspection, approval or Bible edit
   occurs during preview; the proposal is stored locally for confirmation.
3. With explicit user confirmation, POST
   `filmmaking/assets/{view_id}/bible-change-confirm` with `preview_id`,
   `approved: true`, and `authored_by: "agent"`. Only the stored proposal is used;
   changed entity/view/book/image-review revisions require a new preview.

Confirmation keeps the image, updates the owning Series Bible, Episode Book or
legacy world and entity/reference description, and appends an audit event with
`source: "image"`, `asset_id`, `preview_id`, exact diff, confirmer and time.
Reconfirming an applied preview is idempotent. Saved episode/request snapshots
are retained. Default handling of mismatches is rejection followed by an
explicitly approved new generation; there are no automatic Bible edits or retries.

`GET /agent/v1/usage` keeps its existing provider keys and `remaining` /
`used_today` fields. Grok adds `balance_available: false` and a plain explanation
that the connected subscription bridge does not provide the subscription balance.
`rate_limit_observation` is null until xAI returns supported headers through an
existing account check, image submission/poll or video submission/poll. Otherwise
it contains `source`, `scope`, `observed_at` (Unix seconds) and `rate_limits` with
allowlisted header names and original values. Observations persist in the private
workspace; they are last observed values, not live counters or guaranteed quotas.
Account/model headers are labeled `grok_account`, never attributed to a media
endpoint. Rate limits, per-request usage and app request counts are not a remaining
subscription balance. Reading usage neither generates media nor guesses a balance.
The UI shows the same unavailable-balance statement and dated rate-limit data.

`StudioClient` exposes `usage`, `generate_workshop`, `confirm_workshop_image`,
`preview_image_bible_change` and `confirm_image_bible_change`; the existing generic
`request` method remains supported. Generation approval defaults to false.


## End-to-end Storybook and workshop operations

Place and prop templates emit each structured description, lighting, time and
purpose once; display summaries are not appended a second time. Trailing sentence
punctuation is normalized before joining style text.

`answers.aspect_ratio` on the Series Bible / Episode Book is an optional image
aspect default (`16:9`, `9:16`, `1:1`, `3:2`, `2:3`). Without an explicit setting,
a recognizable ratio in the saved style is honored, otherwise it defaults to
`16:9`. Character sheets keep their existing `3:2` layout. Place/prop template
text and the compiled provider request both use the view draft's `settings.ratio`.
`PUT filmmaking/assets/{view_id}` with `{expected_revision, ratio}` explicitly
changes only this view; `expected_revision` is its **view revision**. Unreviewed
automatic wording is rebuilt for that ratio; a reviewed custom prompt stays saved
and requires review of its changed inputs. Users can override the ratio in the
image development Generate panel. Explicit user prompt text is never rewritten
merely to change an aspect setting.

`PUT filmmaking/entities/{entity_id}` saves entity metadata without editing image
drafts. To refresh particular unreviewed template drafts explicitly, include
`refresh_view_ids: ["view-id"]`. No other drafts are touched. Drafts that have ever
been AI-prepared/reviewed or manually reviewed retain their exact saved prompt,
even if named in this list. Changed creative context can invalidate a review
without erasing its text or provenance. Opening or saving a workshop also does
not rewrite existing drafts.

Episode Book reads add `linked_entities` with entity ID/name/category,
`linked_revision`, `source_revision`, `source_changed`, `source_missing`, saved
`identity_asset_id` and `source_identity_asset_id`. Links are frozen snapshots;
source changes never silently refresh them. The UI shows **Source changed**.

- `POST filmmaking/episodes/{episode_id}/storybook/refresh-links` takes
  `{expected_revision}` for the **Episode Storybook**, not episode/scene/view
  revisions. It explicitly refreshes selected entity snapshots and any guide
  cards linked through `series_asset_id`. Other book content, shared style,
  scripts, storyboard references and generated media stay fixed. Stale revisions
  or unavailable source entities fail without changing snapshots.
- `GET filmmaking/episodes/{episode_id}/storybook/readiness` is read-only. It
  returns `book_revision`, `ready`, `needs_images` and `entities`. Every linked
  entity includes `confirmed_main_image` (`asset_id`, `src`, or null),
  `needs_main_image`, and the stale-source fields above. A newer source image does
  not count as this book's image until the user refreshes the link.

Candidate names record generation layout, rather than assuming all outputs in a
main slot are single images. `character_sheet: true` labels the generated output
**Character sheet**; an explicit `image_layout` can also name `main`, `front`,
`side`, `back` or `head`. Providers can still fail to render the requested layout;
inspect the pixels. To correct an old or mismatched name, POST
`filmmaking/assets/{view_id}/rename-candidate` with view `expected_revision`,
`expected_review_revision` from the candidate, `asset_id`, and a `title` without
an extension. This updates the candidate title and download filename while
preserving bytes, layout metadata, approval and immutable request history.

`preview_image_bible_change` also accepts `changes.reference_ids`, a list of at
most five available local image IDs. All ordinary image validation applies.
The candidate being deliberately kept may be referenced before its confirmation;
other generated references must already be approved. Preview validates the list
without saving it; confirm revalidates and applies the stored proposal with the
same explicit approval and audit rules. Clearing the list with `[]` is supported.

For paid-step previews, POST
`filmmaking/{series|episodes|worlds}/{id}/generation-preview` with the same
`job_id`, `model` and `requests` used for generation. No approval or idempotency
key is required because preview neither saves drafts nor calls a provider. Each
request uses the **view** `expected_revision`, and the response separates
`view_revision` from `draft_revision`, includes the compiled request/aspect, and
returns `usage` before approval. Image/video validation and prompt-writing status
reads also include `usage`. The workshop and Storybook UI display allowance status
before generation/writing approval.

The real Grok subscription balance is still **unavailable through the connected
OAuth bridge**. The preview explicitly returns `balance_available: false`,
`remaining: "unknown"`, the reason, and any separately labeled, timestamped
rate-limit observation. Studio does not treat rate limits, per-request usage,
API prepaid credits or local generation counts as a subscription balance. Grok's
own [usage instructions](https://docs.x.ai/grok/faq) describe Settings → Usage;
they do not supply a subscription-balance endpoint for this integration.

`generate_workshop(identity, job_id, requests, ...)` accepts the series or
production ID for `scope="series"` and `scope="worlds"`; `scope="episodes"`
requires an episode ID. `job_id` is the owning workshop's `job.id`. Request
`expected_revision` must be the view revision, and conflicts report its current
value explicitly. A missing/mismatched workshop job error identifies the expected
job/production rather than telling an already built series to build again.

`/api/assets/{id}` is a browser/media URL requiring a session or Bearer header;
it is not a public link. Agent code should use
`download_image_candidate(image_job_id, asset_id, destination)`, which retrieves
`/agent/v1/image-studio/jobs/{image_job_id}/outputs/{asset_id}` with the workspace
token. Missing browser/session credentials now explain this distinction; valid
Bearer downloads remain workspace-isolated.

SDK helpers: `preview_workshop_generation`, `refresh_storybook_links`,
`production_readiness`, and `rename_image_candidate`. Docstrings specify each
ID/revision domain. Image-to-Bible helpers retain their existing names.
