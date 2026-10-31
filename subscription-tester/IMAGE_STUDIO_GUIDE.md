# Image Studio

Image Studio is part of Imagine Studio, alongside Video Studio. Both share an image library and named asset library. Image providers have separate account connections and usage pools. Image controls live in their own workspace; video controls stay in Video Studio. The installed service serves a prebuilt interface. Source changes require the frontend build described in the README.

!Image Studio with the existing SampleHero asset

## Agent collaboration — October 16, 2026

[Agent draft handoff](USER_GUIDE.md#work-with-an-agent) can share pending image settings, AI instructions/writer selection, the prepared-prompt review editor and Precision operations. Browser control permission is separate from read-only sharing. Each published editor lists its available save/reload/discard actions, and requests fail if its captured state changed. Agents can save through the normal revision-checked image API and request a reload in the originating editor. Identity verification and generation approval remain human controlled.

Camera Control reference PNGs can also be rendered locally through the API, then transferred into the linked image draft. See the [camera export contract](AGENT_API_REFERENCE.md#local-camera-control-reference-export).

## Create a consistent frame

1. Open the shot’s image workspace. The canvas stays visible above **Compose**, **Review & use**, and **Versions**.
2. Choose saved assets and select their views. The source limit is five for Grok or GPT Image 2 through Codex, sixteen for GPT Image 2.5 through the API. Native Codex shows “1 image per request”; connections supporting multiple outputs offer 1, 2 or 4.
3. In **Compose**, describe the image or the changes you want. Choose the Prompt AI connection and press **Prepare prompt with AI**. This starts writing only, then presents an editable prompt for review. **Use reviewed prompt** returns it to Compose. Instructions survive refresh and tab changes.
4. Alternatively choose **Write / edit prompt myself**, enter the generation prompt, and press **I reviewed this prompt**. This records explicit review of the current draft revision without an AI writing call. Changes to creative inputs invalidate that review; review again before generation. Saving only model, quality, resolution or candidate count preserves it.
5. Press **Generate image** as a separate action. OpenAI API models require the visible charge-approval checkbox. Output details, billing notes and compiled request are folded away; blocking errors remain visible.
6. In **Review & use**, compare the result with its base, select/deselect it for the shot, download, refine, edit a region, save a reference, add an asset view, or transfer to Video. Selecting for a shot approves the image and chooses it; deselection retains history and appearance approval. Standalone images use **Approve image** before reuse.
7. **Versions** contains drafts and generation attempts for this shot. Open a draft to resume editing, inspect a prior result, or reuse its settings. Viewing a version never changes the chosen image automatically.
8. The shot’s outline menu supports Rename & details, Duplicate shot, and Move to trash. Undo or **Shot trash & image branches → Restore shot** restores it with its media and versions. Old refinements with a verified base-image link are offered for explicit reassociation; names alone never determine ownership.

The request count and image approval are separate. Approval to spend usage permits one image request. Approval of its appearance permits video use. You can undo appearance approval; video validation will then block using that local candidate until it is approved again.

## How identity persists over time

The model does not remember SampleHero from a previous request. New compositions send the selected identity images and descriptions. Refinements send the base image and only additional references the user explicitly chooses. It translates local names into plain titles and a numbered source-image description in the prompt. Those names and categories are local organization, not provider-side asset IDs.

Image drafts and history preserve **snapshots** of each attached asset. Editing or archiving the shared library does not silently replace those snapshots. Use **Edit** on a card in **Your Assets** to open the shared asset editor. Saving updates the library and that current draft, including renamed prompt mentions. Selected image views survive reordering; removed views are deselected for review. Other drafts, video scenes and completed generations retain their snapshots. To adopt a library edit made elsewhere, remove and reattach the asset. Use **Add shot** for another story shot. **New image version** in a shot creates a new composition draft within that shot. **Reuse settings** restores the exact earlier prompt, source selections and snapshots.

For long-lived consistency, upload original identity images and back them up with `.state/studio/`. A remote URL can change or expire; the app does not archive remote URL contents. Use a small, carefully curated set of original views. Avoid repeatedly replacing canonical identity images with generated variations: small errors can accumulate.

Reference conditioning improves consistency but does not guarantee pixel-identical characters or locations. Every candidate needs visual review. There is no training, custom identity model, seed control or Grok.com library synchronization in this feature.

## Refine and reuse

**Refine this image** creates a new image version in the same shot, with the candidate as its base and an empty change brief. Original asset snapshots remain available, but their views are deselected and loose references omitted by default. The base is input image 1 and consumes one source slot. Expand **Additional references** only to introduce or restore something; **Use base image only** deselects extras on an older draft. The original image and shot selection remain intact. Describe changes in Compose, prepare or write a prompt, review it, then generate separately.

Candidates are saved as actual local PNG, JPEG or WebP files, rather than expiring output URLs. Download them, approve them, or reopen them from history. Loading a different image draft clears unrelated previews. Saved drafts autosave and are shared with agents. Concurrent edits use revisions; on conflict, choose **Saved drafts → Save local draft as copy**, or discard local edits and reload.

## Provider request and limits

The Grok model is `grok-imagine-image-2.0`. Plain prompts use `POST https://api.x.ai/v1/images/generations` with `n: 1`, `2` or `4`. Requests with visual inputs use `POST https://api.x.ai/v1/images/edits`, with `image` for one source or `images` for multiple sources. Each source uses `{type: "image_url", url: ...}`. Local asset files become base64 data URLs; public HTTPS inputs remain URLs. Requests use JSON, not multipart. Both generation and editing use `deferred: true` and `response_format: "url"`. The server saves the returned `request_id`, polls `GET /v1/images/{request_id}`, then downloads each successful candidate into local storage.

| Control | Values |
| --- | --- |
| Aspect ratio | `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `3:2`, `2:3`, `2:1`, `1:2`, `19.5:9`, `9:19.5`, `20:9`, `9:20`, `21:9`, `5:2`, `auto` |
| Resolution | `1k`, `1.5k`, `2k` |
| Quality | `low`, `medium`, `auto` |
| Sources per edit | At most five in total |
| Outputs per app request | 1, 2 or 4 |

Automatic quality currently chooses Low for text generation and Medium for editing; Automatic is the app default; choose Low or Medium to pin quality. This is described in the [official generation documentation](https://docs.x.ai/developers/model-capabilities/images/generation). Source ordering and the five-image limit follow [multi-image editing](https://docs.x.ai/developers/model-capabilities/images/multi-image-editing); refinement follows [image editing](https://docs.x.ai/developers/model-capabilities/images/editing). Read-only documentation snapshots are in `docs/images-*-2026-10-02.md`.

The **4,096-character expanded Grok image prompt ceiling is a conservative local policy** and is not a confirmed xAI image API limit. GPT Image 2/2.5 drafts use a 32,000-character local ceiling; the native subscription transport may impose additional restrictions. `prompt_limit_chars`, `image_output_limit_mb` (20 MB), `image_timeout_seconds` (180 seconds), and upload limits are configurable in `studio-config.json`. Drafts may contain longer text but cannot generate until the expanded prompt validates.

First/last/keyframe transfers obey existing video model rules. Only Video 1.5 and Video 1.5 Lite accept new work. Lite accepts a starting image; references, voices, last frames and keyframes require Video 1.5. Keyframe timestamps use one-third-second slots, strictly inside the duration, with no duplicate slot and at most four anchors. Transfer preserves the video settings and retags positional image references when adding a first frame. Different image/video ratios can stretch the frame.

## Subscription, errors and mock testing

Image Studio reuses the existing server-side Hermes OAuth session. It introduces no xAI API key or credit fallback, browser cookies, or Grok credentials. Tokens remain out of browser responses and logs. It posts directly to Imagine image endpoints; the app cannot choose xAI’s Build/Imagine usage attribution or promise equivalent subscription rates.

Existing earlier requests established account access to other image/video workflows. **Image Studio’s Image 2.0 editing entitlement and subscription charge have not been live-tested.** A separate approved real test is needed. The endpoint capability docs primarily show API-key examples, rather than proving this specific model’s subscription entitlement. A rejected request never switches to API credits.

Only one account operation runs at a time. An image request executes in a background server thread; the browser polls the local job. It is never automatically resubmitted after a timeout, network failure, server restart or rejection. Check the error, history and account usage before deciding on another request. Grok jobs with a saved request ID offer **Resume existing job** after interruption, timeout or server restart. Resume only polls that saved request; it never submits another generation. Partial downloads are retained by candidate index. New generation for the same draft is blocked until its recoverable request finishes or you explicitly discard recovery. History offers **Discard recovery** for failed recoverable jobs, with confirmation. It preserves cached candidates, the original settings and provider request ID, and writes a local audit entry. Discarding does not cancel work at xAI or refund usage; it unlocks the draft so you can choose another model or make a new request. Active jobs cannot be discarded. Provider results expire after 24 hours, so resume promptly. If submission failed before an ID was saved, check usage before choosing a new request. OpenAI synchronous/native requests cannot safely resume after process loss.

Provider result downloads from the exact hosts `imgen.x.ai`, `images.x.ai` and `api.x.ai` support transparent proxy DNS in `198.18.0.0/15`. This exception applies only to output URLs returned by the Grok result response. User-supplied references still require public HTTPS addresses, even on those hosts. Other private destinations remain blocked; redirects stay disabled, no OAuth headers are sent to image downloads, and image format/size checks remain in force. No broad proxy trust setting is needed for this range.

For no-usage testing, start a separate mock server:

```sh
.venv/bin/python studio_server.py --port 8876 --state-dir /tmp/imagine-image-studio-mock
```

Connect the mock account, upload a sample identity image, attach an asset, compose a prompt and approve a mock image. The result is a **geometric test pattern**, not an AI-generated example or proof of identity fidelity. Test approval, refinement, download and transfer without xAI calls. Mock and live candidate history are separated by mode. Use a separate state directory to keep test assets out of your working library.

## Agent interface

The existing private local agent token protects `/agent/v1/image-studio/*`. Browser controls and agents share the same persistent image draft and history. Discover exact allowed values with `GET image-studio/schema`, and the expanded request with `POST image-studio/drafts/{id}/validate`. Do not place provider credentials in requests.

| Route after `/agent/v1/image-studio/` | Method | Action |
| --- | --- | --- |
| `schema` | GET | Model, defaults, allowed values, local limits |
| `workspace` | GET / POST | Read current draft; select `draft_id` or create a draft |
| `drafts` | GET / POST | List or create image drafts |
| `drafts/{id}` | GET / PUT | Read or replace settings with `expected_revision` |
| `drafts/{id}/validate` | POST | Validate and preview exact expanded request |
| `drafts/{id}/generate` | POST | One approved request; `expected_revision` and `Idempotency-Key` required |
| `jobs` / `jobs/{id}` | GET | History or status/output |
| `jobs/{id}/download` | GET | First cached candidate, for compatibility |
| `jobs/{id}/outputs/{asset_id}` | GET | A specific cached candidate |
| `jobs/{id}/resume` | POST | Resume a recoverable Grok request; no new submission |
| `jobs/{id}/reuse` | POST | New draft using original settings |
| `jobs/{id}/refine` | POST | New refinement draft using `asset_id`; optional `prompt` |
| `jobs/{id}/approve` | POST | Set reviewed `asset_id` to `approved: true` or `false` |
| `jobs/{id}/transfer` | POST | Add approved candidate to video scene |

Example preparation, with **no generation**:

```python
from agent_client import StudioClient
c = StudioClient()
draft = c.create_image('SampleHero at the workshop', {
    'prompt': '@SampleHero studies a blueprint at a wooden desk. Warm evening light, medium wide shot. Preserve its defining features.',
    'ratio': '16:9', 'resolution': '1k', 'quality': 'low'
}, named_references=['SampleHero'])
c.request('image-studio/workspace', 'POST', {'draft_id': draft['id']})
validation = c.validate_image(draft)
assert validation['valid'], validation['errors']
```

After specific human permission to spend usage, generate with `c.generate_image(draft, approved=True, idempotency_key='unique-human-approved-request')`, then `c.wait_for_image(job['id'])`. Repeating that key returns the original job; using it for different settings is rejected. Do not invent a new key to automatically retry.

After human appearance review, call `jobs/{id}/approve` with its output `asset_id`. Transfer uses `asset_id`, `scene_id`, `expected_revision`, and `target` (`first`, `last`, `keyframe`); keyframes additionally require integer `slot = seconds × 3`. Set `replace: true` only with explicit intent to replace an occupied first/last frame. Transfer returns the updated video record; select it with `POST /agent/v1/workspace` and `scene_id` if the browser should open that scene. No transfer makes a generation request.

## OpenAI model choices

| Choice | Authentication and billing | Controls |
| --- | --- | --- |
| OpenAI Image 2 · subscription | Official native Codex image tool; existing ChatGPT login and Codex allowance | Automatic size/quality; aspect ratio is prompt guidance |
| Image 2.5 Flare · API | Server-side OpenAI API key; separate API billing | Documented pixel sizes and quality controls |
| Image 2.5 Sunburst · API | Server-side OpenAI API key; separate API billing | Same controls; model emphasizes editing precision |

The Image 2 native route is tied to the installed Codex implementation; the generation result does not independently confirm image model identity. It exposes no documented Image 2.5 selector. Native image turns can consume more Codex allowance than text turns; no per-image subscription debit is shown in this app. See experiment evidence.

API model IDs are `gpt-image-2.5-flare` and `gpt-image-2.5-sunburst`. Text generation uses JSON at `/v1/images/generations`; references/refinements use multipart `/v1/images/edits` with ordered `image[]` files. The compiled panel represents local input intent: reference data is converted to files for API edits, or temporary local files for the native tool. Secrets are excluded. The native tool receives the compiled prompt and ordered reference paths, with shell tools and configured MCP servers disabled for the ephemeral session.

API quality choices are `low`, `medium`, `high`, `xhigh`, `max`, `auto`; pixel choices are `auto`, `1024x1024`, `1536x1024`, `1024x1536`, `1536x864`, `864x1536`. This app offers a documented subset of dimensions. Explicit dimensions determine shape; ratio is additional prompt guidance. See the [official Images guide](https://developers.openai.com/api/docs/guides/image-generation).

Selected assets, immutable snapshots, refinement, approval and video transfer work the same across providers. A change of model clears spending approval. A missing key, subscription login failure, timeout or provider rejection never triggers a fallback or automatic retry. Check history and provider usage before approving another attempt. OpenAI API entitlement and billing have not been tested with a real generation in this integration.

## Save an approved image as a reusable reference

Select a generated image in Image Studio and approve it. Click **Save as reference** beneath the preview. The existing editor opens with the generated image attached, **Location** selected, and editable title, mention name and description suggested from that image's saved generation prompt. Change the category to Character or Prop when appropriate; preset voice controls appear for Character. Review the description to keep durable identity details rather than one-scene actions. Save, then use the named reference through **Choose saved assets** in Image Studio or **References** in Video Studio.

Suggestions run locally using prompt wording, with no AI request or usage charge. They do not inspect the image or guarantee that the text matches its pixels. The original generation snapshot is used even if you have since edited the draft. Existing mention names receive a numeric suffix to avoid duplicates. Every field is editable. Saving keeps the original approved image; you can add more views in the editor.

For a one-scene video reference without making a named asset, **Use in video → Reference image** adds the approved image to a saved scene. This respects model restrictions and the 14-reference-image limit on Video 1.5.

### Start a new video scene from an approved image

Click **Use in video**, choose **＋ New scene** in the scene picker, and enter its title. Choose First frame, Last frame, Reference image or Keyframe (with an interior time). Click **Create scene & add image**. Video Studio opens the saved scene for review with the image placed. New scenes start with the standard 5-second Video 1.5 settings; adjust them before generating. No video generation is submitted by this action. Existing scene placement remains available.

### Automatic assets from image prompts

Image Studio automatically attaches saved assets whose exact `@Handle` appears in a typed, pasted or loaded prompt. Matching ignores case; repeated mentions attach one copy. Each new asset starts with its first image view selected, which you can change under Your Assets. Existing snapshots and selected/deselected views stay unchanged. Removing a mention does not remove an attached asset; remove the mention before removing its card to prevent reattachment. Unknown/archived names, assets without images and the selected model’s source limit produce validation messages and block generation until corrected. Free a slot and edit/save the prompt again to attach an asset that previously did not fit. No AI call or generation is involved.

### Usage confirmation

Subscription actions start directly from **Generate video**, **Generate image**, or Story Studio’s send button. They no longer require a separate usage checkbox. OpenAI API image models retain **Approve OpenAI API charges**, which resets when settings change or a request is submitted. Switching to an API model requires fresh approval. Image appearance review (**Approve image**) remains required before using a generated image in a video or saving it as a reference. No generation runs automatically at startup.


### Model-specific prompt limits

The complete expanded prompt includes scene direction, saved reference descriptions and composition guidance. GPT Image 2 and the supported GPT Image 2.5 API models use a 32,000-character local limit, based on OpenAI's Images API reference. GPT Image 2 subscription generation uses the native Codex transport: that transport may impose additional restrictions, so the API limit is not a guarantee of subscription acceptance. Grok retains the configured local limit (currently 4,096); its published image-generation documentation does not establish a prompt character maximum. Model profiles in `image-studio/schema` report `prompt_limit_chars` and `prompt_limit_basis`. Draft text is retained when changing models; expanded-prompt validation decides whether generation can proceed.

Source: https://developers.openai.com/api/reference/resources/images/methods/generate

### Prepare an animation opening frame from a storyboard shot

Click **Image** (or the preview) on any storyboard shot. Image Studio prepares an opening-frame description with the selected image provider's writing connection: ChatGPT/Codex for OpenAI image models, Grok for Grok images. This uses subscription writing allowance; the image itself is generated only when you click **Generate image**.

Preparation reads the saved scene script, shot action, neighboring shot directions, visual style, creative rules, canonical asset descriptions and confirmed included-object relationships. It describes the first visible instant of this particular shot, keeping later motion as context. Exact `@handles` connect visible identities to saved reference snapshots. Existing view selections remain intact; additional references are attached within the selected model’s image-source limit. If a reference cannot fit or an identity is uncertain, review notes explain it. Prompts are validated against the selected model's full expanded character budget.

An unchanged starter storyboard prompt is populated automatically. If you already edited the prompt or generated an image, a side-by-side comparison lets you choose **Use this opening-frame prompt**. Prior settings are backed up, and **Previous prompt & prepared version** provides comparison and revision-protected restoration. **Prepare again** explicitly requests a new AI interpretation using your current image model. Reopening an unchanged prepared shot reuses its result. Failed or interrupted requests preserve existing work and never automatically retry. Scripts, earlier book chapters, asset identities, video directions and generated takes are preserved.

### Returned model and candidate counts

Jobs store `requested_model`, `returned_model` (null when absent), and `model_identity` (`confirmed` or `unconfirmed`). History displays both requested and served identity. A successful request alone does not confirm which model served it. Native Codex results currently provide no model identity; the app does not invent one. Grok deferred responses may omit it as well.

Discover `counts` and `deferred` per model through `image-studio/schema`. Put `n` in image draft settings. Select outputs by their own `asset_id`; approval, refinement, reference export and transfer never approve sibling candidates. `StudioClient.resume_image(job_id)` continues an existing Grok job, and `download_image_candidate(job_id, asset_id, destination)` saves the chosen candidate. Each generated candidate consumes usage.

Implementation was tested with local mock media and mocked provider responses on October 9, 2026. Those checks do not verify this account's 1.5k, Lite or deferred-job subscription entitlement or actual provider media quality.

GPT Image 2 through the installed Codex native tool accepts five source images. GPT Image 2.5 through the API accepts sixteen. Both counts include the refinement base. Grok retains five. The schema exposes models[model].max_sources; its top-level max_sources remains the Grok default for compatibility. No model switching discards saved sources.

### Upload a video take to a shot

In the shot workspace, choose **Upload video** beside **Shot details & takes**.
Upload an MP4, MOV or WebM clip up to 64 MB, set its source label (for example Seedance),
and choose whether to select the clip for the shot. Originals are stored locally without
resizing or transcoding. Uploaded takes support playback, download, frame capture and
Edit timeline sources. Earlier takes and generation settings remain available. Uploaded
clips have no recorded provider request, so automated prompt-comparison review is not
available for them. Failed attachments can retry using the already stored upload.

## Short-film reference preparation — October 27, 2026

See the [Grok Imagine prompting guide](../docs/prompting-guides/Grok_Imagine_Prompting_Guide.md). Before
video, approve the character/costume state, reusable location and actual composed
starting frame. Check neighboring shots for faces, wardrobe and light. Use the
Bible's approved style and explicitly selected image references; inspiration
cards alone do not attach generation inputs.

A compact face/front/rear sheet on neutral gray can be authored as a reviewed
custom prompt. The built-in World Builder sheet still uses five views; this
update does not add a layout selector or change an approved sheet. Preserve the
project's art style, attach the base identity for variants, and keep different
ages/costumes clearly labeled. Correct a flawed starting still before spending
video generation allowance.
