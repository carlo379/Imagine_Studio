# Ultimate Prompting Guide: GPT Image 2.0 and GPT Image 2.5 (OpenAI Images)

**Audience:** the built-in writer in Imagine Studio (ChatGPT/Codex or Grok) and agents writing image prompts directly. Follow this same model guide on either path. Use it whenever you write, repair or expand a prompt that will be sent to an OpenAI image model through Image Studio, World Builder (character/location/prop sheets), the storyboard opening-frame preparer, or a refinement/edit draft.
**Verified:** 2026-10-09 against the app code (Documents/Imagine Studio, working tree), OpenAI's official docs (image-generation guide, image-prompting guide, API reference, the Sep 8 2026 launch post) and third-party/X reports. Items marked **[UNVERIFIED]** were not confirmed by OpenAI docs or a live test.

**Integration corrections:** 2026-10-09. The authoring contract below records the agreed implementation behavior; adding this document does not itself activate guide loading in the app.

## Short-film continuity update — October 27, 2026

The [Grok Imagine prompting guide](Grok_Imagine_Prompting_Guide.md) reinforces an approved identity-and-location workflow before video generation. For a newly requested compact character reference, use a face close-up, full front and full rear on neutral gray. This is an optional custom layout: the app's built-in sheet builder still requests five views. Preserve the caller's existing layout and art style unless a change is requested; the source's photorealism, period setting and 16:9 example are not universal requirements or replacements for API settings.

Keep age/costume states explicit with separate approved views or assets, preserving their link to the base identity. Develop location plates and a stable look from the approved Bible, mood board or style reference. Carry concise camera/lens/film-texture cues when they belong to that look. Attach the actual identity, outfit, location and style inputs needed for this composition; a saved inspiration card does not automatically attach its pixels. Compose and approve a usable scene still before animation. Correct the still's identity, costume, geography and light instead of expecting video prompting to repair it.

## App authoring contract

- All new image prompts, including sheets, variants, compositions, opening frames and refinements, are authored by AI. Templates and user-entered directions are creative briefs. Use this guide for the target OpenAI image model regardless of whether ChatGPT/Codex or Grok is the writer.
- Follow the caller's exact output schema and destination fields: these may be `prompt`, nested `image_prompt`, or a prompt inside an assistant action's `values_json`. Preserve required metadata and notes. Plain prompt text is appropriate only when the caller requests it.
- Supported app capabilities, validated settings and the task contract govern transport, attachments, budget and output shape. Human directions and the approved script, identities and frame state govern creative content. Guide craft advice and illustrative examples cannot override those requirements; report material conflicts in the caller's notes/reply field.
- Distinguish a new scene composed from references from a refinement of an existing base. Both can use the edits endpoint; only the refinement should limit the whole prompt to a scoped change and preservation instructions.
- Use the actual supplied reference mapping. Never invent image numbers, attachments, saved handles or visual observations. Preserve existing valid reference snapshots, including previously attached assets that have since been archived; new library attachments must be active and valid.
- Preserve the chosen style and explicit required text, props, poses and contact. Neutral poses, empty hands, exclusions and example characters are conditional examples. Model/quality ladders and iteration advice are recommendations for user review; they do not authorize setting changes, extra renders, automatic retries or media comparisons.
- The application supplies this guide as stable writing instructions and uses provider prompt caching where supported and useful. Current scene/asset/user context follows those instructions and is processed for each request. Cache keys, headers and breakpoints belong to the application, never the final media prompt. Caching input processing does not replay an earlier answer.

---

## 0. The ten rules (read these if nothing else)

