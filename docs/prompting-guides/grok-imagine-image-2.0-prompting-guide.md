# Ultimate Prompting Guide: Grok Imagine Image 2.0 (`grok-imagine-image-2.0`)

**Audience:** the built-in writer in Imagine Studio (ChatGPT/Codex or Grok) and agents writing image prompts directly. Follow this same model guide on either path. Use it whenever you write, repair or expand a prompt that will be sent to Grok Imagine Image 2.0 through Image Studio, World Builder (character, location, prop sheets), the storyboard opening-frame preparer, or a refinement/edit draft.
**Verified:** 2026-10-09 against the app code (Documents/Imagine Studio, working tree), the xAI docs snapshots saved in `docs/imagine-capability-audit-2026-10-09/`, docs.x.ai, and third-party guides (URLs in section 17). Items marked **[UNVERIFIED]** were not confirmed by xAI docs or a live test.

**Integration corrections:** 2026-10-09. The authoring contract below records the agreed implementation behavior; adding this document does not itself activate guide loading in the app.

## Short-film continuity update — October 27, 2026

The [Grok Imagine prompting guide](Grok_Imagine_Prompting_Guide.md) reinforces an approved identity-and-location workflow before video generation. For a newly requested compact character reference, use a face close-up, full front and full rear on neutral gray. This is an optional custom layout: the app's built-in sheet builder still requests five views. Preserve the caller's existing layout and art style unless a change is requested; the source's photorealism, period setting and 16:9 example are not universal requirements or replacements for API settings.

Keep age/costume states explicit with separate approved views or assets, preserving their link to the base identity. Develop location plates and a stable look from the approved Bible, mood board or style reference. Carry concise camera/lens/film-texture cues when they belong to that look. Attach the actual identity, outfit, location and style inputs needed for this composition; a saved inspiration card does not automatically attach its pixels. Compose and approve a usable scene still before animation. Correct the still's identity, costume, geography and light instead of expecting video prompting to repair it.

## App authoring contract

- All new image prompts, including sheets, variants, compositions, opening frames and refinements, are authored by AI. Templates and user-entered directions are creative briefs. Use this guide for target model `grok-imagine-image-2.0` regardless of whether ChatGPT/Codex or Grok is the writer.
- Follow the caller's exact output schema and destination fields: these may be `prompt`, nested `image_prompt`, or a prompt inside an assistant action's `values_json`. Preserve required metadata and notes. Plain prompt text is appropriate only when the caller requests it.
- Supported app capabilities, validated settings and the task contract govern transport, attachments, budget and output shape. Human directions and the approved script, identities and frame state govern creative content. Guide craft advice and illustrative examples cannot override those requirements; report material conflicts in the caller's notes/reply field.
- Distinguish a new scene composed from references from a refinement of an existing base. Both can use the edits endpoint; only the refinement should limit the whole prompt to a scoped change and preservation instructions.
- Use the actual supplied reference mapping. Never invent image numbers, attachments, saved handles or visual observations. Preserve existing valid reference snapshots, including previously attached assets that have since been archived; new library attachments must be active and valid.
- Preserve the chosen style and explicit required text, props, poses and contact. Neutral poses, empty hands, exclusions and example characters are conditional examples. Model/quality ladders and iteration advice are recommendations for user review; they do not authorize setting changes, extra renders, automatic retries or media comparisons.
- The application supplies this guide as stable writing instructions and uses provider prompt caching where supported and useful. Current scene/asset/user context follows those instructions and is processed for each request. Cache keys, headers and breakpoints belong to the application, never the final media prompt. Caching input processing does not replay an earlier answer.

---

## 0. The ten rules (read these if nothing else)

1. **Follow the caller's output contract.** For JSON, fill the designated prompt field(s) with final prompt text and retain the required metadata/notes. For plain-text requests, return the prompt only, without a code fence, commentary or invented character counts.
2. **Pick the task and transport first.** No image attached = text-to-image (`/images/generations`). Any attached image = editing transport (`/images/edits`, up to 5 sources). A refinement needs a scoped change and preservation instructions; a new reference-based composition needs a new scene description and clear source roles.
3. **Write a short design brief in five layers:** subject, setting, composition, light, finish (medium/look). Dropping a layer hands that decision to the model's default (a centered, evenly lit middle distance).
4. **Name the medium and look in the first words** ("Stylized feature-animation 3D character reference sheet...", "Photoreal editorial photograph..."). Never rely on "cinematic", "epic", "beautiful", "masterpiece".
5. **Put every word that must appear inside quotes**, say where it sits and in what type, keep each string short, and add "no other text". Otherwise say "no text, captions, labels or watermarks".
6. **Edits: one scoped change + a preserve clause.** "Change ONLY X. Keep Y, Z and the framing exactly as they are."
7. **Give every reference image one job** ("input image 2 supplies the jacket only; ignore its background and pose").
8. **State the trait you want, never the one you do not** (positive wording). Naming an unwanted attribute can anchor it.
9. **Draft cheap, finish once:** low quality at 1k to explore, medium (and 2k for dense text/fine detail) for the keeper. Change one variable per retry.
10. **Fix the reference before the wording.** If the same defect appears twice, the cause is usually the attached image or the mode, not your adjectives.

---

## 1. Purpose and scope

Grok Imagine Image 2.0 is xAI's image model for text-to-image and image editing (docs: "ultra-realistic photography to anime, oil paintings, and pencil sketches"). It is strong at: following dense briefs, planning typography and layout, factual/real-world detail, region-scoped edits, and multi-reference compositing. This guide tells you how to turn Imagine Studio project data (series visual style, characters, locations, props, shots, camera notes) into prompts that land in one or two tries.

Not in scope: video prompts (see the Grok Imagine Video guide), GPT Image prompts (see the GPT Image guide). Stills you generate here usually feed video as first/last frames, keyframes or reference images, so keep them video-ready (section 11).

---

## 2. What Imagine Studio does with your prompt (integration notes)

Read this section so you do not duplicate what the app already adds.

