# Story Studio

Story Studio organizes **series → episodes → scripts divided into scenes**. Image and Video Studio keep their existing controls. A linked draft adds only a small script context bar.

## Start a series and episode

1. Open **Story Studio** and select **New** beside Your series. Enter `Example Series`.
2. Open **Continuity & recurring assets** to record the character identities, world, tone and facts that should persist. Select recurring assets from the existing reference library. Save changes.
3. Select **New** beside Episode and enter `Teaser`, or another episode title.
4. Choose **Upload or paste script**. Import UTF-8 TXT, Markdown or DOCX up to 2 MB, or paste script text. PDF and other formats require exporting or copying text first.
5. Review **Preview scene divisions**. Explicit headings such as `Scene 1`, `## Scene 2`, `INT. STUDIO` and `EXT. DESERT` define scenes. Without recognized headings, the script is preserved in one scene. Text preceding the first heading becomes an Opening notes scene. Review and adjust imported titles/text before applying. To change boundaries, correct the headings in the pasted text and preview again.
6. Choose **Apply reviewed script**. Applying replaces the current scene list and preserves previous versions. Unique unchanged scene titles retain existing IDs during browser reimport; other imported scenes receive new IDs.

The complete episode has a local ceiling of 100,000 script/title characters and 150 scenes. Individual writing messages are limited to 12,000 characters. These are app policies, not provider limits.

## Whole episode and scene views

**Whole episode** displays the complete scene-divided script. Edit its title and episode notes here. Choose a scene from the outline to edit its title and script, move it up/down, or remove it. **Save script** saves a revision. Switching scenes/episodes or creating linked media saves pending edits first. Merely changing tabs does not discard edits; leaving the page warns about unsaved story changes.

Scene IDs remain stable when edited or reordered. Removal is recoverable through **Script revisions**. Restoring an older version creates a new revision. Export the latest episode to Markdown with **Export script**. Back up `.state/studio/stories.json` with the rest of local studio state while the server is stopped.

## Writing assistant

Choose **Writing assistant** to discuss an idea, outline a new episode, draft a scene-divided script or revise a selected scene. The verified connection is **ChatGPT via Codex subscription**, using the computer's existing Codex ChatGPT login and Codex allowance. No API-key or different-provider fallback is used. Additional subscription providers are not exposed until their supported integration is verified.

Set **Conversation scope** to Whole episode or Selected scene. The current episode provides broader context even when the proposed change is limited to one scene. Expand **Include previous episodes for continuity** and select up to five episodes from this series. Only selected earlier episodes are included; the assistant does not search unrelated files or other series. Series continuity notes and selected asset descriptions are included, not the assets' image files. The last eight completed messages/replies in this same scope are included in subsequent messages. A 160,000-character serialized context cap prevents oversized requests.

Each send requires **Approve Codex subscription usage for this message**. Script context and conversation are sent to OpenAI only when you send. The response appears locally as a reply and, optionally, a script proposal. Review the proposed scenes, then explicitly choose **Apply reviewed proposal**. Conversation replies never overwrite the script automatically. A proposal based on an older script revision cannot overwrite newer changes: copy useful text or request a fresh proposal instead.

The server uses the [official Codex app-server](https://learn.chatgpt.com/docs/app-server) through managed ChatGPT login. It creates an ephemeral session, disables shell, web, apps, image generation and MCP tools, and requests structured text output. The configured Codex text model is used without model/provider fallback. There is no silent retry after failure, timeout or restart. Writing uses subscription allowance, but the app cannot quote the exact debit or remaining balance. The writing transport is covered by simulated protocol tests and read-only session setup; a real writing reply needs a separately approved live test.

## Create images and videos for a scene

Select a scene, then choose **Create image** or **Create video**. This creates a linked draft without generating anything. Up to five selected recurring assets with image views are attached to a new image draft; their canonical identity snapshots use the existing Image Studio rules. Video drafts start empty so you can choose suitable reference views, voices and frames.

The generation prompt stays separate from the story script. The app does not paste a whole scene into the image/video prompt. Compose the particular shot, or have an agent prepare it using the script context. Every actual image/video generation still needs its own approval.

The context bar shows series, episode, scene and saved script revision. **View script** opens the script snapshot for that draft; **Read whole episode** provides its wider context. **Open episode** returns to the latest editable script. Later script edits preserve the old context of existing drafts and outputs. Reused/refined media drafts retain that context. Linked drafts are listed under their episode or scene and can be reopened.

## Agents and mock mode

All story actions are available under `/agent/v1/stories` with the existing local agent token. Discover routes in `/agent/v1/openapi.json` and limits/providers at `/agent/v1/stories/schema`. See [Agent API](AGENT_API.md). Story records use revision checks; writing submissions use explicit approval and idempotency keys.

Mock mode provides deterministic local writing proposals and media test patterns with no provider calls. It uses a separate writing conversation history from live mode. Series/scripts are common within the chosen local state directory; use an isolated `--state-dir` when practicing so test records do not enter your real library.

### Classify imported script sections

Before **Apply reviewed script**, choose **Scene**, **Notes**, or **Other** for each detected section. Opening text before the first scene defaults to Notes. Titles and text remain editable. Scenes become the episode scene list; Notes and Other append to Episode notes with labeled titles, preserving existing notes. An import with no Scene sections keeps the current scene list. Supporting sections are included in script exports and writing context. Previous scripts remain in revisions. Episode notes have a 10,000-character limit; an oversized import reports an error without changing the episode.

### Focused import review

Upload or paste a script, then choose **Review sections**. A compact outline shows every section and its type. Select a section to edit its title and text; use the **Scene / Notes / Other** buttons to classify it. Changes stay in the review when switching sections. **Change source** returns to the original script input; parsing again starts a new review. The bottom bar summarizes what will be applied and keeps **Apply to episode** visible. No script changes until you apply.
