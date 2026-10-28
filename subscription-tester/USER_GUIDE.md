# User guide

Create a story, make its shots, and assemble the finished video. Imagine Studio
runs locally and keeps your projects in your private workspace.

**New here?** Follow [Your first video](#your-first-video).
Need to install the app? See [Setup](README.md).

## On this page

- [Your first video](#your-first-video)
- [Find your way around](#find-your-way-around)
- [Build a story](#build-a-story)
- [Make a short film from a planned shot list](#make-a-short-film-from-a-planned-shot-list)
- [Make and reuse images](#make-and-reuse-images)
- [Write and generate a shot](#write-and-generate-a-shot)
- [Review the result](#review-the-result)
- [Finish your production in Edit](#finish-your-production-in-edit)
- [Organize and delete productions](#organize-and-delete-productions)
- [Work with an agent](#work-with-an-agent)
- [Protect your work](#protect-your-work)
- [Troubleshooting](#troubleshooting)

## Your first video

1. Open the running app at **http://127.0.0.1:8765/**, or the port you configured.
2. Check the mode. **Mock** is local practice; **live** can use your account's allowance.
3. Create a project or a new video scene. Fresh installations contain no projects.
4. Choose a video model and its duration, shape and resolution.
5. Attach any references or starting image, then write what happens in the shot.
6. Review validation messages. In live mode, connect the selected provider first.
7. Click **Generate video** once. Review the result, then **Download video**.

> **Practice first:** In mock mode, the app uses a local test-pattern clip. It
> does not simulate your prompt, voice, requested duration or visual quality.
> External image URLs can still contact their hosts.

## Find your way around

| Stage | What you do |
| --- | --- |
| **Develop** | Define the story, characters, locations and props. |
| **Script** | Write or import the episode script. |
| **Storyboard** | Plan shots, starting frames and camera staging. |
| **Video** | Write directions, generate takes and review them. |
| **Edit** | Assemble clips, add audio and captions, then export. |

Use **Library** for reusable media and references. **Workspace & account** manages
connections. Separate Image Studio and Video Studio workspaces are also available.

For larger projects, use the [production workspace guide](PRODUCTION_WORKSPACE_GUIDE.md).

## Build a story

Create a **Story / Series**, then add an episode. Keep recurring identities and
world rules in the **Series Bible**. Put this episode's events in its storybook.

Write a script or upload one. Before applying an import, classify each section:

| Classification | Result |
| --- | --- |
| **Scene** | Becomes an episode scene. |
| **Notes / Other** | Goes into episode notes. |

Review titles, text and asset matches before creating the storyboard. Earlier
script versions remain available. AI writing proposals require your review and
an explicit apply step; they do not generate media.

See [Story Studio](STORY_STUDIO_GUIDE.md) for the full writing workflow.

## Make a short film from a planned shot list

The [Grok Imagine prompting guide](../docs/prompting-guides/Grok_Imagine_Prompting_Guide.md)
describes the shot-planning and prompt-authoring workflow.
Plan the script and shot list first, then approve character/costume references,
locations and a consistent look. Record each shot's framing, lens, camera behavior,
action and exact dialogue in the current script/direction/notes. Approve its
starting image before animating.

Check video direction for camera/style, action, environment, physics, audio, SFX
and constraints. Keep it concise; do not add effects just to fill a section.
Use actual middle-keyframe controls when a visual state needs a timed anchor,
then review adjacent shots for identity, wardrobe, light and continuity. Assemble
approved takes in Edit, balance generated sound with any added music, and match
color before export. Storyboard and shot histories provide organization; a
freeform multi-shot comparison canvas is a proposed addition.

## Make and reuse images

In **Image Studio**, choose a model, describe the image, and attach references.
Use **Prepare with AI**, or review a directly written prompt. Generate candidates,
then approve the one you want to use.

| Action | Use it when |
| --- | --- |
| **Save as reference** | A character, location or prop should recur. Review its name, category and description. |
| **Use in video** | An approved image should become a first frame, last frame, reference or keyframe. |
| **Capture frame** | You want to reuse a frame from a completed, readable video. |
| **Mirror** | You need a horizontally flipped copy. The original stays intact; check on-screen text. |

Type `@Handle` or choose a saved reference to reuse it. Removing the mention does
not remove the attached asset: remove its card separately. A scene keeps its own
reference snapshot, so editing the library does not silently change older scenes.

You can upload or drop an image, or paste PNG/JPEG/WebP pixels with **⌘V / Ctrl+V**
while an image slot is focused. First frames set the opening composition;
reference images guide identity. Put each image in the correct role.

See [Image Studio](IMAGE_STUDIO_GUIDE.md) for candidate review and refinement.

## Write and generate a shot

Use short, plain sentences. Describe physical actions and holds, with one idea
per sentence. Keep the approved dialogue and starting state.

```text
The gardener stands beside the gate, watching the visitor, mouth closed.
The visitor raises the lantern. The gardener looks at it.
The camera stays locked in a medium shot.
```

- State what each visible character and important prop does or holds still.
- Carry forward the previous shot's end state and the scene's standing holds.
- Express order with “then” or “after”; put duration in the controls, not timestamp blocks.
- Assign each voice once. In the direction, use the speaker's name rather than repeating voice tags.
- Keep off-screen speakers unseen and visible listeners silent during their turn.

There is no recommended prompt length or beat-count target. Validation enforces
the model's actual limits, including expanded reference context. Read the
[runtime video guide](../docs/prompting-guides/Grok_Imagine_Prompting_Guide.md)
for the full authoring rules.

**Prepare with AI is optional for video.** Review its suggestion before applying.
Image prompts need current preparation or recorded manual review. Changing image
settings can invalidate that review. Preparation and media generation are separate actions.

For a shot marked **Start frame required**, attach and approve the correct frame
before generating. Its thumbnail and approval state appear beside Generate.

Use **Scene geography, lessons & usage** to record positions, facing directions,
standing holds and lessons. The usage display distinguishes app attempts from
provider allowances; **unknown** means the provider did not report a number.

> **Before Generate:** Check the model, inputs, dialogue and validation. API image
> models require **Approve OpenAI API charges**. Account connection alone does
> not prove available quota. No generation runs automatically at startup.

## Review the result

Play the completed take. Download outputs promptly; provider links may expire.
Use **Reuse these settings** for another version, or create a new scene.

**Review against prompt** can identify differences and propose a revision.
Confirm findings and apply changes explicitly. Save useful lessons from reviewed
takes; they can inform later writing. Review has limits, especially for sampled
motion and spoken audio, so inspect the video yourself.

If a job is interrupted, use **Resume polling** when offered. That checks the
existing request rather than submitting a duplicate. A failed generation is not
automatically retried.

## Finish your production in Edit

1. Choose the episode and timeline. Open **Library** to find approved media and uploads.
2. Drag clips onto the timeline, or use **＋**. Select clips to trim, split or reorder.
3. Select a junction to choose a cut, dissolve or fade through black.
4. Add audio, titles, markers and captions. Use the inspector for exact timing.
5. **Save edit**, review a draft render, then choose **Export MP4**.

| Task | Control |
| --- | --- |
| Preview / pause | **Space** or Play. |
| Split the selected clip | **S**, with the playhead inside the clip. |
| Undo / redo | **⌘Z / ⇧⌘Z**, or the Ctrl equivalents. |
| Add a marker | **M**. |
| Try another assembly | **Duplicate timeline**; use **Make primary** to select the main version. |
| Assemble a scene into an episode | **Render into episode** from a scene timeline. |
| Add captions | Import SRT, or use a configured local transcriber. |

Removing a clip removes the timeline item, not its original media. Transitions
overlap neighboring clips and can shorten the assembled duration. Audio offsets
need unused source handles; trim the source or reduce the offset if none remain.

The live preview is approximate. Use **Render draft preview** to check the final
mix and picture effects before a full export. Local exports use FFmpeg and no AI
quota. Review export errors in the Output panel.

## Organize and delete productions

Use a production card's **···** menu to group it under a Story / Series, move it,
or make it standalone. Grouping organizes work without changing scripts or media.

**Move to Trash** hides a production from the active list. Restore it from
**Trash**. Deleting a story leaves its contained productions available separately;
restoring it can restore their grouping unless you moved them elsewhere.

## Work with an agent

Agents use the same projects and validation through the [Agent API](AGENT_API.md).
Review their changes before authorizing a live generation.

Browser draft sharing is optional and read-only. **Agent browser controls** are a
separate, time-limited permission for the shared tab. Signing in or changing an
identity still requires you. An unshared tab's unsaved edits are not visible to agents.

If edits conflict, keep your local draft and use **Save draft as copy** or review
the conflict. Discard local edits only when you intend to lose them.

## Protect your work

Projects and credentials live outside the app directory. See
[private storage locations](../docs/CONFIGURATION.md#private-user-storage).

Stop the server before backing up private storage. Keep backups private: they
can include credentials. Browser-only drafts need separate care; clearing browser
data removes those drafts but does not erase saved server projects. Use one
editing tab at a time when possible.

## Troubleshooting

| Problem | Next step |
| --- | --- |
| Generate is disabled | Check connection, validation, approval, starting-frame state and whether another operation is running. |
| Prompt or references are invalid | Read the message beside the prompt. Shorten repeated context or fix missing inputs and tags. |
| A saved reference looks outdated | Older scenes use snapshots. Remove and reattach the reference to use its latest version. |
| Save conflict | Keep the draft; refresh carefully or save it as a copy. |
| Provider limit / HTTP 429 | Wait and check provider usage. Do not repeatedly resubmit. |
| Sign-in rejected | Reconnect through the account controls and complete the provider's consent step. |
| Polling timed out | Check the saved job or resume polling; avoid duplicate generations. |
| Download fails | The link may have expired. Check whether the video was already cached locally. |
| Export fails | Read the captured FFmpeg error in Output; confirm the inputs are still available. |
| Transcription unavailable | Configure a local model or import an SRT. No model downloads happen automatically. |
| App will not open | Start the local server using [Setup](README.md#start-the-app). |

## Export and import a complete project

In **Your projects**, open a project’s **···** menu and choose **Export project…**.
The same control is available under project management while a project is open.
Save current edits and let active writing, generation and rendering finish first.
Studio saves the open editors before starting the export. Progress appears in the
menu; choose **Save ZIP as…** when it finishes to select a folder and filename.
The ZIP streams directly to that file without loading the entire video archive
into browser memory. You can cancel the picker without saving. In browsers
without a save picker, use **Download project ZIP**; enable the browser’s
“Ask where to save each file” download setting to choose its destination. You can close and reopen
the menu while it works.

The versioned ZIP contains:

- `project.json`: editable project records, relationships, saved revisions,
  Bible and storybooks, scripts, characters, locations, props, prompts, model
  settings, generation history, reviews, timelines and captions.
- `media/`: linked original images, videos, reference assets, uploaded audio/video,
  saved video exports and available request/review evidence.
- `documents/`: readable Markdown books, scripts and saved prompts.
- `Export report.json`: missing files and external image references.

A Story / Series export includes its grouped child productions. Shared assets
referenced by the project are copied into the archive. Unrelated projects,
account credentials, API keys, browser settings and browser-only unsaved
instructions are excluded. Export does not generate or regenerate media.
Completed provider videos are downloaded through the normal video cache when
needed. External image URLs remain external references and are listed in the
report; save those images to the project’s local assets before exporting for a
fully offline archive. Expired or deleted media is reported rather than silently
omitted. An incomplete archive can still be downloaded and imported.

Choose **Import project…** in **Your projects** and select the ZIP. Studio checks
the archive version, media sizes and SHA-256 checksums before saving. Import
creates a separate copy with new IDs and an **(imported)** suffix; it never
replaces an existing project or resumes provider requests. Choose **Open imported
project** when it finishes. Imported media can be used without the original
provider account; future generations require your own connection.

Current limits: 20 GB per ZIP, 50 GB total expanded content, 512 MB of project JSON,
and 100,000 ZIP members. Transfers run locally in the background. A server restart
interrupts an active transfer; retry it afterward. Finished exports remain in the
private workspace’s `project-archives/` folder. Download and retain your ZIP in
your own backup location. Import rolls back ordinary save failures; as with all
workspace writes, avoid stopping the server during the final save.

## Prepare an uploaded vocal recording for a video

In the video's **Voice & Audio** section, use **Uploaded recording · local
preparation** to upload a WAV/MP3, choose a saved workspace recording, listen to
it and set excerpt start/end seconds. **Preview selection** plays the selected
range. **Prepare & attach excerpt** saves an immutable local excerpt and attaches
it to the draft. Optionally associate it with an attached Character reference.
The panel displays the effective excerpt duration and warns when it differs from
the shot. Shot timing and silence are preserved. **Remove recording** removes
only the attachment; original audio and prepared excerpts remain available.

Preset voices are separate controls. Remove conflicting preset assignments
explicitly and enable audio. Keep the original song as the final edit master.

**Generation with an uploaded recording is currently blocked.** xAI documents
custom-audio video references only for trusted partners, and this connection's
contract and entitlement are unverified. The panel prepares local files; it does
not upload them to xAI or promise accurate singing/lip synchronization. Full
Video 1.5 at 480p/720p is a preparation target, not established combination support.
Local uploads accept audio-only WAV/MP3 up to 64 MiB and one hour, with excerpts
up to 15 seconds. Provider-specific format and combination limits are unknown.

## Song Performance workspace

Plan song-clock shots, review take windows and assemble separate working edits
inside Studio. See Song Performance (internal record omitted from public source) and the
complete Agent API example (internal record omitted from public source). Local import/analysis works
without custom-recording generation permission; no planning action generates video.
