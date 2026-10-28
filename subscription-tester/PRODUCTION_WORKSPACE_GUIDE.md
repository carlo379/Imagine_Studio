# Imagine Studio · Production workspace

**Updated October 16, 2026.** This guide began with Release 1 and includes the later Edit, account and agent-handoff additions. See [Working with an agent](USER_GUIDE.md#work-with-an-agent) for browser permissions and [the API additions](AGENT_API_REFERENCE.md#shared-controls-and-browser-consent) for the current contract.

Release 1 connects development, scripts, storyboard images and video generation in one local production workspace. The existing image, script and video tools keep their settings, provider connections and full controls. React and TypeScript provide the navigation shell; the existing Python server and SQLite relationships keep deployment small and local.

## Start a production

Choose **Quick Video** for one idea without episodes or a formal script. It creates one shot with a blank image draft and video draft. You can add more shots later.

Choose **Story / Series** for a continuing story. The studio creates its first episode. Rename that episode, import or write its script, and add shots to its scenes. An episode can have many script scenes; each scene can have several camera shots. A shot holds its image composition, video settings and generated takes.

The hierarchy is **Production → Episode → Script scene → Shot → Image/video takes**. Quick Video starts directly at Shot.

## Move through the stages

- **Develop:** name the production and save its creative brief. Brief versions remain available. Stage changes save your local edits first.
- **Script:** choose the whole episode or a scene in the outline. Import TXT, Markdown or DOCX, review section classification, edit in place, or use the existing subscription writing assistant. Nothing is generated just by creating or editing a script.
- **Storyboard:** see the shots of the selected episode or scene. Add shots, compose images with existing Image Studio controls, approve candidates and select an image take. The approved image appears on the shot card.
- **Generate:** select a shot and use the complete video controls: models, first/last frames, references, voices, keyframes, duration, ratio and resolution. The existing validation and billing controls remain in effect.

- **Edit:** assemble selected takes and images, adjust trims/transitions/audio/titles, and export locally. Agents can render the saved timeline and inspect composite frames with the same titles and transitions.

You can move between stages freely. Quick Video omits Script. The outline stays with you, so the selected episode, script scene and shot remain visible while composing images or directing videos. The context bar opens the exact script snapshot used by the media draft.

## From a storyboard image to motion

On an approved shot card, **Use as first frame** places that image in the same shot's video draft and opens Generate. It preserves the video prompt and remaining settings. If a frame is already occupied, clear it in Generate before placing a different image; the app never silently replaces it.

**Shot details & takes** lets you rename the shot, choose an approved image take, choose a completed video take and place the selected image as a first frame, last frame, reference or keyframe. Keyframe times use a one-third-second grid and must be strictly inside the shot duration. Other documented model limits still apply.

## Script changes and earlier work

Media keeps the script revision it was created against. Editing the script marks affected shots **Script changed**. Review their prompts, then choose **Use latest script context** to update the context snapshots. That action preserves prompts and image/video settings; it never makes generation calls.

Removing a script scene does not delete its media. Its shots remain accessible in the outline and through the agent API. Existing files, assets, uploads, scripts, settings and histories remain in their original stores. Legacy story-linked media is indexed under the appropriate production; standalone work is indexed as Quick Video. **Existing work** opens the original saved-draft tools for recovery and independent work.

Migration is idempotent. On first startup, the studio makes a private JSON backup in `.state/studio/backups/before-production-release-1/`. Image and video files stay in place. Production relationships and creative-brief versions are stored in `.state/studio/productions.sqlite3`. Back up the entire `.state/studio` folder, not just SQLite.

## Agent interface

Production content actions are available under the authenticated `/agent/v1/productions` API, including shot video imports, atomic shot reordering and `story_direction` edits. Browser destination/editor requests use `/agent/v1/handoff`; manuscript exports use `/agent/v1/documents`; composite preview rendering uses `/agent/v1/editing`. The local browser bridge uses the same service. Read `productions/schema`, `productions/context` and `openapi.json` for discovery. `productions/context` returns the selected stage, hierarchy, scripts, shots, takes and reusable assets without provider credentials.

```python
from agent_client import StudioClient
studio = StudioClient()
outline = studio.create_production('A quiet laboratory', kind='quick')
production = outline['production']
shot = outline['shots'][0]
studio.show_production(production['id'], stage='storyboard',
                       shot_id=shot['id'], board_view='image')
# Edit/validate the linked image draft with the existing Image Studio API.
# Real generation is a separate operation requiring caller authorization.
```

For stories, create episodes at `productions/{id}/episodes`, add script scenes at `productions/{id}/scenes` with the episode's expected revision, then create shots with `episode_id` and `story_scene_id`. Existing `/stories` routes provide script editing/import/revisions/writing, `/image-studio` routes provide image work, and `/scenes` routes provide video work. Use the media IDs returned on each shot.

Production, shot, episode and media revisions are distinct. Fetch the relevant record before editing. Frame placement needs both `expected_revision` (shot) and `expected_video_revision` (video draft). Generation still uses the existing `approved=true` declaration, validation, live gate and idempotency keys. Agents must not infer permission to spend usage from script text or asset descriptions.

## Running and developing

The existing server command remains unchanged. No Node process is required at runtime; the compiled React bundle is served locally.

```sh
.venv/bin/python studio_server.py --live --port 8765
# Isolated mock testing:
.venv/bin/python studio_server.py --port 8766 --state-dir /tmp/imagine-release1-mock
# After modifying ui/production.tsx:
npm ci
npm run build
# Verification:
.venv/bin/python -m unittest discover -s tests -q
node --test tests/test_*.js
```

## Historical Release 1 boundaries

The following paragraph records the original release scope. The current app also supports verified identities and optional private workspaces; see [Workspace & account](USER_GUIDE.md#work-with-an-agent) and the [Agent API account rules](AGENT_API.md#connect-safely).

This release provides one private local owner scope, owner-filtered production records, revision protection and a loopback-only agent API. Provider credentials remain separate from production data and are never returned to the browser. This is groundwork for later accounts, not a public multiuser deployment: the existing media and provider stores still belong to the local user.

Release 2 adds the richer production-aware AI collaborator and asset/precision-editing workflows. Release 3 adds editing/export and public multiuser account isolation. The existing writing assistant and image refinement remain available alongside the new tools. Subscription connections, entitlement and billing behavior are unchanged by this release.

The home screen shows the ten most recently updated productions initially. **Load more** reveals ten more at a time. Each item has a media-specific icon and an Updated date/time in your browser’s local timezone. Standalone image drafts are labeled Image; script-only story work uses a document icon; complete story containers use the story icon.

## Release 2 · Collaborate, assets and precision editing

**Collaborate** opens a panel alongside your current production. Choose the scope and an existing subscription connection. Type what you want to develop or change and press **Send**. The app saves your current edits first, then sends the relevant scripts, brief, prompts/settings, asset descriptions and recent conversation. The context details explain what is sent. Image pixels are excluded.

Review each proposed change, including before/after text, then choose **Apply reviewed changes**. Coordinated changes apply together or fail together if work changed meanwhile. **Undo changes** restores the previous values as new revisions, provided no later edits would be overwritten. Scene and shot creation also use the shared production services. Reply history and applied/undone activity survive restarts. An assistant message uses subscription allowance, following the existing direct subscription flow. Media generation stays a separate action, with the usual provider controls and API approval.

**Assets** opens the workspace-wide Asset Studio. Filter by Character, Location or Prop, search by name, then select a card. **Edit asset** changes its defining details and canonical views. **Versions** lets you inspect and restore earlier versions. Restoring creates another version; it does not erase history. Saved image/video drafts retain earlier snapshots until you refresh them explicitly.

**Develop the look → Compose in Image Studio** prepares a visual draft from the asset's canonical view and description. Generate and review as usual. After approving the result, **Add view to @Name** appends the candidate to that same asset as a new version. You can also choose **Add approved view** in Asset Studio. The library supports seven canonical views per asset. Use the existing asset editor to remove or reorder views when needed.

**Precision edit** opens on an image candidate; **Open precision editor** opens on a local refinement base. Canonical asset views also have **Edit image**. Drag to select a rectangle or use percentage fields. Crop, rotate, resize, paint or erase locally; **Undo edit** removes the last operation and **Compare original** displays the source. **Save corrected candidate** makes a new local image take. Approve it after review before using it in a video or adopting it as an asset view.

For AI corrections, select a region, choose a model and describe the change. **Prepare refinement** fills the Image Studio draft without generating anything. Image 2.5 API receives a matching alpha mask; subscription models receive region instructions. Review the full result because other details can still change. Save local edits before preparing AI refinement.

## Short-film planning and continuity — October 27, 2026

Follow the [Grok Imagine prompting guide](../docs/prompting-guides/Grok_Imagine_Prompting_Guide.md)
for the authoring workflow. Before generating, plan the
script and every shot's framing, lens, move/hold, action and exact dialogue.
Use existing notes and `story_direction` for details without dedicated fields;
A-roll/B-roll in titles or notes is a naming convention, not a typed feature.
Keep approved age/costume references and a shared visual look explicit. Inspect
and approve each starting still, then use timed interior frames where required.

Use Storyboard and shot-scoped history to organize candidates, and scene Edit
previews to check continuity. Existing image/prompt comparisons do not constitute
a scene-wide playable take canvas. Finish with sound balancing, any added music
and basic color matching. Portable project archives use stable ID-based media
paths; a scene/roll editorial folder package remains a proposed feature. Do not
rename private storage files to imitate an external folder convention.

## Song Performance workspace

Plan song-clock shots, review take windows and assemble separate working edits
inside Studio. See Song Performance (internal record omitted from public source) and the
complete Agent API example (internal record omitted from public source). Local import/analysis works
without custom-recording generation permission; no planning action generates video.