| App behavior (from code) | Consequence for you |
|---|---|
| `@Handle` mentions: the app finds exact `@Handle` text, attaches that saved asset's selected image views, **replaces `@Handle` with the asset's saved title** in the prompt, and appends a block: `Visual references:` + one line per asset `Category: Title — input image(s) N, M. <saved description>` + `Preserve the supplied asset identities, proportions, materials and defining details. Follow the scene instructions without redesigning these assets.` | Use only handles that exist. Put `@Handle` where the subject is introduced (once is enough). Do **not** write the `Visual references:` block, and do not repeat the saved description; add only scene-critical details. In dialogue/quoted text use the plain name. |
| Source images are numbered **1-based in the appended text** ("input image 1", "input image 2"). Order: refinement base first, then each attached asset's selected views, then "extra" references. | Refer to images by role *and* by that number ("input image 1 is the approved character; keep its face"). Do not invent numbers that are not in the app's list. See the numbering caution in section 3. |
| **Limit: 5 source images total** (base + asset views + extras). | Plan which views matter (usually 1 per asset). If a scene has 4 assets, use 1 view each plus at most 1 extra. Never ask for more. |
| Expanded prompt limit for Grok: **4,096 characters** (a local, conservative app policy; xAI does not publish an image prompt maximum). The count includes the appended Visual references block (~150 chars of boilerplate + every asset line) and `@Handle`→title substitutions. | Write the scene text short: **600-1,400 characters** typical; leave room for descriptions. Character sheets built by World Builder are capped at 2,700 chars and locations at 4,096. If you cannot fit, shorten the scene text, never the identity details. |
| Request body the app sends to xAI: JSON, `model`, `prompt`, `aspect_ratio`, `resolution`, `quality` (omitted when "auto"), `n` (1, 2 or 4), `deferred: true`, `response_format: "url"`; sources go in `image` (one) or `images` (several) as `{type:"image_url", url}`; local files are inlined as base64 data URLs. | These are API fields. **Do not write aspect ratio, resolution, quality, "4K", "high quality", "2k" into the prompt as controls.** |
| The app saves each result as a local PNG/JPEG/WebP candidate; you (or the user) **approve** a candidate before it can be used as a video frame/reference or saved as a reusable reference. | Write prompts for reusable masters (neutral, clean) when the output will become a reference. |
| World Builder prompt builders already exist (`world_workshop.py`): character 5-view sheet, location scouting, prop reference, 8 coverage angles, outfit variants. `Grok_Imagine_Prompting_Guide.md` covers video. The storyboard **opening-frame preparer** has its own policy (image-to-video first frame). | When asked to write or improve these prompts, keep their structure and caps and add the rules below. Keep "No captions, labels or watermarks." |
| Series **visual style** (`answers.style`, ≤200 chars in sheets) is appended as "Series visual style: ..." / "Look: ..." in World Builder prompts. | Reuse that exact style line verbatim in every image prompt of the series so shots cut together. Do not paraphrase it per shot. |

---

## 3. Modes, parameters and what the app exposes

### 3.1 API field vs prompt text

