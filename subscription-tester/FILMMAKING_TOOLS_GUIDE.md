# Imagine Studio · connected filmmaking tools

The creation flow is **Develop → Script → Storyboard → Generate → Edit**. Quick Video skips Script. World Builder lives in Develop, Camera Control stages a storyboard shot, and Camera Movements directs a video shot. The existing brief, collaborator, asset library, image/video generators and editor remain available.

## Agent workflows — October 16, 2026

Agents can read/save Camera Control staging, discover presets and export its local reference PNG without a browser renderer. Open-camera staging, movement briefs and development details can also be shared through the browser's [Agent draft handoff](USER_GUIDE.md#work-with-an-agent). Separate browser-control permission allows destination, chapter, section and inspected-editor resolution requests; it does not grant identity verification or generation approval.

Manuscript preview/download and agent book exports use one shared local formatter. The Edit API can render a saved timeline and return a composite PNG at a requested time, including titles and transitions. See the [current API additions](AGENT_API_REFERENCE.md#shared-controls-and-browser-consent) for request shapes and acknowledgement rules.

## World Builder

Open **Develop → World Builder → Story**. The modern green storybook has six chapters: The idea, Cast, Places, Story arc, Look & rules and Script. The left page focuses on inputs; the right offers guidance, a live manuscript summary and the next step. Turn pages or jump between chapters; the book resumes your last chapter in the same browser session. On narrow screens the spread stacks into a single-column reading flow. Characters and Locations retain their visual studio layouts.

Name the story and describe the idea. Genre and Tone offer common choices and custom entries; running time, audience, character roles/personality, time of day, lighting and visual style also offer choices. One blank character and location are provided by default. Blank cards are optional; AI may omit them or invent details when writing. Appearance, reference images and extra notes are tucked into optional sections. Add/remove up to eight acts.

**Upload your story** accepts TXT, Markdown, Fountain and DOCX up to 2 MB, or pasted text up to 60,000 characters. Extraction runs locally and recognizes title/genre/tone labels, screenplay character cues, settings and act/scene headings. Review the extraction before **Populate my book**. Filled fields stay intact unless you select replacement; the complete original text is preserved. Prose may need character/place details added manually; AI writing uses the original text to develop structured cast, settings and scenes. An Undo import action restores the preceding book while the book stays open.

**Manuscript** opens a live overview with chapter shortcuts; **Download manuscript** exports Markdown. The book saves changes automatically. In Script, choose ChatGPT or Grok and click **Write my story**. A request uses that existing subscription connection; media generation is a separate action. Read and edit the logline, synopsis and scene script directly; review optional shot directions and their character/location links. Empty required script fields preserve the last saved version and can be corrected without loading over the draft.

**Ask for a focused revision** selects one scene and a change such as “make the confrontation tenser.” It creates a new draft, preserving all other scenes, asset identities and shot cast/location links. **Version history** can copy an earlier completed script into a new draft. Once a story is connected to visual work or a storyboard, **Edit as a new version** protects that original work. Writing failures leave the preceding script available; requests never automatically retry or switch providers.

**Continue to characters** carries reviewed cast and place details into the visual studio and fills blank book cards/arc from the script. Create or upload a portrait, confirm the identity, then create identity-conditioned outfit sheets. Locations support 1/3/6 scouting candidates, confirmed main references, eight coverage angles and custom views. Confirmed assets and explicit shot links carry into the new storyboard without retyping. **Preview story bible** exports an illustrated local PDF with the story title and confirmed references.

Limits: 8 scenes, 20 shots, 12 assets and 4 suggested views per asset. Story cards support 8 characters, 4 locations and 8 acts. Visual entities support 32 views with up to 8 generated images per request. PNG/JPEG/WebP reference uploads are limited to 10 MB. Existing episodes, media, timelines and asset versions are preserved. Changed story inputs or briefs require a fresh writing version before a new handoff. Unsaved book/script drafts recover within the browser session, and revision conflicts offer draft download before loading the saved story.

## Camera Control

Open **Stage camera** on a storyboard card or **Camera Control** above an image/video draft. The local perspective scene supports 1–4 subjects, six pose presets, subject position/facing/arm/head controls, orbit, elevation, distance, lens and look-at controls. Framing presets and a draggable top view make blocking faster. Select an existing character identity or describe a simple subject. Choose a frame ratio and describe the environment and look.

**Save composition** persists staging per shot. **Reference PNG** downloads a clean reference. **Review image direction** lets you edit the generated prompt. **Use composition in Image Studio** replaces the linked image prompt, adds the PNG as a loose image reference and attaches chosen character identities. It preserves other settings and existing candidates. Repeating the transfer replaces that tool's previous composition reference. The normal five-source image limit still applies. Rendering uses the image model already selected in the shot.

This is a local blocking tool with articulated mannequins and perspective projection, not a textured scene renderer or motion-capture system. Image generators interpret the reference; review the resulting composition and identity.

## Video Studio: references, direction and timing

The reference column shows one card per attached asset, combining its full name, category, saved image views and compact controls. **Insert name** adds the canonical mention to the direction. Image tags and arrows insert or reorder individual views; **Restore views** appears when an attached view or voice is missing. Each card can show its short video identity cue and original description. Loose reference images have their own cards.

Image and Video Studio history shows only attempts belonging to the current shot's linked draft, including earlier revisions and failed requests. Selecting another shot updates the visible history immediately. Older video jobs already associated with the shot remain visible. Unrelated or unassigned media stays in the Library; this filter does not delete or move any media.

**Video direction & timing** offers ChatGPT or Grok using the existing writing subscriptions. Enter optional **Instructions for AI** before clicking **Prepare with AI** or **Prepare again**. Examples: “Keep the camera stationary,” “Make Mark approach more slowly,” or “End before the truck door opens.” Preparation starts only when you click; opening Video Studio does not submit a writing request.

Instructions support 2,000 characters and stay separate from the final video prompt. AI combines them with the scene script, shot action, neighboring shots, visual style and first-frame description. A repeat preparation also receives the previous proposal for context. Instructions take precedence over previous AI direction while preserving scripted dialogue, approved identities, first-frame continuity and model limits; conflicts should be explained in the proposal's notes. The field preserves edits per shot in the current browser session, and submitted instructions are saved with each proposal. **Instructions used for this preparation** shows what the AI received. Changing the field requires a new preparation before applying that proposal.

AI writes motion instructions, one concise sentence per attached asset, and a supported shot duration with an explanation. **Direct the Scene** includes those cues visibly. Reference expansion uses the concise cues once and retains the full Bible/Storybook descriptions. Preparation checks the entire expanded request against the configured video limit, currently 4,096 characters. If the shot cannot fit the maximum supported duration, AI should flag it for splitting rather than silently shortening dialogue.

An unchanged starter prompt and five-second default can populate automatically. Existing direction, timing or video takes remain protected behind a side-by-side comparison and **Use prompt & duration**. You can edit the prompt and duration afterward; the duration control shows the AI recommendation alongside your current setting. **Restore previous direction & duration** is available before newer edits, with previous text retained for copying later. Source/model/reference changes require preparation again. Failures preserve current settings and do not retry automatically. Video generation remains a separate action.

## Camera Movements

In Generate, select a shot and open **Camera Movements**. Search 14 movements in Essentials, Cinematic and Expressive. Each shows a local animated camera demonstration and a practical prompt. Pans and tilts rotate from a fixed position; tracking, orbit and dolly shots move the camera; optical zoom changes the lens.

Customize the subject, action, location, mood and pace, or edit the direction directly. **Copy prompt** exports text. **Add to video direction** appends it to the current video prompt without removing existing instructions, references, frame pins, voices or settings. Review and generate from the normal video workspace. The demonstrations are local illustrations; actual generated movement is provider-dependent.

## Connections and verification

Writing reuses the established local Codex/ChatGPT and Hermes/Grok subscription transports. OpenAI Image 2 and Grok Imagine subscription models are offered for new drafts. These tools add no Claude connection, API-key requirement or automatic billing fallback. Existing optional OpenAI API image models remain selectable in Image Studio.

Development verification uses isolated local mock state, mocked subscription transports and local media. Live writing and generation with the new workflow have not been submitted. A manual live request is needed to confirm the selected account's current entitlement and output quality.

See Release 4 editor tools for audio shaping, split edits, named lanes and local export controls.

The Edit Captions panel imports SRT or uses an available local transcriber. Export can burn captions, save an SRT, match source resolution, or render a quick 360p preview. See Release 4.

Edit now has take-selection stars, marker notes (M), saved Versions with restore confirmation, and optional color controls. See Release 4 for defaults, API examples and preview limits.

Scene geography and lessons are available in the project's workflow panel. Save the scene layout once and a shot end-state override when it changes. Both video writers receive this continuity and matching project/global lessons; these changes make existing preparation stale. Record frame poses explicitly rather than treating a character reference sheet as geography. Review the non-blocking prompt warnings before authorizing generation. See AGENT_API.md for the shared frame gate, usage, mirror, scene-layout, lesson and timeline routes.

## Grok short-film workflow alignment — October 27, 2026

The [Grok Imagine prompting guide](../docs/prompting-guides/Grok_Imagine_Prompting_Guide.md) connects
the authoring workflow to shot planning and continuity. Plan shots
before generation, develop approved identities/outfits and location plates, carry
the approved camera/lens/look, and correct the starting still before animation.
The runtime video guide now includes seven authoring checks: camera/style,
action, environment, physics, audio, SFX and constraints. These organize existing
prose; no new editor or API fields were added. Shorten duplicate instructions
before escalating a failed prompt.

Full Video 1.5 already supports first/last frames and up to four timed interior
keyframes. Set time in the frame controls on the one-third-second grid, not in
action timestamp blocks. A storyboard still/reference is not automatically a
timed frame pin. Keep Lite restrictions and the compiled request budget intact.
Existing sound/music editing and basic color controls cover the article's finish
stage; scene-wide comparison, compact sheet presets and structured look/shot-list
controls are proposals, not newly available tools. The article does not unlock
uploaded audio conditioning on the current subscription connection.
