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
4. **Propose a plan:** the shots, takes per shot and a budget. **The human approves it once.**
5. **Generate one take** under the plan, with the usage reading taken just before.
6. **Review it:** an independent reviewer session scores it; **the human gives the verdict** and the usage reading after.
7. **Act on the verdict:** keep → next shot; retry → fix and make one more take; reject → rethink and ask for approval again.
8. **Learn:** every verdict, disagreement and reading improves the next prompt, review and estimate.

Studio pauses after every agent take until the human's verdict is recorded. One take
at a time, judged before the next.

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
| Last frame (end-state shots) | attached, approved, and `last_frame_from_first` is true |
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
cannot be approved until every shot's kit is ready.** Show the human the plan: shots,
estimate, budget and kit hints. Then relay their approval:

```python
plan = client.request(f"plans/{plan['id']}/approve", "POST",
    {"expected_revision": plan["revision"], "human_words": "Go ahead."})
```

In direct mode the human clicks **Approve plan** in the **Production plans** panel. Any change
to the plan's shots, takes or budget clears the approval; a title or notes change does not.

## 5. Generate a take

Under an approved plan, `plan_id` replaces the per-take `approved: true`. While the cost of
the shot's resolution is still being learned, first ask the human for their **Grok
Settings → Usage** percentage.

```python
job = client.request(f"scenes/{scene_id}/generate", "POST", {
    "expected_revision": scene["revision"],
    "plan_id": plan["id"],
    "agent": {"model": "claude-opus-5-5", "session_id": "director-7f3a", "product": "Claude Code"},
    "usage_before_percent": 41.5,          # or "usage_reading_unavailable": True
}, idempotency_key="ep3-s1-take1")
result = client.wait_for_job(job["id"])
```

Studio refuses the take when: the previous take still waits for a verdict, the plan is not
approved in its current version, the shot is not in the plan or its kit is not ready, the
shot changed without a retry verdict, a take limit or the usage cap is reached, the declared
director model is not the chosen one, or a needed usage reading is missing. See
[Error codes](#error-codes-and-what-to-do). Never retry a failed paid generation
automatically, and resume polling (`POST jobs/{id}/resume`) instead of resubmitting.

Without a plan, a single take can still be authorized with `approved: true` after the human
approved that exact request; every other rule still applies.

## 6. Review the take

When the take finishes, successful or failed, Studio pauses agent generation until the
human's verdict is recorded.

**AI review (when the human chose a reviewer model).** Fetch `GET jobs/{id}/review-packet`.
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

**Human verdict.** Show the human the take (`GET jobs/{id}/download`), the AI suggestion and
its issues, and ask for their verdict and, while costs are being learned, the Usage % again.
Relay their answer word for word:

```python
client.request(f"jobs/{job['id']}/human-review", "POST", {
    "verdict": "retry",                                   # keep | retry | reject
    "human_words": "Closer, but she smiles too early.",  # verbatim; required
    "notes": "Delay the smile until after the line.",     # optional, yours
    "tags": ["flat_acting"],                              # optional
    "usage_after_percent": 43.0,                          # or "usage_reading_unavailable": True
})
```

Tags: `bad_anatomy`, `off_model`, `wrong_action`, `flat_acting`, `continuity`, `great`.
In direct mode the human uses the review banner: AI suggestion, **✓ Keep**, **↻ Retry**,
**✗ Reject**, tags, notes and the usage %.

## 7. Act on the verdict

| Verdict | Meaning | Next step |
| --- | --- | --- |
| **keep** | The take is good | The shot is finished under the plan. If the scene belongs to a storyboard shot, select the take there: `POST productions/shots/{shot_id}/select-take` with `{"kind": "video", "id": job_id}` |
| **retry** | Close; fix what the note says | Apply the note to the prompt (and frames if needed) and make one more take; the retry verdict authorizes a changed shot |
| **reject** | The shot does not work | Rethink it. The unchanged scene cannot be generated again; show the human the changed shot and relay their approval of the plan again |

When a shot runs out of takes or the plan reaches its budget, stop and ask the human.

## 8. Learn from every take

- **Taste:** every verdict is saved with the human's words and read before the next prompt.
- **Reviewer calibration:** each packet carries recent disagreements, so the reviewer learns
  this person's taste; `GET reviewer/agreement` shows the agreement rate by reviewer model.
- **Cost:** each before/after pair of Usage readings becomes a sample of % per second. A
  resolution is established after 3 clean samples that agree within 50% of their median, or
  after 6 samples. Samples are discarded after a weekly reset or when another generation ran
  between the readings. Then readings for it are optional and plans show estimates.
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
| Generate a take | `POST scenes/{id}/generate` with `plan_id` or `approved: true` | **Generate video** (with **Grok usage % now**) |
| Review packet and frames | `GET jobs/{id}/review-packet`, `GET jobs/{id}/review-frames/{name}` | `GET /api/jobs/{id}/review-packet`, `GET /api/jobs/{id}/review-frames/{name}` |
| AI review | `POST jobs/{id}/ai-review` | shown in the review banner |
| Human verdict | `POST jobs/{id}/human-review` (`human_words` required) | review banner, `POST /api/video/human-review` |
| Usage reading after a take | with the verdict, or `POST jobs/{id}/usage` | `POST /api/video/usage` |
| Verdict log (taste) | `GET human-reviews` | `GET /api/human-reviews` |
| Reviewer agreement | `GET reviewer/agreement` | `GET /api/reviewer-agreement` |
| Cost calibration | `GET usage/calibration` | `GET /api/usage-calibration` |

## Error codes and what to do

| Code | Meaning | What to do |
| --- | --- | --- |
| `human_review_required` | The previous agent take waits for the human's verdict | Show it to the human; relay their verdict |
| `ai_review_required` | A reviewer model is chosen and this take has no AI review | Run the reviewer session and submit it (or `unavailable` with a reason) |
| `usage_reading_required` | This resolution's cost is still being learned | Ask the human for their Grok Settings → Usage % and send it |
| `shot_rejected` | The human rejected this unchanged scene | Rethink and change the shot |
| `shot_kit_incomplete` | The shot kit is not ready | Read `GET scenes/{id}/kit` and complete what is missing |
| `plan_not_approved` | The plan was never approved, or changed since | Show the human the current plan; relay their approval |
| `not_in_plan` | The scene is not in the plan | Add it, then ask for approval again |
| `plan_scene_changed` | The shot changed without a retry verdict | Ask the human to approve the plan again |
| `plan_item_done` | The human kept a take of this shot | Move to the next shot |
| `plan_takes_exhausted` | This shot used every take allowed since the last approval | Ask the human before making more |
| `plan_budget_exceeded` | The plan's take limit or usage cap would be passed | Ask the human before continuing |
| `plan_closed` | The plan is closed | Stop |
| `director_identity_required`, `wrong_director_model` | The human chose a different director model | Declare `agent`, or switch to the chosen model |
| `wrong_reviewer_model`, `reviewer_not_independent` | Review from another model, or from the director's session | Start a fresh session on the chosen reviewer model |
| `invalid_review`, `review_exists` | Malformed review (missing scores or frames), or already reviewed | Fix the JSON; one AI review per take |
| `approval_required`, `idempotency_required` | No authorization, or no idempotency key | Use an approved `plan_id` (or `approved: true`) and an 8–100 character key |

## Settings and stored data

| Item | Where | Notes |
| --- | --- | --- |
| `human_review_after_agent_video` | `studio-config.json` | `true` by default; pauses agent generation after every take |
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