| Setting | Where it lives | Values (docs) | Exposed in Imagine Studio? |
|---|---|---|---|
| `aspect_ratio` | API field | `1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 2:1, 1:2, 19.5:9, 9:19.5, 20:9, 9:20, 21:9, 5:2, auto` (docs: default `auto` = model chooses; for edits the output follows the first input image unless you set one) | **Yes**, all values; app default **16:9** (always sent, so edits do *not* follow the base image unless the user sets `auto` [see 3.3]) |
| `resolution` | API field | `1k` (default), `2k`; REST schema and pricing page also list `1.5k` | App offers `1k`, `1.5k`, `2k` (code and the Oct 9 upgrade note). **[UNVERIFIED: xAI's generation docs page lists only 1k/2k; 1.5k comes from the REST schema/pricing page and has not been live-tested on this account]** |
| `quality` | API field | `low`, `medium`, `auto` (auto = low for generation, medium for editing; only on 2.0) | **Yes** (`low`, `medium`, `auto`; auto = field omitted) |
| `n` | API field | 1-10 | App: 1, 2 or 4 candidates (`counts=[1,2,4]`). Each candidate is an independent asset: separate selection, approval, refinement and download |
| `response_format` | API field | `url` (default), `b64_json` | Fixed by app (deferred jobs need `url`) |
| `deferred` | API field | true → `request_id`, poll `GET /v1/images/{id}`, kept 24h | Used by the app for every Grok image request: it saves the `request_id`, polls `GET /v1/images/{request_id}`, and offers **Resume existing job** after a timeout/restart (no new generation). Failed, moderated or expired (24 h) requests are terminal |
| Edit sources | API field | up to **5** images (URL, data URI, or `file_id`) | Yes, ≤5 total; no provider `file_id` input |
| Mask / region edit | not an xAI field | — | The app's Precision "edit region" only adds a prose sentence on Grok ("Edit only the region from x% to x% across ..."). It is **not** a pixel mask on Grok. |
| Seed, negative prompt, guidance, steps, LoRA | not available | — | **Not available in Imagine Studio** (and not in the xAI image API) |
| Prompt text | prompt | no published limit | App local cap 4,096 chars |

### 3.2 What you control in prose
Subject, setting, composition (shot size, angle, lens behavior), light, medium/finish, exact text, layout, what to preserve, reference roles. Nothing else.

### 3.3 Reference numbering and aspect caution (important, verify when possible)
- xAI's REST reference says that with several edit images you refer to them as `<IMAGE_0>`, `<IMAGE_1>` (zero-indexed) in the prompt; a third-party test (Fuser, 2026-09-28) confirmed both tags landed correctly.
- The app does **not** write those tags for stills; it writes "input image 1/2/..." (one-indexed) in the Visual references block. **Do not mix schemes in one prompt.** Refer to each image by *role plus the app's number* ("input image 2, the red leather jacket") and keep roles unmistakable, so an off-by-one cannot swap them. **[UNVERIFIED: the app's numbering has not been live-tested against Grok; if a result swaps two references, state roles by description only and re-run.]**
- Because the app always sends `aspect_ratio` (default 16:9), a refinement of a 2:3 image will be recomposed to 16:9 unless the draft ratio is set to match or `auto`. When you write a refinement, tell the user in notes (if the schema has a notes field) to keep the draft ratio equal to the base image or `auto` (third-party: Fuser says `auto` in edit mode keeps the first input's ratio).

---

## 4. The prompt: required elements and default order

Write full sentences in one flowing paragraph (or 2-4 short labeled lines for sheets). Default order for **text-to-image**:

1. **Medium + purpose first** (what this image is and what it is for): "Stylized feature-animation 3D character reference sheet for a series", "Photoreal editorial photograph", "Flat 2D TV-cartoon episode screenshot".
2. **Subject**: who/what, 2-4 identifying traits (age, build, hair, signature clothing/material, scale). Use the canonical title; the app attaches the saved description.
3. **Action/pose/expression** (stills show one instant; no sequences).
4. **Setting**: where, time of day, 1-3 concrete anchor details.
5. **Composition**: shot size, angle, camera height, lens behavior (wide-angle with straight verticals, telephoto compression, shallow depth of field), where subjects sit in the frame.
6. **Light**: source, direction, quality, color temperature. Highest-leverage single line.
7. **Finish/look**: the series style line, palette, texture callouts.
8. **Exact text**, if any: quoted, with placement and type.
9. **Constraints/locks**: preserve lines, positive end-state locks, "no captions, labels or watermarks".

Order for **edits**: (a) the change, (b) the target (where), (c) the preserve clause, (d) reference roles, (e) text/finish only if affected.

Elements checklist (all must be answered; omissions get invented):

| # | Element | Ask yourself |
|---|---|---|
| 1 | Medium & purpose | Is the look named in the first words? |
| 2 | Subject | Are the 2-4 identity traits stated? Skin tone/species/scale named? |
| 3 | Pose/action | One frozen instant, hands and gaze stated? |
| 4 | Setting | One location, time, 1-3 anchors? |
| 5 | Composition | Shot size + angle + height + lens? Where is empty space (for later video action or UI text)? |
| 6 | Light | Source, direction, quality, color? |
| 7 | Finish | Style line (verbatim), palette, texture? |
| 8 | Text | Quoted, positioned, short, "no other text"? |
| 9 | Locks | What must not change/drift, stated positively? |
| 10 | References | Each image has one job and a number? |

---

### Objective, brief vs prompt, priorities, pose (from the user-supplied Codex video guide; transferable parts only; unverified third-party input)
- **Objective first:** know in one sentence what this image must communicate before writing; each sentence should serve it.
- **Brief vs prompt:** the script/brief is not the prompt. Translate it into visible, concrete directions for this model; never paste explanatory prose ("the scene is about loneliness").
- **Priorities and continuity:** control identity, the story-critical element and exact text; do not demand equal precision for incidental background. Prefer one lock line ("preserve the reference character's exact body proportions and face design") over repeating long descriptions.
- **Pose for character images:** concrete body language (head angle, gaze target, where each hand rests, weight on which foot, held stillness), not mood words; faceless or stylized characters carry emotion through posture, head tilt and gesture. Numeric angles are optional craft **[UNVERIFIED]**.
- **Constraints:** one short last line of only what must not appear (extra people, text, watermark); long prohibition lists dilute the prompt. Cinematic lens wording ("35mm perspective") is a look cue only.

**Aspect ratio in prompt text:** Grok Image receives the selected ratio through its API field; omit duplicate ratio/resolution/quality controls from the authored prompt. The compiler owns technical composition settings. Include a prose ratio sentence only when the caller explicitly requires one and establishes that no compiler sentence will be appended. An older opening-frame instruction to include ratio must be reconciled with the selected transport during integration. Camera position/lens and framing remain creative prompt content.

**Honesty and defaults:** never claim an image or tag is attached unless saved settings establish it; never claim visual verification of images you cannot see; never state an unmeasured length or promise identical identity or success. Image Studio's backend `create`/`edit` auto-attaches known active `@Handle` mentions with an image view when slots permit, including API requests; the video API separately requires explicit `named_references`. Validate the resulting bindings instead of relying on prose. Library edits do not mutate a draft's saved snapshot: use the image draft's explicit `refresh-reference` action to adopt the latest version and review selected views, or deliberately remove/re-add when appropriate. Preserve the user's style; all examples here are illustrative data.

## 5. Length and density

- Typical scene prompt: **60-180 words**. Sheets: 90-220 words. Edits: **20-70 words** (short, specific; long edit prompts re-describe the picture and cause drift).
- Past a point, detail competes with itself (Runware guide): every clause must carry weight. Cut filler adjectives; keep concrete nouns, materials and numbers ("exactly five", "one per hand").
- When a scene has lots of elements that must be right (crowd, vehicles, signage, reflections), **name them and their counts**; the model's factuality improves when the checkable items are listed.
- Hard app ceiling: 4,096 chars for the whole expanded prompt (section 2). Measure when the app gives you the compiled count; never invent a count.

---

## 6. Text rendering (posters, labels, signage, UI)

Grok 2.0 plans typography and layout like a designer. Rules that worked (xAI-hosted guides, Runware, Fuser tests with 1k and 2k):
1. Quote the exact string; describe type ("tall condensed white sans-serif", "small serif caps") **and** position ("top third", "lower right under the product").
2. Keep strings short (a headline + one info line tested clean; paragraphs untested). For body copy, leave clear space and set the type in post.
3. Say how many times it appears ("exactly once") and add "no other text".
4. Dense or small text: ask for 2k (set the `resolution` field) and keep each string short; iterate layout at 1k.
5. A few words still glitch (an X user reported "price"→"prince" three times; Grok's own account advised quoting the exact term or fixing text after generation). If a word fails twice, change it, spell it in capitals, or composite it afterward. Do not loop more than 2 retries.
6. For on-product text (a mug, a label) add "keep the lettering exactly as in input image N" on edits.
7. If a character sheet or reference must contain **no** text: "no text, captions, labels, numbers or watermarks."

---

## 7. Editing with references (single and multi-image)

- Edit = `/images/edits`; the prompt is an instruction. Direct verbs: change, replace, remove, recolor, relight, restyle, add, move.
- **One operation per request.** Bundling ("change the label, the background and the light") yields three half-changes. Chain edits: use each output as the next input (the app's "Refine this image" does this; the base is input image 1 and uses one of 5 slots).
- **Always include a preserve clause** naming what must stay: identity/face, pose, product geometry, logo and lettering, camera angle, framing/crop, lighting, background, materials. This is what separates an edit from "a new image inspired by the source".
- **Local vs global:** local edit = precise target + strong preserve clause; global restyle = style direction + "keep composition, subject identity and framing".
- **Multi-image composite** (≤5): assign roles. Example: "Input image 1 is the character: keep face, hair and outfit exact. Input image 2 is the location: use only its architecture and light. Place the character at the desk in input image 2." Say what transfers and what to ignore (background, pose, palette, layout).
- Style transfer works; xAI docs list multi-turn editing and style transfer as supported.
- The app's `@Handle` flow attaches assets as references on the **edits** endpoint even for a "new" scene, so a scene with attached assets is an *edit with composition*, not pure text-to-image: describe the new scene, the roles, and "preserve the supplied identities".
- Region edits in the app on Grok are prose-only (see 3.1): describe the region in plain words ("the left sleeve") as well as the percentage sentence the app adds, and expect leakage; review the whole frame.

---

## 8. Consistency across a series

Grok has **no seed, no memory, no identity model**: consistency is built from attached images and repeated text.
1. **Series style line:** establish concrete construction, line, shading, eyes, hands and palette from the selected style, then reuse the approved line verbatim. Expand ambiguous style labels into visual cues when preparing that line; do not replace the user's chosen style or canonical identities.
2. **Approved masters first** (character sheet, location plates, prop sheets). Attach 1 master view per asset per shot; do not attach lower-fidelity generated variants as identity (errors accumulate).
3. **Style anchor:** after the first approved image in a style, attach it as a reference with the role "style and rendering only" and keep later prompts short ("In the same art style, ...").
4. **Lock lines** (add the ones the scene needs): character lock ("same face, hair, build and outfit as input image 1"), prop lock ("the brass lantern is in his left hand"), blocking lock ("always on screen-left of the door"), palette/light lock, count lock ("exactly one robot, one dog").
5. **Height lineup image** for casts: all characters side by side on neutral grey with a count lock and a measurable height rule ("his head reaches her lower chest"); reuse as a reference.
6. **Feature lock** for a drifting feature (usually eye color): state the wanted value positively ("rich medium-brown irises"), optionally add a macro close-up reference.
7. **Variants (outfit, age, condition):** reuse the sheet format, attach the approved master, anchor ("the same character as input image 1, same face and proportions"), state only what changes.
8. Consistency is **not guaranteed**; the app warns "Visual consistency requires review". Always review face, silhouette, proportions, colors, clothing, props.

---

## 9. Templates (fill from project data)

Placeholders in `[]`. Project data sources: **STYLE** = series visual style line; **CHAR** = Character asset (title, appearance, outfit, palette); **LOC** = Location asset (description, lighting); **PROP** = Prop asset; **SHOT** = storyboard shot (size, angle, action, light, neighbors).

### T1. Generic scene still (text-to-image or with attached assets)
```
[MEDIUM + PURPOSE, from STYLE]. [@Subject] [2-4 identity traits only if not in the saved description] [one frozen pose/expression/gaze], in [LOC, time of day, 1-3 anchors]. [Shot size] at [camera height/angle], [lens behavior]; [subject placement and clear space]. Light: [source, direction, quality, color temperature]. Look: [STYLE line verbatim; palette]. [Quoted text with placement, or "No text, captions or watermarks."] Preserve the supplied identities; [one or two lock lines].
```

### T2. Character reference sheet (World Builder compatible; 3:2)
Default = the app's 5-view layout. Alternatives from the catalog in 9.2.
```
Create one polished character reference sheet with exactly four clearly separated views on a flat neutral [#B5B5B5] background: full body front, full body rear, full body side, and a head close-up of the face. Same face, proportions and outfit in every view. Neutral standing pose, relaxed arms, empty hands, neutral expression, flat even light, full figures uncropped with generous spacing, at least 8% margin around each view.
Character: [CHAR title]. [Gender/age/ethnicity-or-species/height/build/hair/eyes/skin as short fields.] Appearance and distinguishing details: [CHAR description, ≤600 chars]. Main outfit: [outfit, materials, colors].
Series visual style: [STYLE]. Identity color palette: [3-5 colors].
No captions, labels, numbers, text or watermarks.
```
Outfit sheet (identity-conditioned, input image 1 = approved master): "Use input image 1 as the approved character identity. Preserve face, hair, body, age and rendering style. Change only clothing and accessories; the reference outfit must not override the requested outfit. Requested outfit ([name]): [details]." Then the same layout lines.

### T3. Location plates (scouting, empty of people; 16:9)
```
[MEDIUM from STYLE] location reference: [LOC name]. Establish coherent geography, architecture, scale and atmosphere: [layout in 2-3 spatial statements: where the entrance, window wall, focal furniture are]. Wide establishing shot at [eye/low] height, deep focus, no people, no text. Light: [LOC lighting: source, direction, quality, time of day]. Materials: [3 concrete materials]. Look: [STYLE]. Color palette: [..]. Leave [open floor/foreground] clear for action. No captions, labels or watermarks.
```
Split exterior and interior into separate plates when action crosses a threshold. The 8 coverage angles (Wide, Medium, Close-up, Aerial, Low angle, Reverse, Interior, ...) attach the approved main plate as input image 1: "Consistent [angle] of the same place. Preserve geography, architecture, colors and materials from input image 1."

### T4. Prop reference (neutral gray; 1:1 or 3:2)
```
Clean reusable prop reference: [PROP]. Show the complete object, silhouette, construction, materials and defining details in four views on neutral gray: front, rear, three-quarter detail, profile, consistent scale. [Materials and wear in physical terms, e.g. "brushed aluminum with worn edges, one cracked left lens"]. [Any legible marking: "the engraved word 'ORBIT' on the handle, exactly once"]. Neutral uncluttered background, flat even light, no people. Look: [STYLE]. No captions, labels or watermarks.
```
Prop from a photo: "Use input image 1 as the object. Preserve its shape, markings and proportions exactly; change only [wear/condition]."

### T5. Storyboard opening frame (first frame for image-to-video)
Mirror the app's opening-frame policy: the **earliest visible instant** of this shot, one static composition (no montage, no motion instructions), state carried over from preceding shots, outcome of later action NOT depicted.
```
[MEDIUM + aspect-appropriate framing]. [Shot size] from [position], [lens]. [Visible characters by canonical @name with the scripted initial pose, expression, gaze and position]; [held props, contact and object state at the first visible instant]; [location layout and background details]. Light: [..]. Look: [STYLE]. Context only (do not render): next, [action].
```
Rules: no unrequested characters, dialogue or text; leave room for motion; preserve the scripted mouth state, held props and contact at frame one; frame on where the action happens. A closed-mouth waiting pose is appropriate only when the script and continuity call for it.

### T6. Single scoped edit (one image attached)
```
[Verb] [exact target] [to what]. Keep [identity/face], [pose], [geometry], [lettering "..."], [camera angle and crop], [lighting and background] exactly as in input image 1. Do not change anything else.
```

### T7. Multi-reference composite (≤5)
```
Create [shot description]. Input image 1 is [subject]: keep [features] exact. Input image 2 is [style/location/prop]: use only [attribute]; ignore its [background/pose/layout]. [Placement and interaction]. Light: [..]. Match [lighting/grade] to input image 2. No extra characters, no text.
```

### T8. Poster/label/infographic (text-heavy)
```
[Format] for [use]. Layout: [top third: headline "..." in [type]; center: [visual]; lower right: [info line "..." in small caps]]. Style: [medium, palette]. Light: [..]. Render each quoted string exactly once, no other text, no watermarks.
```
(set `resolution` 2k in the app for dense text)

---

### 9.1 Style rules to fold into any prompt (from the Imagine Studio style catalog)
- Do not rely on "cinematic" alone. Name the selected medium, construction, lighting and finish. Describe shots in plain words (static eye-level medium-wide). Flat 2D styles generally avoid photoreal skin, lens effects and realistic shading; feature-animation 3D and photographed stop-motion can use depth of field, shadows and material texture consistent with their selected style. For photoreal work, use relevant camera/grade, texture and focal-plane cues rather than adding them to every animation prompt.
- Every animation style gets **a style line** (construction, line, fill, shading, eyes, hands) **plus a guardrail line** that blocks unintended drift. Expand style labels into concrete visual cues. Preserve the user's selected style and canonical character identities; combine styles only when the brief explicitly requests a coherent combination. Anatomy changes must fit that style while retaining the subject's required identifying traits.
- Frame animation stills as "a screenshot from a finished [era/genre] cartoon episode; one continuous in-episode frame, not promotional art; no hero pose or poster composition"; add a foreground edge (chair edge, cables) for depth.
- **Pixar-style 3D house look:** "stylised feature-animation 3D; production CG, not photorealistic, not flat cartoon; matte skin with subsurface glow, cloth with weight, tactile differentiated materials"; lighting designed (key direction and color, rim, bounce, practicals); palette as a ratio with one named saturated accent; appeal-driven design (one exaggerated feature paired with its opposite; silhouette readable in 3 words; one signature item). Image prompts short, no long avoid list; change a garment's design instead of "no logos".
- **Preschool / kids 3D (musical):** baby-schema proportions, oversized head ~1:2-1:3, saucer eyes ~a third of the face, pillowy zero-sharp-edge forms, plush/fleece materials with soft subsurface, clean PBR with soft GI, warm even key light, high-saturation primary palette. Animals upright "with no clothes or accessories". Human hero clearly taller than animals; lock with a lineup image.
- **Micro drama / photoreal live action:** background realism block in every environment prompt (one sharp focal plane, corners softer than center, highlights blown and shadows crushed, texture only on the focal plane); handheld written as operator physics; photoreal sheets = 4 views on neutral gray with soft key upper left and gentle fill right; never a dramatic grade on a sheet.
- Sub-style cue + guardrail pairs are in Appendix A (35 styles).

### 9.2 Character-sheet formats (choose by job; catalog)
- **4-view (app default):** front, side, back, head close-up of the face. Exactly four views in one 3:2 image.
- **3-panel (most widely used, all styles):** (1) front body from the collar down with **no head**, (2) straight rear full body, (3) three-quarter head-and-shoulders close-up with neutral expression and ≥8% margin. The headless body panel stops faces disagreeing and gives the face more detail. Lock the background with a hex code ("flat #B5B5B5 background") or an uploaded blank layout template ("Use input image 2 only as the empty three-panel layout; keep its equal vertical panels and divider lines").
- **4-panel:** full-body front three-quarter, full-body rear, front head-and-shoulders close-up, 90-degree profile close-up (photoreal sheets: neutral gray, soft key upper left, fill right).
- **Turnaround + 8 expressions** (neutral, happy, delighted, sad, surprised, confused, angry, talking): drifts more; test before committing.
- Defaults for neutral sheets: flat even light, neutral expression and empty hands unless the canonical brief requires a different expression or held item. Preserve required skin markings and tattoos; omit unrequested marks. Build the character from FIXED traits and SWAP lines, and distinguish each cast member from the others. A four-view prop sheet on gray is a useful format when requested. These defaults do not override the chosen deliverable or identity.

---

## 10. Worked examples
All worked examples use fictional demonstration data. Use saved assets for actual identities.

### E1. Character sheet
```
Create a four-view reference sheet of a fictional gardener wearing a green raincoat and carrying an empty watering can. Show exactly four views: front, side, back and head close-up. Keep proportions and clothing consistent. Use a plain gray background and even light.
```

### E2. Location plate
```
Create an empty greenhouse interior. A potting bench lines the back wall. A clear aisle runs from the entrance to the bench. Use soft morning light, glass panels and painted timber. Keep the aisle empty.
```

### E3. Prop sheet
```
Create four consistent views of a blue watering can on neutral gray: front, rear, side and three-quarter. Show its curved handle and long spout clearly. Use even light and no labels.
```

### E4. Opening frame
```
Create the first frame of a fictional gardening scene. The gardener stands beside the potting bench, hands at their sides, looking at an empty flowerpot. Use a locked medium shot at eye level. Keep the doorway visible.
```

### E5. Scoped edit
```
Change the watering can from blue to yellow. Keep its shape, position, lighting and everything else unchanged.
```

### E6. Multiple references
```
Use input image 1 for the gardener's identity, input image 2 for the watering can and input image 3 for the greenhouse architecture. Show the gardener holding the can beside the potting bench. Match the greenhouse lighting.
```

### E7. Poster with text (set resolution to 2k in the app)
```
A minimal gig poster. Top third: the headline "LATE NIGHT BLUE" in tall condensed white sans-serif letters. Center: a stylized silhouette of a saxophonist under a single warm spotlight on a deep navy background. Bottom: "FRI 14 NOV · 9PM · THE CELLAR" in small white caps. Swiss poster layout, subtle paper grain. Render each string exactly once, no other text, no watermarks.
```
(adapted from the Fuser-tested layout)

### E8. 2D TV-cartoon episode screenshot (style + guardrail)
```
Screenshot from a finished mid-1990s prime-time suburban sitcom cartoon episode; one continuous in-episode frame, not promotional art. Static eye-level medium-wide shot of [Character A] on the left and [Character B] on the right at a kitchen table, flat even lighting, opaque cel color, clean uniform dark outlines, simplified rounded anatomy, large white eyes with tiny pupils, minimal shadows, a chair edge in the foreground. Use one coherent shape grammar; do not combine recognizable traits from several unrelated shows. No gradients, glossy 3D surfaces or film grain. No captions or watermarks.
```

---

## 11. Making stills video-ready (Image Studio → Video Studio)
- Match the **image ratio to the planned video composition**. Image-to-video output follows the starting image's ratio; a conflicting requested ratio does not override that image. Resolve mismatches through the actual starting-frame preparation and app settings.
- **First frame:** the earliest visible instant of this shot, preserving preceding-shot continuity. Keep scripted held props, contact, mouth state and action already underway; do not force an idle pose. Show one static composition and preserve any required visible lettering.
- **Last frame / keyframes:** prepare related stills by editing the first frame when appropriate so the set shares a coherent scene. Grok Video 1.5 accepts up to four optional interior keyframes at configured timestamps; there is no app requirement for at least three keyframe images. Last/first frames are separate controls. Lite supports neither last frames nor keyframes. Prose does not attach or time a frame.
- **Reference stills for video reference-to-video:** one master per asset (sheet, plate, prop); neutral expression and flat light; no text; no multi-panel layouts in scene references (bind with "use only for character design").
- Hands and faces clean at the image stage (artifacts amplify in motion). Images are cheap, video is expensive.

---

## 12. Editing and iteration protocol
1. **Draft:** quality `low`, resolution `1k`, n=1 (or 2 when exploring a pose). Check composition, light, identity.
2. **Diagnose before rewriting:** list what is wrong in nouns ("hat missing", "eyes brown not blue", "two extra fingers"). If the same element fails twice → inspect the reference image/mode.
3. **Fix with an edit, not a re-roll,** when the composition is good: one scoped change + preserve clause.
4. **Change one variable per retry** (wording OR reference OR quality). Re-roll the whole image only if the composition is wrong.
5. **Finish:** keeper → `medium` (and `2k` for dense text or print-size detail). Auto resolves to low for generation, so set `medium` explicitly for finals (the app default is `auto`).
6. **Approve the candidate in the app** only after reviewing face, silhouette, proportions, colors, clothing and props.
7. When revising a prompt: open with what changed, output the full prompt, flag knock-on effects.
8. A persistent defect should lead to a proposed change of tactic (reference, mode or local compositing). Rewriting or rendering again requires a user-requested iteration; this guide does not authorize automatic retries or comparative media generation.

---

## 13. Pre-flight checklist (run silently before returning a prompt)
1. Correct task and transport? No images = generation; attached images = editing transport. A refinement has a scoped change/preserve clause; a new composition has clear scene direction and reference roles.
2. Medium named in the first words; no bare "cinematic/epic/stunning".
3. Subject has 2-4 identity traits (or relies on a named, attached asset); skin tone/species/scale named.
4. One frozen moment (no "then", no sequence); pose, gaze, hands stated.
5. Composition (size, angle, height, lens behavior) and light line (source, direction, quality, color) both present.
6. Series style line copied verbatim; use concrete craft cues and a relevant guardrail without replacing the user's chosen style or canonical traits.
7. Every `@Handle` has a valid attached snapshot or an explicit supported attachment request; new library attachments are active; total source images ≤5; each has a role; any numbering follows the supplied app mapping.
8. Quoted text short, positioned, "no other text" (or "no text" if none wanted).
9. Positive wording; no named unwanted attribute you are actually seeing.
10. Aspect/resolution/quality are controlled by the app; no duplicate or contradictory prose controls. Composition fits the planned video/destination.
11. Length: scene text fits (typical ≤1,400 chars; compiled ≤4,096 incl. asset descriptions).
12. Output matches the caller's plain-text or JSON contract, with final prompt text in the designated field(s).

---

## 14. Symptom → fix table

| Symptom | Likely cause | Fix |
|---|---|---|
| Misspelled / extra words | text not quoted, too long, no placement, no "no other text" | Quote exact short strings, add position and type, "exactly once, no other text"; 2k; if it fails twice, composite text after |
| Generic centered "stock" look | missing composition and light layers | Add shot size, angle, lens behavior, and light source/direction |
| Plastic/AI-sheen skin (photoreal) | vague "cinematic", no texture | Name camera/stock; ask for true micro-pores, fine skin texture; two texture callouts |
| Flat style drifts into 3D / wrong show | no style line or guardrail; show names used | Style line + guardrail line; one shape grammar; "transform the anatomy" |
| Character changes between images | no master attached; paraphrased style; many generated variants as refs | Attach the approved master (1 view), repeat style line verbatim, add character lock; avoid replacing masters with generated variants |
| Unwanted trait persists (e.g. blue eyes, hat) | you named it ("no blue eyes") or reference shows it | State the wanted value positively; fix/replace the reference image |
| Edit changed unrelated things | no preserve clause; several edits at once; long re-description | One change; list what to keep ("lighting, framing, lettering"); shorten |
| Edit recomposed to another shape | the app always sends `aspect_ratio` (default 16:9) | Set the draft ratio equal to the base image, or `auto` |
| Two references swapped / blended | no roles; numbering ambiguity | One job per image; describe each by role + app number; keep ≤3 inputs when possible |
| Reference background/layout leaks | reference not bound | "Use input image N only for [attribute]; ignore its background, pose, layout, panels" |
| Sheet shows the wrong views / panels merged | layout only described loosely | Count views, name each, lock background (hex or blank template), "generous spacing" |
| Sheet face disagrees between views | face in several views | 3-panel with headless body panel + one close-up |
| Drifting eye color / feature | feature small in frame | Positive value + macro close-up reference; keep tight close-ups out of video prompts |
| Height relationships wrong | not stated | Measurable comparison ("her head reaches his lower chest") + lineup image |
| Landscape comes back square (text-to-image) | `aspect_ratio` left at auto in the draft | Set the ratio field; do not write it in prose |
| Result looks rough | quality low (or auto → low) | Re-run keeper at `medium`; 2k for detail |
| Request rejected / empty | expanded prompt over 4,096 chars, unknown `@Handle`, >5 sources, moderation filter | Shorten scene; use real handles; deselect views; rewrite neutral wording if filtered |
| Cropped limbs/heads | not stated | "full figures uncropped, generous margin" |
| Extra people/objects | open-ended scene | Count lock ("exactly one ..."), "no other characters" |

---

## 15. Common mistakes
- Treating the prompt as a tag list (Grok reads full sentences/briefs).
- Re-describing the whole picture in an edit prompt.
- Putting aspect ratio, "4K", "high quality", "1:1" in the prose.
- Attaching 5 loosely related references with no roles.
- Using `@Handle` for assets that are not attached/approved; writing the Visual references block yourself; pasting the saved description again.
- "No X" lists as the main control (Grok has no negative-prompt field; state the positive instead).
- Paragraphs of in-image copy.
- Changing wording and reference and quality in the same retry.
- Generating sheets with a dramatic mood or action pose (carries into every later shot).
- Naming real shows/characters in the final prompt.

---

## 16. Not available in Imagine Studio / unreliable / unverified

**Not available** (do not write prompts that depend on them): seed or deterministic regeneration; negative-prompt field; pixel-mask editing on Grok (prose region only); provider Files (`file_id`) inputs; xAI Batch API; webhooks; custom-trained identity/LoRA; more than 5 source images; Smart Resize and the magic wand/segmentation (these are Grok app features, not exposed by this app or the xAI API docs I read); background removal as an API operation **[UNVERIFIED for API]**; image count `n` beyond 1/2/4 in the app.

**Unreliable:** exact spelling of some words; long paragraphs of text; strict counts in crowded scenes; exact hex colors; identical identity across generations (never guaranteed); consistency of small props.

**Unverified (flag in notes if relevant):**
- `1.5k` resolution on the generation docs (REST schema/pricing list it; docs page lists 1k/2k).
- Whether `auto` aspect ratio on edits always follows the first input (third-party Fuser claim).
- The app's one-indexed "input image N" convention vs xAI's zero-indexed `<IMAGE_n>` for stills.
- Whether the subscription (Hermes OAuth) route gives the same entitlement/quality as the API (the app's own docs: "Image 2.0 editing entitlement and subscription charge have not been live-tested").
- Whether Grok rewrites prompts internally: the REST usage schema reports tokens for a "prompt-rewriting (upsampler)" LLM, so a rewritten prompt likely exists; the app does not display it.
- Quality `auto` mapping (low for generation, medium for edits) is from xAI docs; arena rankings cite Grok Imagine Image 2.0 at Low placing #3 on the text-to-image arena (Aug 2026, X post by Arena).
- Prices (from the app's audit of docs.x.ai, Oct 9): $0.04/$0.05/$0.06 at low and $0.06/$0.07/$0.08 at medium for 1k/1.5k/2k, plus $0.01 per input image; the model page headline says $0.04 per image. Subscription billing may differ.

---

## 17. Sources (retrieved 2026-10-09)
- App: the application source and the three model guides included in this repository.
- xAI: https://docs.x.ai/developers/model-capabilities/images/generation , /images/editing , /images/multi-image-editing , https://docs.x.ai/developers/models/grok-imagine-image-2.0 , https://docs.x.ai/developers/rest-api-reference/inference/images , https://docs.x.ai/developers/migration/imagine-image-quality-nov-2 (on Nov 2, 2026 `grok-imagine-image-quality` redirects to 2.0 at low; select 2.0 explicitly).
- Runware, Grok Imagine Image 2.0 prompting and text-rendering guides (Aug 10-11, 2026): https://runware.ai/docs/models/xai-grok-imagine-image-2-0/guides/prompting , .../text-rendering
- Fuser (tested Sep 28, 2026): https://fuser.studio/articles/grok-imagine-image-guide
- Morphic: https://morphic.com/resources/how-to/grok-imagine-image-2-guide ; editing guide https://grokimagine2.io/grok-imagine-image-2-0-editing-guide (third party; claims about apps features are not API facts)
- X: @grok (2026-10-06, text glitch advice), @TheWhiteWitchTM (2026-10-06), @runware (2026-08-11), @arena (2026-08-10, leaderboard) via the X connector; low sample, treat as anecdotal.
- Codex guide "The Anatomy of a Great AI Video Prompt" (user-supplied PDF; unverified third-party claims; only transferable ideas used)
- Imagine Studio style catalog (YouTube-derived lessons and cartoonprompts.com styles).
- Today's date context: 2026-10-09.

---

## Appendix A: Animation style lines and guardrails (35)
Use the CUES as the style line and the GUARDRAIL as the drift-blocking line; keep identity (face, age, proportions, outfit, colors) while rebuilding it in the style's grammar. Source: cartoonprompts.com list, extracted 2026-10-03.

01. Rubber Hose [2D] - Elastic rhythm, pie-cut forms and vintage ink.
   CUES: Use a 1930s inkblot-cartoon language: flowing tubular arms and legs, pie-cut eyes, rounded forms, bold black contours, simple flat fills and rhythmic elastic curves.
   GUARDRAIL: Do not fake the style with sepia or film dirt; transform the anatomy while retaining the subject's identifying face and outfit.
02. Golden Age [2D] - Theatrical squash, painted warmth and confident line.
   CUES: Use polished 1940s–1950s theatrical cel animation: solid constructed anatomy, strong silhouettes, tapered ink contours, squash-and-stretch posing and opaque cel color.
   GUARDRAIL: Do not use jointless rubber-hose anatomy, limited-TV construction, heavy sepia or fake film damage.
03. Hanna-Barbera [2D] - Limited-animation economy with a readable silhouette.
   CUES: Use 1960s limited-TV animation: simplified geometric construction, bold clean contours, flat cel fills, minimal shading, readable silhouettes and economical jointed parts.
   GUARDRAIL: Do not add a tie or collar unless it belongs to the reference outfit, and do not render fluid theatrical motion or 3D volume.
04. Cartoon Network [2D] - Graphic shapes, modern timing and expressive clarity.
   CUES: Use a 1990s–2000s creator-driven cable-cartoon language: bold geometric silhouettes, varied thick outlines, asymmetrical exaggeration, high-chroma flat color and minimal shading.
   GUARDRAIL: Use one coherent shape grammar; do not combine recognizable traits from several unrelated shows.
05. South Park Cutout [2D] - Flat paper construction and deliberately stiff charm.
   CUES: Build the subject from flat layered construction-paper shapes with simple circular geometry, shallow overlap shadows, tiny mouth forms, rigid cutout posing and scanned paper texture.
   GUARDRAIL: No gradients, glossy vectors, rounded 3D toy forms or fluid anatomical posing.
06. 90s Cel Anime [2D] - Two-tone shadows, sharp ink and analog cel energy.
   CUES: Use analog 1990s cel-anime craft: precise inked contours, flat opaque colors, crisp two-step shadow shapes, restrained highlights, angular period design and subtle cel texture.
   GUARDRAIL: No bloom, airbrushed gradients, plastic 3D lighting or contemporary oversized moe eyes.
07. Studio Ghibli [2D] - Natural hand-drawn acting with restrained cel color.
   CUES: Use traditional hand-drawn Japanese feature animation: gentle pencil-like contours, natural proportions and gestures, simple expressive faces, flat opaque cel color, one restrained shadow tone and nuanced daylight.
   GUARDRAIL: Keep watercolor texture in backgrounds only; no chibi eyes, glossy airbrushing or fantasy wardrobe changes.
08. Pixar-style 3D [3D] - Rounded volume, tactile materials and cinematic light.
   CUES: Use stylized feature-quality 3D: a memorable rounded silhouette, sculpted appealing proportions, tactile differentiated materials, soft subsurface skin, plausible cinematic light and readable features.
   GUARDRAIL: No generic giant-eyed face, waxy skin, shiny vinyl surfaces or excessive depth of field; preserve the reference facial structure.
09. Spider-Verse Toon Shading [Hybrid] - Halftone print, offset color and graphic dimensionality.
   CUES: Blend dimensional modeling with illustration using expressive ink lines, bold graphic shapes, halftone dots and hatching instead of gradients, stepped-pose energy and limited chromatic misregistration.
   GUARDRAIL: No random graffiti, speech bubbles, comic panels or generic neon cyberpunk; the print language must shape the character.
10. Claymation [Practical] - Handmade volume, tactile surfaces and studio light.
   CUES: Use hand-built clay stop motion: softly sculpted forms, fine fingerprints and tool marks, slight handmade asymmetry, practical miniature-set lighting and grounded contact shadows.
   GUARDRAIL: No flawless CGI, glossy vinyl toy surfaces or oversized fingerprint grooves.
11. Simpsons-style [2D] - Prime-time sitcom shorthand and clean graphic shapes.
   CUES: Use clean prime-time sitcom-cartoon construction: flat yellow skin, bulging round eyes with tiny pupils, a pronounced muzzle or overbite, four-finger hands, uniform dark contours and saturated cel color.
   GUARDRAIL: Do not merely recolor normal anatomy yellow, copy an existing cast member or add dimensional 3D shading.
12. Dragon Ball Z-style [2D] - Forceful ink, angular forms and high-energy cel shading.
   CUES: Use late-1980s–1990s martial-arts cel anime: robust angular anatomy, sharp eyes, bold directional hair masses, dynamic tapered lines, flat colors, hard-edged shadows and forceful silhouettes.
   GUARDRAIL: Do not turn the subject into a muscular Super Saiyan, change the hair color, add an aura or replace the reference outfit.
13. Family Guy-style [2D] - Uniform outline, flat color and adult-sitcom economy.
   CUES: Use clean uniform outlines, simplified rounded sitcom anatomy, large white eyes with tiny pupils, flat bright colors, minimal shadows and tightly controlled on-model expressions.
   GUARDRAIL: No yellow skin, Simpsons proportions, painterly rendering or glossy 3D surfaces.
14. 2D Disney-style [2D] - Elegant line, expressive posing and painted cel color.
   CUES: Use classic hand-drawn feature animation: flowing tapered cleanup lines, appealing rounded anatomy, readable squash-and-stretch posing, luminous cel color and restrained painted shading.
   GUARDRAIL: No glossy modern 3D-princess treatment, generic anime eyes or fantasy wardrobe redesign.
15. 2.5D Mixed Media [Hybrid] - Paper texture, drawn ink and shallow layered depth.
   CUES: Build a shallow 2.5D collage from layered paper, ink and photographic textures with crisp cut edges, restrained depth, soft contact shadows and selective dimensional forms.
   GUARDRAIL: Do not turn it into a full glossy 3D render or an incoherent scrapbook with conflicting light and depth.
16. The Simpsons [2D] - Rounded sitcom forms, bold ink and bright cel color.
   CUES: Use clean prime-time sitcom-cartoon construction: flat yellow skin, bulging round eyes with tiny pupils, a pronounced muzzle or overbite, four-finger hands, uniform dark contours and saturated cel color.
   GUARDRAIL: Do not merely recolor normal anatomy yellow, copy an existing cast member or add dimensional 3D shading.
17. Johnny Test [2D] - Angular energy, elastic shapes and hot digital color.
   CUES: Use angular elastic silhouettes, wedge-shaped faces, oversized flame-like hair shapes, clean dark contours, hot saturated digital colors and sparse cel shading.
   GUARDRAIL: Do not turn the subject into generic spiky-haired shōnen anime or smooth the design into rounded feature-animation anatomy.
18. King of the Hill [2D] - Grounded proportions and restrained suburban color.
   CUES: Use restrained realistic caricature, grounded adult proportions, fine clean contours, muted warm suburban colors, minimal cel shading and understated expressions.
   GUARDRAIL: No loud adult-cartoon exaggeration, glossy 3D caricature or dramatic superhero anatomy.
19. American Dad! [2D] - Clean broadcast geometry and crisp shadow blocks.
   CUES: Use crisp even outlines, smooth geometric sitcom anatomy, tall refined proportions, large white eyes with tiny pupils, bright clean colors and simple hard-edged cel shadows.
   GUARDRAIL: Do not borrow Family Guy's rounder construction or impose Roger-like alien traits that replace the subject's own identity.
20. Peanuts [2D] - Wobbly hand ink, tiny forms and warm paper tones.
   CUES: Use sparse gently irregular hand-inked lines, oversized round heads, tiny bodies, dot eyes, economical expressions, muted flat colors, warm paper and generous negative space.
   GUARDRAIL: No polished vector geometry, gradients, plush-looking 3D forms or elaborate scenery.
21. SpongeBob SquarePants [2D] - Bouncy outlines and candy-bright graphic color.
   CUES: Use bouncy uneven ink contours, simple geometric and organic shapes, porous speckled details, candy-bright flat cel colors and highly elastic facial acting.
   GUARDRAIL: No glossy 3D children's rendering, realistic sea-creature anatomy or smooth polished vectors.
22. The Fairly OddParents [2D] - Sharp silhouettes, oversized forms and neon color.
   CUES: Use razor-angular silhouettes, oversized heads, compact bodies, thick uniform black contours, huge simple eyes, neon color blocks and flat cel shadows.
   GUARDRAIL: Do not round the design into preschool vector art or use the newer glossy CG treatment.
23. Invader Zim [2D] - Jagged gothic shapes and acid-toned cel shadows.
   CUES: Use flat 2D gothic sci-fi TV animation: thick black angular outlines, wedge-shaped heads and limbs, oversized geometric eyes, tiny tapered torsos, pointy hands and limited acid green, magenta and purple cel colors.
   GUARDRAIL: No crosshatching, realistic fabric texture, painterly shading, smooth anatomy or wardrobe redesign.
24. Totally Spies! [2D] - Sleek fashion contours and glossy saturated color.
   CUES: Use sleek fashion-illustration contours, tall tapered proportions, large anime-influenced eyes, a Y2K pink-lime-cyan palette, simple cel gradients and dynamic spy-design clarity.
   GUARDRAIL: Do not drift into generic magical-girl anime, hyper-glossy fashion art or replacement spy uniforms.
25. Total Drama Island [2D] - Lanky cutout shapes and angular caricature.
   CUES: Use crisp digital reality-TV caricature: lanky angular bodies, tiny waists, oversized hands and feet, asymmetrical facial shapes, varied outline weight and flat earthy cel colors.
   GUARDRAIL: No smooth attractive sitcom anatomy, glossy shading or copied contestant features.
26. Bob's Burgers [2D] - Loose outlines, bean-shaped forms and muted warmth.
   CUES: Use simple expressive adult-sitcom 2D: bean-like torsos, oval eyes, rounded noses, uniform dark contours, flat colors and loose readable posing.
   GUARDRAIL: Do not substitute Family Guy anatomy, glossy shading or perfectly polished vector symmetry.
27. Happy Tree Friends [2D] - Cute compact forms and sugary graphic color.
   CUES: Use cheerful vector-cutout 2D: round compact forms, minimal colored contours, modular limbs, tiny dot eyes, simple mouths and candy-bright flat fills.
   GUARDRAIL: No furry realism, plush or glossy 3D rendering, heavy black outlines or unnecessary gore.
28. My Life as a Teenage Robot [2D] - Retro-futurist geometry with clean cel highlights.
   CUES: Use retro-futurist Art Deco 2D: geometric machine-age construction, sweeping curves, crisp symmetric silhouettes, pale cyan and navy accents and flat graphic fills.
   GUARDRAIL: No generic anime mecha or glossy metallic 3D, and do not replace a non-robot subject with an unrelated robot character.
29. Yu-Gi-Oh! [2D] - Sharp manga forms and high-contrast cel shadows.
   CUES: Use high-energy early-2000s shōnen cel animation: razor-angular faces, large focused eyes, bold directional hair masses, jewel-tone color, dramatic fabric folds and hard two-step shadows.
   GUARDRAIL: No cards, logos or duel props; preserve the reference hair color, outfit and identity instead of copying a named character.
30. Teen Titans [2D] - Anime-comic shapes and graphic shadow blocks.
   CUES: Use anime-influenced American superhero 2D: bold angular silhouettes, compact heroic anatomy, large expressive eyes, saturated color blocks and hard graphic cel shadows.
   GUARDRAIL: Do not use chibi Teen Titans Go proportions, generic anime rendering or a replacement superhero costume.
31. Archer [2D] - Precise vector contours and posterized shading.
   CUES: Use mid-century spy-comic realism: photo-referenced adult anatomy, precise vector contours, restrained expression, flat posterized skin shading and crisp cinematic design.
   GUARDRAIL: No photorealism, smooth 3D rendering, generic halftone comic texture or exaggerated caricature.
32. 6teen [2D] - Slim fashion-cartoon forms and bright mall color.
   CUES: Use clean early-2000s digital tween-sitcom design: slim fashion-forward silhouettes, rounded heads and hands, fine controlled outlines, flat bright color and minimal cel shading.
   GUARDRAIL: Do not import Total Drama's lanky angular caricature or add glossy fashion-rendering effects.
33. Studio Ghibli [2D] - Natural hand-drawn forms and restrained cel color.
   CUES: Use traditional hand-drawn Japanese feature animation: gentle pencil-like contours, natural proportions and gestures, simple expressive faces, flat opaque cel color, one restrained shadow tone and nuanced daylight.
   GUARDRAIL: Keep watercolor texture in backgrounds only; no chibi eyes, glossy airbrushing or fantasy wardrobe changes.
34. Minecraft [3D] - Classic player-skin construction and crisp pixel texture.
   CUES: Use the classic Minecraft player-skin model: one cuboid head, rectangular torso, box arms and legs, with the subject's identity and outfit rendered as crisp low-resolution pixel textures and flat block-face lighting.
   GUARDRAIL: No micro-voxel sculpture, bevels, rounded anatomy, smooth gradients, glossy materials or toy-brick construction.
35. Disney [2D] - Flowing ink, rounded anatomy and storybook color.
   CUES: Use classic hand-drawn feature animation: flowing tapered cleanup lines, appealing rounded anatomy, readable squash-and-stretch posing, luminous cel color and restrained painted shading.
   GUARDRAIL: No glossy modern 3D-princess treatment, generic anime eyes or fantasy wardrobe redesign.