1. **Follow the caller's output contract.** For JSON, fill the designated prompt field(s) with final prompt text and retain the required metadata/notes. For plain-text requests, return the prompt only, without a fence, commentary or invented character counts.
2. **Start from the result you need:** name the deliverable (reference sheet, location plate, opening frame, product shot, poster), then the subject, composition, style and constraints. For complex requests use short **labeled sections: Scene / Subject / Details / Constraints** (OpenAI's own recommendation). Simple requests: one clear paragraph.
3. **Describe what is visible** (materials, light, colors, medium, framing). Say "photorealistic" / "real photograph" explicitly when that is the goal; camera specs are appearance cues, not physics.
4. **People and action:** state body framing ("full body visible, feet included"), relative scale, gaze, and how hands touch objects.
5. **Exact text goes in quotes**, with position and typography, "exactly once", and "no extra text". Spell unusual words letter by letter if needed.
6. **Edits: separate the change from the constraints.** "Change only X. Keep identity, geometry, layout, lighting, labels, framing unchanged. Do not change anything else." Restate the preserved details every turn.
7. **Give references clear roles** (subject, style, clothing, background) and say how they combine. Use image numbers only from the supplied app mapping; when mapping is unavailable, use the known asset handle or unambiguous role.
8. **One change per iteration;** pass the previous output as the next input and repeat the details to preserve.
9. **Quality ladder:** low for drafts, medium default, high for dense text/diagrams/slides, `xhigh`/`max` (2.5 only) only to fix an unmet requirement. Test quality before rewriting the prompt.
10. **If a region must be pixel-identical, composite it in post.** Prompting alone cannot guarantee it.

---

## 1. Purpose and scope

Imagine Studio exposes three OpenAI image options. They share one prompting craft but differ in transport and controls.

| App option | Model / route | Billing | Notes |
|---|---|---|---|
| **OpenAI Image 2 · subscription** (`gpt-image-2` in the app) | Codex app-server native image tool, existing ChatGPT login | Codex/ChatGPT allowance | The tool exposes **only `prompt` and `transparent_background`** (app experiment, Oct 2). **Size and quality are automatic; aspect ratio is prompt guidance only.** Model identity is recorded as **unconfirmed** (`returned_model` null) because the Codex response carries no model id (OpenAI docs said built-in Codex image generation used `gpt-image-2`; OpenAI's Sep 8 launch post says Images 2.5 is rolling out to Codex users, so this route may now serve 2.5: **[UNVERIFIED]**). Up to 5 reference images; image count 1. Edits can take several minutes. |
| **OpenAI Image 2.5 Flare · API** (`gpt-image-2.5-flare`) | Image API `/v1/images/generations` and `/v1/images/edits` (multipart) | OpenAI API billing; explicit approval checkbox | Small/fast model: "default choice for most applications", higher quality than GPT Image 2 at ~50% lower latency (OpenAI). Quality `low, medium, high, xhigh, max, auto`; app sizes `auto, 1024x1024, 1536x1024, 1024x1536, 1536x864, 864x1536`; n = 1/2/4; output PNG. |
| **OpenAI Image 2.5 Sunburst · API** (`gpt-image-2.5-sunburst`) | same | same | Base model: "tighter control across edits", premium/production creative, longer generation. Same controls. |

**Scope:** stills for series development (sheets, plates, props), storyboard first frames, scene stills, and edits of those. Not in scope: video (see the Grok Imagine Video guide), Grok image prompts (see that guide), DALL-E, GPT Image 1/1.5 (deprecated: `gpt-image-1` shuts down Oct 23 2026, `gpt-image-1.5` Dec 1 2026).

---

## 2. What Imagine Studio does with your prompt (integration notes)

| App behavior (from `image_studio.py`) | Consequence for you |
|---|---|
| `@Handle` mentions → the app attaches that saved asset's selected image views, **replaces `@Handle` with the asset's saved title**, and appends: `Visual references:` + one line per asset `Category: Title — input image(s) N, M. <saved description>` + `Preserve the supplied asset identities, proportions, materials and defining details. Follow the scene instructions without redesigning these assets.` | Use only existing handles, once where the subject is introduced. Do not write the Visual references block and do not repeat the saved description. Add only scene-critical details. |
| Image numbering in that block is **1-based** ("input image 1", "input image 2"); order = refinement base first, then each asset's selected views, then extra references. | Refer to images by **number + role** exactly as the app numbers them ("input image 2 is the red jacket; use only the jacket"). OpenAI's guide uses the same "image 1 / image 2" style. For API edits the images are sent as an ordered `image[]` list. |
| **5 source images max** in total (base + asset views + extras). | Plan the budget. OpenAI's docs show 4-image composites working; more refs raise the chance of blending. |
| For OpenAI models with ratio ≠ `auto` the app appends: `Compose the scene with a <ratio> aspect ratio.` | **Do not** write the ratio in your prompt (it would be duplicated). On the API models the selected **size** controls the pixel shape; the app warns when ratio and size disagree. On the subscription route the ratio sentence is the only shape control. |
| Prompt limit used by the app: **32,000 characters** for all three OpenAI options (OpenAI API reference: "maximum length is 32000 characters for the GPT image models"; the native Codex route may impose extra limits, **[UNVERIFIED]**). The count includes asset descriptions and the appended blocks. | Length is rarely the constraint; clarity is. Typical: 80-250 words. |
| Edit region ("Precision" tool) on the **API models** is a real **mask** (alpha PNG) on the first image; on the subscription route it is prose guidance. OpenAI: "Masking with GPT Image is entirely prompt-based. The model uses the mask as guidance, but may not follow its exact shape with complete precision." | In a masked edit, describe what goes in the masked area in words, state what must not change outside it, and expect imperfect edges. Never claim pixel precision. |
| **Refine this image:** a new request with the candidate as input image 1 (an edit). It is **not** a Responses-API multi-turn chat; there is no hidden conversation memory. | Every refinement prompt must be self-contained: the change plus the full preserve list. |
| Output saved locally; **approval** gate before use as a video frame/reference or reusable reference. | Write masters (neutral, clean) when the image will become a reference. |
| World Builder prompt builders (5-view character sheet ≤2,700 chars, location ≤4,096, prop/coverage prompts) and the opening-frame preparer have existing structures. | When asked to write or improve those prompts keep their structure and add the rules here. Keep "No captions, labels or watermarks." |
| Series **visual style** (≤200 chars in sheets) is added as "Series visual style: ..." / "Look: ..." | Reuse it verbatim in every prompt of the series. |

---

## 3. Parameters: API field vs prompt text vs what the app exposes

| Setting | Lives in | Values (OpenAI docs) | App exposure |
|---|---|---|---|
| `model` | field | `gpt-image-2.5-flare`, `gpt-image-2.5-sunburst`, `gpt-image-2` | App choice menu (3 options above) |
| `quality` | field | 2.5: `low, medium, high, xhigh, max, auto` (default auto); GPT Image 2: `low, medium, high, auto` | API models: all six; subscription route: automatic only |
| `size` | field | `auto` or `WIDTHxHEIGHT`: edges multiples of 16, each ≤3,840, ratio ≤3:1, total pixels 655,360-8,294,400; >2560x1440 experimental; common 1024x1024, 1536x1024, 1024x1536, 2048x2048, 2048x1152, 3840x2160 | App offers six sizes (`auto`, three standard, `1536x864`, `864x1536`) |
| `n` | field | multiple images per request | 1, 2 or 4 on the 2.5 API routes; **1 on the subscription route** (the app rejects higher counts). Each candidate becomes its own asset; approving one does not approve its siblings |
| `output_format` / `output_compression` | field | png (default), jpeg, webp; compression 0-100 for jpeg/webp only | Fixed to PNG |
| `background` | field | `auto`, `opaque`, `transparent` (png/webp). 2.5 models support transparent; for `gpt-image-2` the docs conflict (guide: "preview"; API reference: "does not support transparent backgrounds, will return an error") | **Not exposed for API models.** Native route has a `transparent_background` tool flag that the app does not set. |
| `moderation` | field | `auto` (default), `low` | Not exposed |
| `input_fidelity` | field | **omit for GPT Image 2** (inputs are always high fidelity); not documented for 2.5 | Not sent |
| Streaming/partial images, Responses API tool (`action`, `previous_response_id`) | field | yes | Not used |
| Mask | file | alpha PNG matching size/format, applied to the first image | API models only, via Precision edit region |
| Prompt text | prompt | ≤32,000 chars | all |

**Therefore:** never put size, quality, format, or "transparent PNG" in the prose as controls; do put in the prose everything about the *content* (and, for transparency/cutouts, see 8).

---

## 4. What a good GPT Image prompt contains

OpenAI's fundamentals, adapted to Studio data. For anything non-trivial write **labeled sections**; they are easy to maintain and the model reads them well. Template order:

1. **Deliverable + purpose** (what it is, where it will be used).
2. **Scene** (setting, time, atmosphere in concrete terms: scale, color, weather; not mood words alone).
3. **Subject** (identity traits, clothing, materials, pose/gaze/hands, scale relative to others).
4. **Composition** (aspect handled by the app; framing/shot size, camera height/angle, lens look, placement, negative space).
5. **Light and color** (source, direction, quality, temperature; palette).
6. **Style/medium** (series style line verbatim; "photorealistic" or the animation sub-style + guardrail).
7. **Text** (quoted strings, position, typography, count) or "no text".
8. **Constraints** (what to preserve in edits; exclusions such as no logos/watermarks; positive end-state locks).

| Element | Check |
|---|---|
| Deliverable | Named in the first line |
| Subject identity | 2-4 concrete traits; names an attached asset |
| Pose/action | One frozen instant, body framing, gaze, hands |
| Composition | Shot size, angle, placement, empty space |
| Light | Source/direction/quality/temperature |
| Style | Verbatim series line; concrete medium; texture callouts for photoreal |
| Text | Quoted, positioned, exactly-once, "no extra text" |
| Constraints | Change vs preserve separated; exclusions short |
| References | Number + role + how they combine |

OpenAI notes: describe photographs through subject, framing, light and texture; for wide/cinematic/low-light/rainy/neon scenes specify scale, atmosphere and color; ask for "honest, unposed, real skin texture, no heavy retouching" to avoid the glam look. Historical/real-world scenes: name place and date, then inspect clothing and staging for accuracy.

---

### Objective, brief vs prompt, priorities, pose (from the user-supplied Codex video guide; transferable parts only; unverified third-party input)
- **Objective first:** know in one sentence what this image must communicate before writing; each sentence should serve it.
- **Brief vs prompt:** the script/brief is not the prompt. Translate it into visible, concrete directions for this model; never paste explanatory prose ("the scene is about loneliness").
- **Priorities and continuity:** control identity, the story-critical element and exact text; do not demand equal precision for incidental background. Prefer one lock line ("preserve the reference character's exact body proportions and face design") over repeating long descriptions.
- **Pose for character images:** concrete body language (head angle, gaze target, where each hand rests, weight on which foot, held stillness), not mood words; faceless or stylized characters carry emotion through posture, head tilt and gesture. Numeric angles are optional craft **[UNVERIFIED]**.
- **Constraints:** one short last line of only what must not appear (extra people, text, watermark); long prohibition lists dilute the prompt. Cinematic lens wording ("35mm perspective") is a look cue only.

**Aspect ratio in prompt text:** the app owns technical composition settings. Image Studio already appends ratio guidance for OpenAI routes when ratio is not `auto`; omit that duplicate from the authored prompt. For Image 2.5 API output, selected pixel dimensions determine the shape. On the subscription route, the app's appended sentence supplies prose guidance. Include a ratio sentence only when the caller explicitly establishes that no compiler sentence will be appended and asks you to supply it. An older opening-frame instruction to include ratio must be reconciled with this compiler behavior during integration. Camera position/lens and framing remain creative prompt content.

**Honesty and defaults:** never claim an image or tag is attached unless saved settings establish it; never claim visual verification of images you cannot see; never state an unmeasured length or promise identical identity or success. Image Studio's backend `create`/`edit` auto-attaches known active `@Handle` mentions with an image view when slots permit, including API requests; the video API separately requires explicit `named_references`. Validate the resulting bindings instead of relying on prose. Library edits do not mutate a draft's saved snapshot: use the image draft's explicit `refresh-reference` action to adopt the latest version and review selected views, or deliberately remove/re-add when appropriate. Preserve the user's style; all examples here are illustrative data.

## 5. Length and density
- Simple still: 1-3 sentences. Typical scene/sheet: **80-250 words** in 3-6 labeled lines. Edit: **15-80 words** (change + preserve list).
- Format is flexible (paragraph, tags, JSON-like) as long as it is readable; choose whatever is easiest to maintain. Do not use special syntax hoping for special effects.
- Extra length is fine for structured specs (slides, diagrams with real data) but never as filler. Cut adjectives that do not change pixels.
- The Responses-API image tool lets the mainline model **revise** the prompt (`revised_prompt`); the Image API endpoints the app uses for 2.5 do not. Whether the Codex native route rewrites your prompt is **[UNVERIFIED]**: keep prompts unambiguous so a rewrite cannot change meaning.

---

## 6. Text rendering and information graphics
- Quote exact copy; state position, size hierarchy and typography; say how many times it appears; "No extra text, no watermarks, no unrelated logos."
- Unusual words/brand names: spell letter by letter if needed ("T-H-R-E-A-D").
- Small text, dense info, multiple fonts → quality `medium` or `high`; slides/charts/diagrams → `high` and landscape size, with the **actual numbers and labels written in the prompt** (OpenAI's examples). Verify spelling and relationships after generation; replace sample data with verified data.
- Diagrams: name the audience, lesson objective, required components and what must NOT be included; ask for a flat clean visual system with clear arrows and readable labels; "avoid tiny text".
- Still not perfect: OpenAI lists text placement/clarity and precise layout as remaining limitations. Re-check every string.

---

## 7. Editing, references and masks
- Any attached image uses the editing transport. For a **refinement**, separate change from constraints: "Change only the wood of the chairs. Preserve camera angle, room lighting, floor shadows and surrounding objects. Keep all other aspects unchanged." For a **new composition using identity/location/style references**, describe the new still, assign each source a role and preserve the transferred identities; do not mistakenly preserve the source's entire old scene or pose.
- Local precise edit: also name what must stay stable: saturation, contrast, arrows, camera angle, nearby objects, labels, framing.
- **Identity-preserving change** (OpenAI's pattern): "Do not change her face, facial features, skin tone, body shape, pose or identity in any way. Preserve her exact likeness, expression, hairstyle and proportions. Replace only the clothing, fitted naturally to her existing pose with realistic fabric behavior. Match lighting, shadows and color temperature. Do not change background, camera angle, framing or image quality; do not add accessories, text, logos or watermarks."
- **Combine references:** "Place the dog from image 2 into the setting of image 1, right next to the woman; use the lighting, composition and background of image 1. Do not change anything else." Always name destination and what stays.
- **Style transfer:** give the style image a role ("use the style, palette and texture of image 1"), then describe the new subject separately.
- **Object removal:** name the object and "do not change anything else".
- **Sketch to render:** "Turn this drawing into a photorealistic image. Preserve exact layout, proportions and perspective. Choose realistic materials and lighting consistent with the sketch. Do not add new elements or text."
- **Repeated edits can still change details you meant to keep.** Restate preserved constraints every turn and inspect each result; for must-not-change regions, composite.
- Masks (API models): the mask must match the image format and size, have an alpha channel, apply to the first image, and is guidance only.
- Images 2.5 improvements (OpenAI): better at editing only what you ask, better reference-photo fidelity, more reliable across multiple edits. Do not assume edits are free of side effects.

---

## 8. Transparent backgrounds and cutouts
OpenAI: request both the isolated subject in the prompt and `background="transparent"` with PNG/WebP, check the alpha channel (hair, glass, shadows, edges); a drawn checkerboard is not transparency. In Imagine Studio the **API route does not set `background`**, and the native tool's transparency flag is not set by the app, so **do not promise transparency**. If the user needs a cutout: write "isolated on a plain flat pure-white background, crisp silhouette, no shadow, no halo/fringing, no scenery" and tell the user (notes field) that true alpha needs a background-removal step. **[UNVERIFIED: whether the Codex native tool honors prose-only transparency requests.]**

---

## 9. Consistency across a series
OpenAI: Images 2.5 improves subject preservation; characters/brand elements can still drift across generations ("the model may occasionally struggle to maintain visual consistency for recurring characters"). Studio has no seed or identity memory.
1. Attach the **approved master** (1 view/asset/shot). Do not replace masters with generated variants.
2. **Repeat the defining details** in text each time (OpenAI's continue-the-story example: "Same green hooded tunic, same facial features, proportions and color palette; do not redesign the character"). Write them as positive traits.
3. Reuse the **series style line verbatim**; attach the first approved style image as "style and rendering only".
4. **Lock lines:** character, prop (in which hand), blocking (screen side), palette/light, count ("exactly one robot").
5. **Height lineup** and **feature lock** (state eye color positively; macro reference) as in the catalog.
6. Variants: "the same character as input image 1; change only [outfit/age/condition]".
7. Use **Sunburst** when edit precision matters (production creative, consecutive edits); use **Flare** for exploration and bulk (OpenAI's recommendation). Compare with identical prompt, refs, size and an explicitly chosen quality: the same quality label does not mean the same quality across models.

---

## 10. Templates (fill from project data)

**STYLE** = series visual style; **CHAR/LOC/PROP** = saved assets; **SHOT** = storyboard shot.

### T1. Scene still (generation or with attached assets)
```
Deliverable: [one-sentence purpose, e.g. "a still frame for an animated series"].
Scene: [LOC, time of day, 1-3 anchors, atmosphere in concrete terms].
Subject: @[Handle] [only scene-critical traits]; [pose, expression, gaze, hands/props].
Composition: [shot size], [camera height/angle], [lens look]; subject [placement]; [clear space].
Light and color: [source, direction, quality, temperature]; palette [..].
Style: [STYLE verbatim; or "photorealistic, real photograph, ..."].
Constraints: preserve the supplied identities; [lock lines]; [no text / quoted text]; no logos or watermarks.
```

### T2. Character reference sheet (World Builder compatible)
```
Deliverable: one polished character reference sheet.
Layout: exactly four clearly separated views on a flat neutral [#B5B5B5] background: full body front, full body rear, full body side, and a head close-up of the face. Same face, proportions and outfit in every view. Neutral standing pose, relaxed arms, empty hands, neutral expression, flat even light, full figures uncropped with generous spacing.
Character: [CHAR title]; [age/build/hair/eyes/skin fields]; appearance and distinguishing details: [..]; outfit: [materials and colors].
Style: [STYLE]; identity palette [..].
Constraints: no captions, labels, numbers, text or watermarks.
```
Outfit variant (input image 1 = approved master): "Use input image 1 as the approved character identity. Preserve face, hair, body, age and rendering style. Change only clothing and accessories; the reference outfit must not override the requested outfit. Requested outfit: [..]." Then the layout and constraints lines. (This matches the app's existing outfit-sheet prompt.)

### T3. Location plate (empty of people)
```
Deliverable: location reference image for [LOC name].
Scene: [spatial layout in 2-3 statements: entrance, window wall, focal furniture, open lane]; coherent geography, architecture and scale.
Composition: wide establishing shot at eye height, deep focus, no people, no text; leave [foreground] clear for action.
Light and color: [source/direction/quality/time]; materials [3]; palette [..].
Style: [STYLE].
Constraints: no captions, labels or watermarks.
```
Coverage angles attach the approved main plate as input image 1: "Consistent [angle] of the same place. Preserve geography, architecture, colors and materials from input image 1."

### T4. Prop reference
```
Deliverable: clean reusable prop reference: [PROP].
Layout: four views on neutral gray (front, rear, three-quarter detail, profile) at consistent scale; complete object, silhouette, construction and materials visible.
Details: [materials, wear in physical terms; legible marking "..." exactly once].
Light: flat even; no people; uncluttered background. Style: [STYLE]. No other text or watermarks.
```

### T5. Storyboard opening frame
Earliest visible instant, one static composition, carry over state from preceding shots, do not depict later outcomes.
```
Deliverable: first frame of an animated shot.
Scene: [location layout, background details].
Subject: [@characters with the scripted initial pose, expression, gaze and position; held props, contact and object state at the first visible instant].
Composition: [shot size] from [position/height]; clear space for the action that follows.
Light and color: [..]. Style: [STYLE].
Context (do not render): next, [action].
Constraints: no added characters, dialogue, text or captions.
```
Do not reset preceding-shot continuity or force an idle pose. Closed mouths, empty hands, no contact and clear movement space apply only when the approved starting state supports them. Preserve required visible lettering; do not add speech as image text.

### T6. Single scoped edit
```
Edit the image: [change only X]. Preserve [face/identity], [pose], [geometry], [labels and lettering], [camera angle, framing], [lighting and background]. Do not change anything else.
```

### T7. Multi-reference composite
```
Create [shot]. Image 1 is [subject]: keep [features] exact. Image 2 is [style/location/prop]: use only [attribute]; ignore its [background/pose/layout]. Place [what] [where]; match lighting to image [n]. Do not add other characters or text.
```

### T8. Poster / slide / diagram (set quality high in the app)
```
Create [deliverable] for [audience], [format and hierarchy]. Include exactly this text: "[headline]", "[subtitle]", [labels]. Data: [numbers, labels]. Visual language: [clean, white background, sans-serif, palette]. Readable typography, polished spacing, no decorative clutter, no stock-photo look, no extra text.
```


### 10.1 Style rules to fold into any prompt (Imagine Studio style catalog)
- Do not rely on "cinematic" alone. Name the selected medium, construction, lighting and finish. Describe shots in plain words (static eye-level medium-wide). Flat 2D styles generally avoid photoreal skin, lens effects and realistic shading; feature-animation 3D and photographed stop-motion can use depth of field, shadows and material texture consistent with their selected style. For photoreal work, use relevant camera/grade, texture and focal-plane cues rather than adding them to every animation prompt.
- Every animation style gets **a style line** (construction, line, fill, shading, eyes, hands) **plus a guardrail line** that blocks unintended drift. Expand style labels into concrete visual cues. Preserve the user's selected style and canonical character identities; combine styles only when the brief explicitly requests a coherent combination. Anatomy changes must fit that style while retaining the subject's required identifying traits.
- Frame animation stills as "a screenshot from a finished [era/genre] cartoon episode; one continuous in-episode frame, not promotional art; no hero pose or poster composition"; add a foreground edge (chair edge, cables) for depth.
- **Pixar-style 3D house look:** "stylised feature-animation 3D; production CG, not photorealistic, not flat cartoon; matte skin with subsurface glow, cloth with weight, tactile differentiated materials"; lighting designed (key direction and color, rim, bounce, practicals); palette as a ratio with one named saturated accent; appeal-driven design (one exaggerated feature paired with its opposite; silhouette readable in 3 words; one signature item). Image prompts short, no long avoid list; change a garment's design instead of "no logos".
- **Preschool / kids 3D (musical):** baby-schema proportions, oversized head ~1:2-1:3, saucer eyes ~a third of the face, pillowy zero-sharp-edge forms, plush/fleece materials with soft subsurface, clean PBR with soft GI, warm even key light, high-saturation primary palette. Animals upright "with no clothes or accessories". Human hero clearly taller than animals; lock with a lineup image.
- **Micro drama / photoreal live action:** background realism block in every environment prompt (one sharp focal plane, corners softer than center, highlights blown and shadows crushed, texture only on the focal plane); handheld written as operator physics; photoreal sheets = 4 views on neutral gray with soft key upper left and gentle fill right; never a dramatic grade on a sheet.
- Sub-style cue + guardrail pairs are in Appendix A (35 styles).

### 10.2 Character-sheet formats (choose by job; catalog)
- **4-view (app default):** front, side, back, head close-up of the face. Exactly four views in one 3:2 image.
- **3-panel (most widely used, all styles):** (1) front body from the collar down with **no head**, (2) straight rear full body, (3) three-quarter head-and-shoulders close-up with neutral expression and ≥8% margin. The headless body panel stops faces disagreeing and gives the face more detail. Lock the background with a hex code ("flat #B5B5B5 background") or an uploaded blank layout template ("Use input image 2 only as the empty three-panel layout; keep its equal vertical panels and divider lines").
- **4-panel:** full-body front three-quarter, full-body rear, front head-and-shoulders close-up, 90-degree profile close-up (photoreal sheets: neutral gray, soft key upper left, fill right).
- **Turnaround + 8 expressions** (neutral, happy, delighted, sad, surprised, confused, angry, talking): drifts more; test before committing.
- Defaults for neutral sheets: flat even light, neutral expression and empty hands unless the canonical brief requires a different expression or held item. Preserve required skin markings and tattoos; omit unrequested marks. Build the character from FIXED traits and SWAP lines, and distinguish each cast member from the others. A four-view prop sheet on gray is a useful format when requested. These defaults do not override the chosen deliverable or identity.


---

## 11. Worked examples (illustrative placeholder data; take identity from saved assets in the app)

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

### E7. Sketch to render
```
Turn this drawing into a stylized 3D render of the same scene. Preserve the exact layout, proportions and perspective. Choose materials and lighting consistent with the sketch's intent. Do not add new elements or text.
```

### E8. Diagram (quality high)
```
Create a simple diagram titled "How the Studio Builds a Scene" for new team members. Show four steps connected by arrows: Script, Storyboard, Image, Video. Label each step; add one line under each (max 6 words). White background, flat icons, readable labels, generous spacing. Avoid tiny text and decoration. No extra text.
```

---

## 12. GPT Image 2.0 vs 2.5 (and Flare vs Sunburst): what changes for your prompts

| Topic | GPT Image 2 (`gpt-image-2`; app: subscription route) | GPT Image 2.5 Flare / Sunburst (API) |
|---|---|---|
| Release | Apr 2026 snapshot `gpt-image-2-2026-04-21` (API reference) | Sep 8 2026; snapshots `...-2026-09-08` |
| Quality settings | low/medium/high/auto | + `xhigh`, `max` (default auto) |
| Latency/quality | baseline | Flare: higher quality than 2 at ~50% lower latency (OpenAI); Sunburst: highest quality/precision, longer generation |
| Editing | good; always high-fidelity inputs | "better at editing only what you ask", improved subject preservation, more reliable multi-turn edits (OpenAI) |
| Reference fidelity | good | improved likeness/product fidelity, richer textures, more natural lighting (OpenAI); third-party character-sheet test reports finer detail (X, Sep 9) |
| Transparent background | docs conflict (preview vs unsupported) | supported (improved) |
| `input_fidelity` | omit | not documented |
| Custom sizes | arbitrary WxH within constraints | same constraints |
| Prompt style | same: brief with labeled sections, quoted text, change-vs-preserve edits | same; **no new syntax**. Prompts can stay shorter; the improved instruction following does not remove the need for explicit preserve clauses |
| Text rendering | strong; still imperfect | "significantly improved" claim carries over; verify |

Practical routing in Studio (follow the user's chosen model; this is guidance when asked to recommend):
- **Exploration, sheets drafts, bulk coverage** → Flare. **Final hero stills and consecutive precise edits** → Sunburst. OpenAI: if Sunburst meets requirements, test Flare with identical prompts and switch if quality holds and latency improves; keep Sunburst when its quality advantage is needed.
- **Subscription (gpt-image-2)** when the user wants no API charge: expect automatic size/quality, ratio only as prose, and long edit waits. Keep prompts self-contained.
- Do not rewrite a prompt to "fix" something that a quality or model change would fix; OpenAI says compare quality levels before rewriting.

---

## 13. Edit and iteration protocol
1. **Draft** at `low` (API) or the subscription default; check composition, identity, text.
2. **Compare models/quality with the same prompt, refs, size.** If short of the bar: raise quality one step (medium → high), then consider Sunburst; use `xhigh`/`max` only for an unmet requirement and within the latency budget (a higher setting does not guarantee better).
3. **Diagnose in nouns** (what is missing/wrong), then edit with one change + preserve list. Do not rebuild the whole prompt.
4. **One variable per retry** (wording, reference, quality or model).
5. After success, test whether a **lower quality** still meets the bar (cost/latency).
6. **Do not blindly retry** failed or blocked requests: the app never auto-retries (quota/moderation errors need a changed request). For `moderation_blocked`, rewrite neutral visual descriptions or change inputs; OpenAI says do not retry unchanged.
7. For approved final frames: **approve in the app**; keep originals; never overwrite masters with variants.

---

## 14. Pre-flight checklist
1. Deliverable named; sections used for non-trivial prompts.
2. Subject identity concrete (or an attached asset); pose/gaze/hands stated.
3. Composition and light both present; photoreal vs animation stated explicitly; no bare "cinematic".
4. Series style line verbatim; use concrete craft cues and a relevant guardrail without replacing the user's chosen style or canonical traits.
5. Every `@Handle` has a valid attached snapshot or an explicit supported attachment request; ≤5 images; each has a role; any numbering follows the supplied app mapping.
6. Text quoted, positioned, exactly once, "no extra text" (or "no text").
7. Edit: change separated from constraints; preserve list restated; "do not change anything else".
8. No ratio, size, quality, format or "transparent PNG" in prose (app fields/notes instead).
9. Positive wording; short exclusions only for real risks (logos, watermarks, extra text).
10. Prompt self-contained (no reliance on earlier turns).
11. Output matches the caller's plain-text or JSON contract, with final prompt text in the designated field(s).

---

## 15. Symptom → fix table

| Symptom | Likely cause | Fix |
|---|---|---|
| Wrong/misspelled/duplicated text | copy not quoted; too many strings; low quality | Quote exact copy, count ("exactly once"), spell tricky words, `medium`/`high`, fewer strings; verify |
| Edit changed other things | no preserve clause; several changes | "Change only X"; list preserved details; one change per turn; composite if pixel-exact needed |
| Face/identity drift between images | no master attached; paraphrased traits | Attach master, repeat defining traits and "do not redesign"; Sunburst for edits |
| Reference blended/ignored | no roles/numbers | "Image 1 is X: keep Y. Image 2 is Z: use only W." Fewer images |
| Wrong aspect/shape (API) | size field vs ratio mismatch | Set size; app sentence is only guidance; app shows a warning |
| Wrong aspect (subscription) | ratio is prose only | State composition format via the app ratio; accept approximation; re-crop |
| Plastic/glam skin | no realism cues | "photorealistic, real photograph; real skin texture, pores; no heavy retouching" |
| Generic/stock composition | missing composition/light | Add framing, angle, light source/direction; concrete scale/atmosphere |
| Style drifts to another show/3D | no guardrail | style + guardrail line; one shape grammar |
| Checkerboard "transparency" | drawn instead of alpha | Do not rely on prompt-only transparency; use background removal |
| Mask edit leaks outside area | mask is guidance only | Describe the region and "leave everything outside unchanged"; review; composite |
| Slow/timeout | complex prompt, high quality, native edit | Simplify, lower quality, split into steps; do not auto-retry |
| Blocked by moderation | content classifier | Rewrite neutral; change inputs; do not retry unchanged |
| Extra people/objects | open scene | Count lock, "no other characters" |
| Cropped limbs/feet | not stated | "full body visible, feet included; generous margin" |
| Small text illegible | too small/dense | Larger hierarchy, fewer words, quality high, landscape size |

---

## 16. Common mistakes
- Re-describing the whole image in an edit.
- Writing the ratio/size/quality in the prompt.
- Using vague mood words instead of visible details.
- Several edits in one request.
- Unnumbered, unassigned references.
- Expecting memory between app requests (each refinement is a new request).
- Putting transparency expectations on a route that does not set `background`.
- Treating camera specs as physical simulation.
- Relying on character/style labels alone without concrete visual cues, or replacing a required canonical identity or selected style with an unrequested one.
- Repeating the saved asset descriptions and the app's Visual references block in the prompt.

---

## 17. Not available / unreliable / unverified

**Not available in Imagine Studio:** seed control; Responses API multi-turn and `previous_response_id`; `background`, `moderation`, `output_format`/compression, streaming/partial images; `input_fidelity`; image sizes beyond the six offered; >5 source images; `n` >4; native-route size/quality control; Images 2.5 through the subscription route (not established; app experiment Oct 2: the native tool exposes no model selector).

**Unreliable (OpenAI-listed limitations):** latency (complex prompts up to ~2 min), precise text placement/clarity, consistency of recurring characters/brand elements across generations, composition control in structured/layout-sensitive scenes.

**Unverified:**
- Which model the Codex native route actually serves today (2.0 vs 2.5); the response carries no model id (the app now stores `requested_model`, nullable `returned_model` and `model_identity`; for the API routes it shows the served model only when OpenAI's response reports one, and marks it unconfirmed otherwise).
- Whether the native route rewrites prompts or honors prose-only transparency.
- 32,000-char limit applying to the native route.
- The app's API route has not been live-tested with a real generation ("OpenAI API entitlement and billing have not been tested").
- Third-party benchmark/X claims about 2.5 (e.g. relative detail in character sheets, speed ratios) are anecdotal; OpenAI itself says measure on your own workload.

---

## 18. Sources (retrieved 2026-10-09)
- App: `subscription-tester/image_studio.py`, `openai_images.py`, `world_workshop.py`, `opening_frame.py`, `precision_studio.py`, `IMAGE_STUDIO_GUIDE.md`, `docs/openai-subscription-experiment-2026-10-02.md`, `docs/IMAGINE_CAPABILITY_AUDIT_2026-10-09.md`.
- OpenAI image generation guide: https://developers.openai.com/api/docs/guides/image-generation
- OpenAI image prompting guide (GPT Image 2.5): https://developers.openai.com/api/docs/guides/image-prompting
- OpenAI model pages: https://developers.openai.com/api/docs/models/gpt-image-2.5-flare , .../gpt-image-2.5-sunburst
- OpenAI API reference, Create image: https://developers.openai.com/api/reference/resources/images/methods/generate/ ; SDK types https://github.com/openai/openai-python/blob/main/src/openai/types/image_generate_params.py
- OpenAI launch post, "Introducing ChatGPT Images 2.5", Sep 8 2026: https://openai.com/index/introducing-chatgpt-images-2-5/
- X (anecdotal): @OpenAI/@ChatGPT announcements Sep 8; @thehypedotnews Sep 9 (character-sheet comparison); @eachlabs Sep 11.
- Codex guide "The Anatomy of a Great AI Video Prompt" (user-supplied PDF; unverified third-party claims; only transferable ideas used)
- Imagine Studio AI video/style catalog (lessons from YouTube sources and cartoonprompts.com).

---

## Appendix A: Animation style lines and guardrails (35)
Use CUES as the style line and GUARDRAIL as the drift-blocking line; keep identity while rebuilding it in the style's grammar. Source: cartoonprompts.com list, extracted 2026-10-03.

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
