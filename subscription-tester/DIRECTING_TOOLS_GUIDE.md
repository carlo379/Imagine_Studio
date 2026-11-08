# Directing tools

The storyboard, Video workspace and Camera Control share saved work with the
local Agent API. The routes below use `StudioClient.request` and are relative
to `/agent/v1`. Get project and episode IDs from
`GET productions/{production_id}/summary`. Use the episode ID as `scope` for
a series and `quick` for a Quick Video. Refresh a saved record on HTTP 409 and
reconcile concurrent edits before retrying.

## Frame Continuity Review

In the **Storyboard** board view, open **Frame Continuity Review**. Choose a
saved comparison or choose two frames and create one. Compare them side by
side or toggle between the two positions. Expand **Saved shot state** for the
captured image draft, video draft, shot direction and any saved camera staging. Use separate fields for
what should hold, what changes deliberately, and what you observed in the
images. To pass a frame forward, save the findings, pick the side and
destination, and choose **Attach as video reference**.

```python
path = f"productions/continuity/{production_id}/{scope}"
groups = client.request(path + "/frames")
# Pick actual frame records from groups, including role and timestamp.
# Two groups can be from different shots, or both choices can come from one.
frames = [
    {k: first[k] for k in ("asset_id", "role", "timestamp_s")} | {"shot_id": first_shot_id},
    {k: second[k] for k in ("asset_id", "role", "timestamp_s")} | {"shot_id": second_shot_id},
]
review = client.request(path, "POST", {
    "title": "Hunter face switch",
    "frames": frames,
    "consistent": "Armor, body pose, camera framing and lighting.",
    "changes": "Only the hunter’s face changes.",
})
route = path + "/" + review["id"]
# For each side, GET assets/{asset_id} returns the original image bytes.
review = client.request(route)
review = client.request(route, "PUT", {
    "expected_revision": review["revision"],
    "findings": observations_from_inspecting_the_two_images,
})
destination = client.request(f"productions/shots/{next_shot_id}")
client.request(route + "/attach", "POST", {
    "expected_revision": review["revision"],
    "side": 1,
    "target_shot_id": next_shot_id,
    "expected_video_revision": destination["video"]["revision"],
})
```

The list endpoint returns saved review summaries. Each review pins two local
workspace assets and the shot states at creation. Import URL-only frames as
workspace images and place them in the shot to include them in the picker.
The same asset may appear at different times or in different roles. Create a
new comparison for replacement frames. Attaching a frame uses the Video 1.5
reference slot and the normal approval and model limits. A 1080p draft moves
to 720p when a reference is added. It leaves the
destination’s selected storyboard image alone. A duplicate reference is a
no-op when submitted against the current draft revision.

## Generation Request Preview

Choose **Preview request** on a storyboard card or in the selected shot’s
**Video** toolbar. The app saves pending editor changes before compiling.
Review the input thumbnails, position or reference tags, speaker voice IDs,
render settings, and issues. **Save edit duration** stores the planned cut
length on the shot, independently of the render length. The Edit workspace
controls actual timeline trims.

```python
path = f"productions/shots/{shot_id}"
shot = client.request(path)
client.request(path, "PUT", {
    "expected_revision": shot["revision"],
    "intended_edit_duration": 1.5,
})
preview = client.request(path + "/generation-preview")
print(preview["render_duration"], preview["intended_edit_duration"])
print(preview["images"], preview["voices"], preview["issues"])
if preview["request"]:
    print(preview["request"].get("reference_audios", []))
```

The preview uses the generation compiler, local request resolver, start-frame
gate, and prompt checks. `request` shows the effective request with compact
media descriptors in place of inline bytes. `images` identifies each request
field, role and source. `voices` includes saved speaker assignments and
whether they are included. A voice bound only to a raw audio tag shows as
unlabeled until the draft supplies an identity or speaker label. The preview
can flag changed library snapshots without rewriting a deliberately frozen
shot. It does not test provider availability or submit a job.

## Shared Scene Blocking

On a storyboard shot select **Stage camera**, then **Shared Scene Blocking**.
Pick a saved layout for the episode or start one from the shot’s staging.
Use the top view and portrait preview together. Add box props and position
them with the horizontal, depth and base-height controls. The width, height,
length and rotation controls define each box. Actor controls set the pose and
position, and an eyeline points to a 3D target. Turn on **Set an actor mark for
this view** when a beat needs a different actor pose or position against the
same props and shared cast.

Add and name cameras for the angles you need. **Save scene layout** publishes
the geometry and cameras to the shared workspace. **Use view for this shot**
links the saved view so it opens on that shot next time. Open another shot
and select the same layout to link a different view. **Export portrait PNG**
downloads the saved view as a 720 × 1280 composition reference. PNG exports
omit labels, the eyeline overlays and framing guides. The preview is a static
blocking model, so check clearance at each critical position of a move.

```python
base = f"filmmaking/blocking/{production_id}/{scope}"
defaults = client.request("filmmaking/presets")["defaults"]
actor = dict(defaults["subjects"][0], name="Sorceress")
camera = defaults["camera"]
layout = client.request(base, "POST", {
    "title": "Market alley",
    "geometry": {
        "subjects": [actor],
        "props": [
            {"name": "Stall top", "x": 0, "y": 0.85, "z": 0,
             "width": 1.6, "height": 0.12, "depth": 0.8, "rotation": 0},
            {"name": "Cloak peg", "x": 1.1, "y": 1.7, "z": 0,
             "width": 0.1, "height": 0.1, "depth": 0.3, "rotation": 0},
        ],
        "eyelines": [{"subject": 0, "x": 1.1, "y": 1.7, "z": 0}],
        "environment": "Market alley", "style": "Overcast",
    },
    "views": [
        {"id": "slide", "name": "Low slide", "camera": dict(camera, elevation=-4, target_y=0.6),
         "marks": [{"subject": 0, "x": 0, "z": 0, "rotation": 0,
                    "pose": "slide", "arms": 0, "head": 0}]},
        {"id": "rivals", "name": "Rivals’ angle", "camera": dict(camera, yaw=-30)},
    ],
})
saved = base + "/" + layout["id"]
view = saved + "/views/slide"
link_route = f"filmmaking/shots/{shot_id}/blocking"
link = client.request(link_route)
client.request(link_route, "PUT", {
    "expected_revision": link["revision"],
    "expected_layout_revision": layout["revision"],
    "layout_id": layout["id"],
    "view_id": "slide",
})
stage = client.request(view)
png = client.request(view + "/reference.png", "POST", {"expected_revision": layout["revision"]})
```

To revise a layout, GET the saved record, then PUT its updated `title`,
`geometry`, and `views` with `expected_revision`. View IDs stay stable across
edits. A linked shot reads the latest saved version of its selected view.
To unlink, PUT the link revision with both IDs set to null. For a tavern
layout, place the drink using its base height on the bar and use a long thin
box for the sword. Set its rotation and position to mark the entrance side.

The API and Camera Control use the same local renderer for exported PNGs.
Install the repository’s Node and Canvas dependencies before exporting.
