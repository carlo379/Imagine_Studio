# Autonomous production guide

How an agent produces videos, episodes and series with Grok Imagine through Imagine
Studio, with high quality and controlled cost, while the human stays in charge of the
decisions that matter. Read this before generating anything as an agent.

Imagine Studio works in two modes that share the same projects, rules and data:

| Mode | Who operates Studio | How the human takes part |
| --- | --- | --- |
| **Agentic** (main mode) | An agent (Claude Code, Codex or another) through the [Agent API](AGENT_API.md) | Tells the agent what they want; the agent shows results and relays the human's decisions, in their own words |
| **Direct** | The human, in the browser at http://127.0.0.1:8765/ | Clicks the same decisions in Studio's panels and banners |

Every rule below is enforced by Studio in both modes. Model and session names, and the
human's words, are declared by the agent and cannot be verified by Studio: relaying them
honestly is the agent's responsibility, exactly as with `approved: true`.

## On this page

- [The loop at a glance](#the-loop-at-a-glance)
- [1. Learn the human's choices](#1-learn-the-humans-choices)
- [2. Develop the story](#2-develop-the-story)
- [3. Build each shot's kit](#3-build-each-shots-kit)
- [4. Propose a plan and get it approved](#4-propose-a-plan-and-get-it-approved)
- [5. Generate a take](#5-generate-a-take)
- [6. Review the take](#6-review-the-take)
- [7. Act on the verdict](#7-act-on-the-verdict)
- [8. Learn from every take](#8-learn-from-every-take)
- [Endpoints](#endpoints)
- [Error codes and what to do](#error-codes-and-what-to-do)
- [Settings and stored data](#settings-and-stored-data)
- [Limits](#limits)

## The loop at a glance

1. **Learn the human's choices:** the director and reviewer models, past verdicts, what a take costs.
2. **Develop the story:** series bible, characters, locations, script, shot list.
3. **Build each shot's kit:** 3D staging, approved first frame, last frame (end-state shots), middle frame (complex action), direction.
4. **Optionally propose a plan:** the shot list, takes per shot and a budget, to track progress and cost.
5. **Ask the human to approve the next take, then generate it.** This is **the one human stop**:
   `approved: true` with their own words (`human_words`), and, in the same call, their verdict
   on the previous take if they gave one.
6. **Review it:** optionally an independent reviewer session scores it; the human's verdict is all Studio needs.
7. **Act on the verdict:** keep → next shot; retry → fix and make one more take; reject → rethink.
8. **Learn:** every verdict, disagreement and optional usage reading improves the next prompt, review and estimate.

One take at a time, judged before the next. Generation with an approval for that take
never waits on anything else: no plan re-approval, no AI review, no usage reading, no
separate frame approval and no separate verdict call.

## Before you start: is the server current?

`GET /agent/v1/` and `GET schema` report `code`: the digest of the code the server loaded,
the digest on disk now, and `stale`. When `stale` is true the server was started before the
last code change and enforces old rules (for example, old approval stops). Ask the human to
restart Studio before generating. The SDK checks this once before the first generation and
warns with `StaleServerWarning`; the browser shows a banner.

## 1. Learn the human's choices

- `GET roles`: the **director** model (runs Studio, writes prompts) and the **reviewer**
  model (reviews takes) the human chose. If they have not chosen, ask; record their answer
  with `PUT roles` and `human_words`. When a director is chosen, every generation must
  declare `agent: {model, session_id, product}` with that model.
- `GET human-reviews`: every verdict so far (keep, retry, reject) with the prompt, tags,
  notes and the human's own words. **Read it before writing prompts.** It is this person's taste.
- `GET reviewer/agreement`: how often the AI reviewer agreed with the human, and recent disagreements.
- `GET usage/calibration`: the learned Grok usage % per second of video for 480p, 720p
  and 1080p, and whether readings are still needed.
- `GET kit/stats`: the human's keep rate by shot-kit completeness.
- `GET schema` and the [model prompting guides](../docs/prompting-guides/): model limits and how to write prompts.

## 2. Develop the story

Use the existing story tools before planning shots: the
[Series Bible and episode books](SERIES_BOOKS_GUIDE.md), [Story Studio](STORY_STUDIO_GUIDE.md),
[the production workspace](PRODUCTION_WORKSPACE_GUIDE.md) and the
[filmmaking tools](FILMMAKING_TOOLS_GUIDE.md). Approve character, location and prop
references before any shot uses them; continuity depends on them.

## 3. Build each shot's kit

Grok Imagine fails most often when it must invent too much. A **shot kit** gives it known,
approved pictures to move between. Build it for every shot before generating:

1. **Stage the shot in 3D** with Camera Control / Shared Scene Blocking
   ([Directing tools](DIRECTING_TOOLS_GUIDE.md)): mannequins, props, camera, lens,
   eyelines, a start mark and, when the shot has one, an end mark. Export the reference
   render and upload it. It becomes `staging_asset_id`.
2. **Make the first frame from the staging** with the image model and the character
   identities ([Image Studio](IMAGE_STUDIO_GUIDE.md)). Prefer the OpenAI subscription for
   stills: it does not use the Grok video allowance. Review and approve it.
3. **Last frame, only when the shot has a clear end state** ("he ends seated at the
   counter"). Make it by editing the approved first frame and approve it. Free-flowing
   motion (wind, drift, a slow orbit) is marked `free_motion` and has no last frame.
4. **Middle keyframe, only for complex action** (several beats, a turn and a reach, a fall).
   Make the key pose by editing the approved first frame, approve it and attach it as a
   keyframe strictly inside the take.
5. **Never send the staging render to the video model**, as a frame, keyframe or
   reference. Grok would animate the mannequins.
   A frame you edited locally and uploaded is approved in one of two ways: relay the human's
   approval with `POST assets/{id}/approve` (`{"human_words": "..."}`, or
   `client.approve_asset(id, words)`), or simply let the take's approval cover it (see
   [5. Generate a take](#5-generate-a-take)). In the browser, **Approve start frame** sits
   beside the generation request.
6. **Record the kit:**

```python
client.request(f"scenes/{scene_id}/kit", "PUT", {
    "expected_revision": scene["revision"],
    "camera": "Medium shot, 35 mm, slow push-in.",
    "action": "The knight crosses to the counter and sits.",
    "end_state": "He ends seated at the counter, facing the barkeep.",  # or "free_motion": True
    "last_frame_from_first": True,
    "complex_action": False,                # True also needs "middle_frame_from_first": True
    "staging_asset_id": staging_render_id,
})
```

`GET scenes/{id}/kit` returns a checklist; the kit is **ready** when every check passes:

| Check | Passes when |
| --- | --- |
| Direction | `camera` and `action` are written |
| End state decided | `end_state` is written, or `free_motion` is true (never both) |
| Complex action decided | `complex_action` is true or false |
| Staging | `staging_asset_id` names an uploaded render |
| First frame | attached, and approved if it was generated |
| Last frame (end-state shots) | attached, approved, and consistent with the first: `last_frame_from_first` is true, or `continuity_check_id` names a passed or human-accepted [continuity check](IMAGE_STUDIO_GUIDE.md#continuity-check-fixed-objects-between-a-first-and-last-frame) of the same two frames |
| Middle keyframe (complex action) | approved keyframe strictly inside the take, and `middle_frame_from_first` is true |
| No mockup leak | the staging render is not a frame, keyframe or reference |
| Prompt | validates with no issues and every named character attached |

A multi-beat action marked `complex_action: false` adds a visible **hint** for the human
instead of blocking. Editing a kit is a scene revision.

## 4. Propose a plan and get it approved

A **production plan** lists the shots, takes per shot (default 2, at most 5) and an
optional budget: a cap on total takes and on Grok usage percent.

```python
plan = client.request("plans", "POST", {
    "title": "Episode 3: The Return",
    "items": [{"scene_id": s1, "label": "Knight enters"}, {"scene_id": s2, "max_takes": 3}],
    "budget": {"usage_percent": 10, "max_takes": 8},
})
```

`GET plans/{id}` shows each shot's state, kit checklist and cost estimate ("expected", one
take per shot; "worst case", every allowed take), plus the usage spent so far. **A plan
cannot be approved until every shot's kit is ready.**

Plan approval is **optional**. In the usual flow each take is approved by the human right
before it is generated (see [5. Generate a take](#5-generate-a-take)), and that approval also
covers a plan that is unapproved or changed since, edited shots, and the plan's take and budget
limits, which are then recorded on the job as `plan.warnings`. Approve a plan only when the human
wants the agent to make takes **without** asking before each one. Then show them the plan: shots,
estimate, budget and kit hints, and relay their approval:

```python
plan = client.request(f"plans/{plan['id']}/approve", "POST",
    {"expected_revision": plan["revision"], "human_words": "Go ahead."})
```

In direct mode the human clicks **Approve plan** in the **Production plans** panel. Any change
to the plan's shots, takes or budget clears the approval; a title or notes change does not, and
editing a shot's scene (prompt, frames, kit) never does.

## 5. Generate a take

**The one human stop is here.** Show the human exactly what will be generated (prompt,
frames, duration, resolution) and ask for their go-ahead. Then send `approved: true` with
their words, verbatim, in `human_words`. If they also gave a verdict on the previous take
("the last one was too fast, go ahead with this one"), send it as `verdict` in the same call:

```python
job = client.generate(scene, approved=True, idempotency_key="ep3-s1-take2",
    human_words="Yes, the last one was too fast. Go ahead with this one.",
    verdict={"job_id": previous_job_id, "verdict": "retry",   # keep | retry | reject
             "notes": "Slow the walk down."},                # human_words defaults to the top-level words
    plan_id=plan["id"],                                       # optional: count the take in a plan
    agent={"model": "claude-opus-5-5", "session_id": "director-7f3a", "product": "Claude Code"})
result = client.wait_for_job(job["id"])
```

The same body works with `client.request(f"scenes/{id}/generate", "POST", {...})`. The
approval for this take covers:

- **the attached frames:** a start frame (or last frame or keyframe) that was uploaded or
  edited locally needs no separate approval; it must still be named and attached;
- **plans:** a plan that is not approved, or whose shot changed since, and its take and
  budget limits (they become `plan.warnings` on the job);
- **the review pause:** a previous take still waiting for a verdict does not block, and a
  rejected, unchanged shot can be generated again;
- **usage readings:** `usage_before_percent` is optional and never blocks (send it when the
  human offers it; it improves cost estimates).

What still refuses: a closed plan, a scene outside the plan, a shot the human already kept,
the wrong director model, a stale `expected_revision`, prompt conflicts and the live lock.
The job records the approval as `take_approval` (`human_words`, `approved_at`).

`approved: true` **without** `human_words`, or `plan_id` alone under an approved plan, still
works for autonomous runs, with the stricter rules: the previous take must have a verdict, the
start frame must be approved, the plan must be approved in its current version, the shot must
not have changed without a retry verdict, and take limits and the usage cap refuse. See
[Error codes](#error-codes-and-what-to-do).

Never retry a failed paid generation automatically. Resume polling (`POST jobs/{id}/resume`,
or `client.resume_job(id)`) instead of resubmitting: the job returns to `pending` at once, so
`wait_for_job` waits for the resumed attempt instead of returning the old error.

## 6. Review the take

When the take finishes, successful or failed, it waits for the human's verdict. The verdict
can be relayed on its own (below) or together with the approval of the next take (see
[5. Generate a take](#5-generate-a-take)).

**AI review (optional, when the human chose a reviewer model).** The human's verdict never
waits for it; a review sent after the verdict still counts toward reviewer agreement. Fetch `GET jobs/{id}/review-packet`.
Start a **new, separate session** on the chosen reviewer model, for example a Claude Code
subagent started with that `model` or `claude -p --model <model>` in a fresh session, or
`codex exec -m <model>` in a fresh session. Give it only the packet: the brief, the story
beat, the reference images, the contact sheet and sampled frames (download them with your
token and attach the files) and the human's past verdicts. Never pass your own notes or
reasoning. Submit its JSON:

```python
client.request(f"jobs/{job['id']}/ai-review", "POST", {
    "reviewer": {"model": "gpt-5.5", "session_id": "review-91c2", "product": "Codex"},
    "scores": {"story": 8, "identity": 9, "craft": 5, "performance": 7},
    "issues": [{"severity": "blocking", "category": "anatomy", "time_s": 2.1,
                "problem": "Her right hand merges with the cup.",
                "fix": "Cup in her left hand, fingers clearly visible."}],
    "frames_examined": 12,
    "summary": "Plays the entrance beat; the cup hand breaks.",
})
```

Studio computes the suggestion: story below 5 → **reject**; any blocking issue or any score
below 6 → **retry**; otherwise **keep**. A review must come from the chosen reviewer model, in
a different session from the director, and must report the frames it examined. If the
reviewer cannot run, submit `{"unavailable": true, "reason": "..."}`. Never invent a review.

**Human verdict.** Show the human the take (`GET jobs/{id}/download`) and, if you ran one,
the AI suggestion and its issues, and ask for their verdict. Relay their answer word for word
(the usage reading is optional):

```python
client.request(f"jobs/{job['id']}/human-review", "POST", {
    "verdict": "retry",                                   # keep | retry | reject
    "human_words": "Closer, but she smiles too early.",  # verbatim; required
    "notes": "Delay the smile until after the line.",     # optional, yours
    "tags": ["flat_acting"],                              # optional
    "usage_after_percent": 43.0,                          # optional
})
```

Tags: `bad_anatomy`, `off_model`, `wrong_action`, `flat_acting`, `continuity`, `great`.
In direct mode the human uses the review banner: AI suggestion, **✓ Keep**, **↻ Retry**,
**✗ Reject**, tags, notes and the usage %.

**Keeping an earlier take.** When the human prefers a take they judged before ("let's keep
the first one"), send the verdict on the latest take with `keep_job_id` naming the earlier
one; the verdict on the latest take is then `retry` or `reject`, and the earlier take becomes
the kept one (its first verdict stays in its `history`):

```python
client.request(f"jobs/{latest['id']}/human-review", "POST", {
    "verdict": "reject", "keep_job_id": first_take_id,
    "human_words": "let's keep the first one",
})
```

If every take of the shot is already judged, `POST jobs/{id}/keep` with the human's words
makes that take the kept one. In the review banner, **Keep an earlier take instead** does the
same.

## 7. Act on the verdict

| Verdict | Meaning | Next step |
| --- | --- | --- |
| **keep** | The take is good | The shot is finished under the plan. If the scene belongs to a storyboard shot, select the take there: `POST productions/shots/{shot_id}/select-take` with `{"kind": "video", "id": job_id}` |
| **retry** | Close; fix what the note says | Apply the note to the prompt (and frames if needed) and make one more take; the retry verdict authorizes a changed shot |
| **reject** | The shot does not work | Rethink it, show the human the changed shot and relay their approval of that take |

Under plan-only generation, when a shot runs out of takes or the plan reaches its budget,
stop and ask the human; with a per-take approval those limits are warnings.

## 8. Learn from every take

- **Taste:** every verdict is saved with the human's words and read before the next prompt.
- **Reviewer calibration:** each packet carries recent disagreements, so the reviewer learns
  this person's taste; `GET reviewer/agreement` shows the agreement rate by reviewer model.
- **Cost:** each before/after pair of Usage readings becomes a sample of % per second. A
  resolution is established after 3 clean samples that agree within 50% of their median, or
  after 6 samples. Samples are discarded after a weekly reset or when another generation ran
  between the readings. Readings are always optional; established resolutions get estimates in plans.
- **Kit:** `GET kit/stats` compares keep rates for complete and incomplete kits, first-and-last
  versus first-only frames, and takes with a middle keyframe.

## Endpoints

Agent paths are relative to `/agent/v1` and need the workspace bearer token. Browser paths
are for the human's local Studio tab. `openapi.json` has the exact shapes.

| Purpose | Agent API | Browser |
| --- | --- | --- |
| Director and reviewer models | `GET` / `PUT roles` (`human_words` required) | `GET` / `POST /api/roles` |
| Shot kit and checklist | `GET` / `PUT scenes/{id}/kit` | `GET` / `POST /api/scenes/{id}/kit` |
| Keep rate by kit | `GET kit/stats` | `GET /api/kit-stats` |
| Plans | `GET` / `POST plans`, `GET` / `PUT plans/{id}` | `GET /api/plans`, `GET /api/plans/{id}`, `POST /api/plans`, `POST /api/plans/{id}/update` |
| Approve or close a plan | `POST plans/{id}/approve` (`human_words` required), `POST plans/{id}/close` | `POST /api/plans/{id}/approve`, `POST /api/plans/{id}/close` |
| Generate a take (the one stop) | `POST scenes/{id}/generate` with `approved: true` and `human_words` (optional `verdict`, `plan_id`) | **Generate video** (Grok usage % optional) |
| Approve an uploaded or edited image | `POST assets/{id}/approve` (`human_words` required) | **Approve start frame** beside the request, `POST /api/assets/{id}/approve` |
| Review packet and frames | `GET jobs/{id}/review-packet`, `GET jobs/{id}/review-frames/{name}` | `GET /api/jobs/{id}/review-packet`, `GET /api/jobs/{id}/review-frames/{name}` |
| AI review (optional) | `POST jobs/{id}/ai-review` | shown in the review banner |
| Human verdict | `POST jobs/{id}/human-review` (`human_words` required), or `verdict` on the next generate | review banner, `POST /api/video/human-review` |
| Keep an earlier take | `keep_job_id` on the verdict, or `POST jobs/{id}/keep` (`human_words` required) | **Keep an earlier take instead** in the review banner, `POST /api/video/keep` |
| Is the server current? | `GET /` or `GET schema` → `code.stale`; the SDK warns (`StaleServerWarning`) before the first generation | a banner when the server runs older code |
| Final file ready to post? | `POST delivery/checks`, then `POST delivery/checks/{id}/fix` (see the [sound and delivery guide](SOUND_AND_DELIVERY_GUIDE.md)) | `/delivery` page |
| Usage reading after a take | with the verdict, or `POST jobs/{id}/usage` | `POST /api/video/usage` |
| Verdict log (taste) | `GET human-reviews` | `GET /api/human-reviews` |
| Reviewer agreement | `GET reviewer/agreement` | `GET /api/reviewer-agreement` |
| Cost calibration | `GET usage/calibration` | `GET /api/usage-calibration` |

## Error codes and what to do

| Code | Meaning | What to do |
| --- | --- | --- |
| `human_review_required` | The previous agent take waits for a verdict and this call has no take approval | Ask the human; send their verdict, or `approved: true` + `human_words` (+ `verdict`) for the next take |
| `start_frame_required` | The start frame is missing, not attached, or not approved | Attach it; approve it with the take's `human_words` or `POST assets/{id}/approve` |
| `shot_rejected` | The human rejected this unchanged scene and this call has no take approval | Rethink the shot, or relay the human's approval of this take |
| `shot_kit_incomplete` | The shot kit is not ready | Read `GET scenes/{id}/kit` and complete what is missing |
| `plan_not_approved` | Plan-only generation, and the plan was never approved or changed since | Ask the human to approve this take (`approved: true` + `human_words`) |
| `not_in_plan` | The scene is not in the plan | Add it with `PUT plans/{id}`, or leave out `plan_id` |
| `plan_scene_changed` | Plan-only generation, and the shot changed without a retry verdict | Ask the human to approve this take |
| `plan_item_done` | The human kept a take of this shot | Move to the next shot |
| `plan_takes_exhausted` | Plan-only generation, and this shot used every allowed take | Ask the human to approve this take |
| `plan_budget_exceeded` | Plan-only generation, and the take limit or usage cap would be passed | Ask the human to approve this take |
| `invalid_approval` | `human_words` is empty or too long | Quote the human's approval verbatim (1–2,000 characters) |
| `plan_closed` | The plan is closed | Stop |
| `director_identity_required`, `wrong_director_model` | The human chose a different director model | Declare `agent`, or switch to the chosen model |
| `wrong_reviewer_model`, `reviewer_not_independent` | Review from another model, or from the director's session | Start a fresh session on the chosen reviewer model |
| `invalid_review`, `review_exists` | Malformed review (missing scores or frames), or already reviewed | Fix the JSON; one AI review per take |
| `approval_required`, `idempotency_required` | No authorization (or `human_words`/`verdict` without `approved: true`), or no idempotency key | Send `approved: true` with `human_words` and an 8–100 character key |

`ai_review_required` and `usage_reading_required` are retired: an AI review and usage
readings are optional and never block.

## Settings and stored data

| Item | Where | Notes |
| --- | --- | --- |
| `human_review_after_agent_video` | `studio-config.json` | `true` by default; every agent take waits for a verdict, which only blocks generation without a take approval |
| Director and reviewer models | private workspace `agent-roles.json` | Set by the human (browser) or relayed with their words |
| Plans | private workspace `plans.json` (`mock-plans.json` in mock mode) | Revisioned; approval tied to a fingerprint of shots, takes and budget |
| Verdicts, AI reviews, usage readings, kit snapshots | each job in the generation history | Read through `human-reviews`, `reviewer/agreement`, `usage/calibration`, `kit/stats` |
| Review frames and contact sheets | private workspace `review-frames/{job}` | Sampled once per take with FFmpeg |
| Shot kits | on each saved scene (`kit`) | Part of the scene revision |

## Limits

- Studio cannot read the Grok subscription balance. Costs are learned from the human's
  Usage readings; Grok work outside Studio between two readings spoils that sample.
- Model names, sessions, `human_words` and "made from the first frame" are declared by the
  agent; Studio records them but cannot verify them.
- The AI reviewer sees sampled frames: it cannot judge audio, lip sync or motion between
  frames, so the human keeps the final say.
- In direct mode there is no agent to start a reviewer session; the human reviews alone.
- Mock mode is free and never counts toward cost calibration. Practice the whole loop there first.
