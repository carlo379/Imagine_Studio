# Grok Imagine prompting guide (any project)

This guide is based on Grok Imagine’s article [“Inside Episode 1: The Oath”](https://x.com/imagine/article/2115214583983935517), merged with Imagine Studio’s validation and staging rules. Items marked (inferred) are practical extensions, not stated in the article.

**This guide is the main source of truth when another guide disagrees.** Studio's capability schema and request validator still govern settings, limits and prompt size.

Core idea: still frames drive the video. Decide everything in writing first, lock the look in images, then animate. If the keyframe is wrong, the video will be wrong.

## Standing rules (always apply)
1. **Always write video prompts in the 7-block format** (below), even for a single simple shot. A block with nothing to add says so briefly (for example "No added sound effects."). The user may waive optional steps for a given test (for example character sheet and middle keyframe); skip them only when told.
2. **Restrictions restate the non-negotiables by design** (no cuts, camera behavior, exact start frame), even if the Camera block already says it. Use ALL CAPS and CRITICAL: only for the few must-haves; plain sentences also work (the first test shot used none and came out clean).
3. **Ask once which image model to use** (GPT Images / ChatGPT or Grok Imagine Image) the first time images are created for a user, then save the answer to memory and reuse it. Re-ask only if they change their mind or it is unavailable.
4. **Dialogue timing check before any video.** Count the words of every spoken line. About 2.5 words per second plus about half a second of silence at each end: words / 2.5 + 1 = minimum seconds. If that exceeds the planned duration, extend it (Studio allows 1 to 15s) or trim the line, and tell the user. Example: 30 words needs about 13s, so 10s is too short.
5. **Get explicit approval before every real generation** (each uses allowance or money). Confirm settings against Studio's capability schema first.
6. **Use only voices the live provider accepts.** Studio's voice list can be out of date: Liora was listed but xAI rejected it with HTTP 400; carina worked. Check the provider's live list before generating.

## Workflow, in order
1. **Script.** Write the story and dialogue first. Keep runtime short for social formats.
2. **Shot list before generating anything.** For every shot record: shot size, lens, camera movement, action, and the exact dialogue.
3. **Organize files from the start.** Folder per scene, then A-roll / B-roll, e.g. `SCENE1_FIELD_BROLL`.
4. **One Image Studio Project for everything.** Keep every frame, prompt, and take together, grouped by shot. Compare takes side by side and check continuity (faces, wardrobe, lighting).
5. **Character sheets.** Per character: one close-up, one full front, one full back, on plain neutral grey. Make a NEW sheet whenever the character ages or changes costume.
6. **Character prompt.** Reuse the same text so the face stays the same. Expect occasional face drift. See template below.
7. **Locations.** Every prompt names shot size, time of day, mood, camera, lens, and film stock.
8. **One look across all shots.** Start from a mood board or style reference image and name camera, lens, and film stock in every prompt. Prefer an era or genre reference over a director name.
9. **Keyframes.** Place the character from the sheet into each location to make the start (and end) frames. Spend real time here before animating. Approve the starting still before animating.
10. **Video prompts in 7 blocks** (below), using the keyframes as references.
11. **Middle keyframes.** Grok Imagine lets you add a frame between start and end frames and choose the exact time it lands (in Studio: interior anchors on a one-third-second grid, full 1.5 only).  Only use it when needed to control timing or precise action control. Not always needed.
12. **Camera in every prompt.** Static/locked-off to set a scene; handheld when action starts. State it every time.
13. **Finish in the edit.** About 18 hours on the article's episode. Most sound effects came from Grok Imagine; music and a color grade were added on top.

## Character sheet prompt template
```
An ultra-photorealistic cinematic character reference sheet for [NAME], [role/title], [setting and era].
CHARACTER: [age range, build, skin, face features, eyes, hair, facial hair, expression, demeanor].
COSTUME: [every garment, materials, colors, wear, accessories; one distinctive prop described in detail and where it sits on the body].
LAYOUT: Single wide 16:9 image divided into THREE VERTICAL PANELS with thin white dividing lines.
LEFT: Large three-quarter facial close-up. CENTER: Full-body FRONT VIEW, arms relaxed, whole costume visible. RIGHT: Full-body BACK VIEW showing drape, hairstyle, footwear.
All three panels must depict the EXACT SAME [PERSON] wearing the EXACT SAME COSTUME, with identical proportions, materials, and accessories.
PHOTOGRAPHY: [reference photography style], neutral medium-gray seamless studio background, soft diffused lighting, natural skin texture, realistic fabric detail, subtle film grain. Grounded realism.
STRICTLY PHOTOREALISTIC. No illustrations, no CGI appearance, no text, no labels, no additional characters.
```

## The 7-block video prompt
Blocks, in this order, as labeled headers: [Camera & Style], [Subject Motion / Action], [Environment & Atmosphere], [Physics & Details], [Audio], [SFX], [Restrictions].
- Camera & Style: era/film stock/lens, frame rate and motion feel, grain; continuous shot or not; shot size and angle; camera movement or locked-off; how reference images are used.
- Action: start by matching the first frame; positions (frame left / center / right); entrances; middle and end references; end state.
- Environment: weather, wind, light, foreground movement.
- Physics: weight, contact, how fabric/water/objects react.
- Audio: music or none, natural sound, exact dialogue and speaker.
- SFX: specific sounds tied to visible actions, or none.
- Restrictions: short non-negotiables (no cuts, exact start/end images, camera behavior, depth ordering, everything visible at the end).
Rules of thumb: if a prompt fails, make it shorter; use left/right/center and numbered references to control staging; state camera movement explicitly even when none.

## Staging, hold and performance rules (from the Studio Video 1.5 guide)
Use these inside the 7 blocks.
- **Hold everything you don't mention.** Give every visible character and prop a position and a hold, each character's gaze and mouth state (open or closed), and the camera a position and hold. Unsaid things get invented motion.
- **Describe the body, not the idea.** Say what hands, heads and eyes physically do ("both hands apart above the pot, palms facing"), not "checks the pot". Name exact visible states, not moods.
- **One clear action per moment.** A tiny detail works best as the shot's only motion. Anything within reach gets touched, so keep hands away from things that should stay still.
- **Carry forward** the previous shot's end state and the scene's standing holds (locked camera, prop positions) unless the direction changes them.
- **Add nothing unasked.** The camera stays locked unless a move is requested. No extra gestures or sound effects.
- **If a beat fails twice, change the shot** (split it, close-up, new start frame, cut in the edit), not the wording, and ask approval first.
- **Order and dialogue.** List actions in order with then / after / once / before. Never write timestamp ranges or timed action blocks; duration is a generation setting. Keep the exact dialogue. Name each speaker and recipient, and describe the listener's attention and eyeline.
- **Use the real inputs.** Look at the supplied first frame and references and say what is visible. If a correction or script conflicts with the first frame, flag it instead of inventing geometry. The first frame sets the opening state, character sheets set identity (their panel layout does not set the scene), other references set clothing, props or environment. In Studio a pinned first frame is `<IMAGE_0>` and attached references start at `<IMAGE_1>`. Do not re-describe in text what the images already show unless it clears up a distinction.
- **Voices.** Bind each voice once in the header; in the body refer to the speaker by name only, never repeat audio tags or voice names. Name one performer per spoken line or laugh, and say if they are on or off screen. An off-screen performer stays unseen and visible characters listen silently, mouth closed, until their own turn. A mouthless robot's visor never forms a mouth. Wording reduces but cannot guarantee this; if it keeps failing, record the off-screen audio separately in the edit.
- **Audio setting.** With audio on, include required spoken lines and sound direction. With audio off the output is silent: flag that dialogue can't be heard and ask for a decision.
- **Return clean.** Before handing over, check image associations, physical feasibility, eyelines, camera consistency, dialogue and audio compatibility, and prompt size. Delete duplicated appearance prose, irrelevant style templates and stale corrections. A better take shows what happened in that take; it does not prove a universal rule.
- **Limits (full Video 1.5 reference workflow; check the runtime schema first):** up to 14 images, 3 preset voices, 4 internal pinned frames, 15 seconds, 720p (1080p for text and image workflows). Lite differs. Report unsupported inputs instead of dropping them. Interior keyframes sit on a one-third-second grid strictly inside the duration (slot = seconds x 3); keep timestamps out of the prose. A reference image alone does not enforce a transition time.
- **Review takes** for faces, wardrobe, lighting and screen direction, then finish sound balance, music and color in the edit. Generated sound is not uploaded-audio conditioning.

## Camera snippets
- Setup/establishing: static, locked-off, no movement.
- Action handheld (article's go-to): "Unstabilized handheld combat camera POV, violent jagged shake, the camera swinging, rolling and tilting wildly, the horizon tipping off-level with every stride, hard vertical bounces, sudden sideways whips, lurching drops and jolts, focus hunting and snapping, the frame barely holding the chaos. Chaotic, never aligned, never smooth, like a camera held by someone crouching inside a shadowed threshold tracking urgent movement. Fast, urgent, real-time speed, no slow motion." Adapt to the scene.

## Quality checklist before generating a video take
- Keyframe exactly right (character, wardrobe, location, light)? If not, fix the still first.
- Prompt in 7 blocks, naming shot size, camera movement, lens/film stock, time of day, mood?
- Same character prompt text and look reference as other shots in the scene?
- Start/middle/end images referenced?
- Audio explicit, dialogue exact, voice accepted by the provider, and duration long enough for the dialogue?
- Prompt as short as it can be while unambiguous?
- Takes compared for continuity before moving on.

## Using this in Imagine Studio
Series Bible and scripts = step 1; shot directions = steps 2 and 12; storyboard shots and starting frames = steps 5-9; takes review = continuity step; Library = reusable character sheets, locations, style reference; Edit timeline = step 13. Studio's validators and capability schema govern settings and size; this guide governs how prompts are written.

## Not stated in the article
No clip duration, resolution, aspect ratio (beyond 16:9 for the character sheet), or model-version guidance. Use Studio's capability schema for those instead of guessing.
