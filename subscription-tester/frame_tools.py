"""Local video frame extraction and revision-safe image placement; no generation calls."""
import base64
import copy
import json
import math
import shutil
import subprocess
import uuid
from agent_api import APIError, blank


def capture(app, job, data):
    timestamp = data.get('timestamp_s')
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < 0:
        raise APIError('invalid_timestamp', 'Choose a finite, nonnegative video timestamp in seconds.')
    if job['status'] != 'done' or not job.get('video'):
        raise APIError('video_unavailable', 'Choose a completed video before capturing a frame.')
    if set(data) - {'timestamp_s', 'data_url'}:
        raise APIError('invalid_capture', 'Use a recorded video job and timestamp; external URLs are not accepted.')
    path = app.download(job['id'])
    duration = job['settings']['duration']
    if shutil.which('ffprobe'):
        try:
            info = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)], capture_output=True, check=True, timeout=20).stdout)
            duration = float(info['format']['duration'])
        except (subprocess.SubprocessError, ValueError, KeyError):
            raise APIError('video_unreadable', 'The saved video could not be inspected.') from None
    if timestamp > duration + .001:
        raise APIError('invalid_timestamp', f'Choose a timestamp between 0 and {duration:g} seconds.')
    image = data.get('data_url')
    method = 'browser'
    if image is None:
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            raise APIError('capture_dependency', 'Agent frame capture requires ffmpeg and ffprobe. Browser capture is still available.')
        method = 'ffmpeg'
        try:
            result = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(min(timestamp, max(0, duration - .05))), '-i', str(path), '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True, check=True, timeout=30)
            if not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError()
            image = 'data:image/png;base64,' + base64.b64encode(result.stdout).decode()
        except (subprocess.SubprocessError, ValueError):
            raise APIError('capture_failed', 'Could not decode this frame. Try a nearby timestamp.') from None
    asset = app.upload({'name': f'Video frame at {timestamp:.3f}s', 'data_url': image})
    with app.lock:
        asset.update(source_video_job_id=job['id'], frame_seconds=timestamp, capture_method=method)
        app.agent.save(app.assets_path, app.assets)
    return copy.deepcopy(asset)


def place(api, asset_id, data):
    asset, _ = api.app.asset(asset_id)
    if asset.get('generated') and not asset.get('approved'):
        raise APIError('approval_required', 'Review and approve this Image Studio candidate first.')
    new = data.get('new_scene') is True
    if new and data.get('scene_id'):
        raise APIError('invalid_target', 'Choose a new scene or an existing scene, not both.')
    record = None if new else api.record(data.get('scene_id'))
    if record and (record['archived'] or data.get('expected_revision') != record['revision']):
        raise APIError('revision_conflict', 'Restore the scene or fetch its latest revision before placing an image.', 409)
    scene = blank() if new else copy.deepcopy(record['scene'])
    before = copy.deepcopy(scene)
    target = data.get('target')
    advanced = scene['model'] == 'grok-imagine-video-1.5'
    if target not in ('first', 'last', 'reference', 'keyframe'):
        raise APIError('invalid_target', 'Choose first frame, last frame, reference image or keyframe.')
    if scene['model'] not in ('grok-imagine-video-1.5', 'grok-imagine-video-1.5-lite'):
        raise APIError('unsupported_model', 'Choose Video 1.5 or Lite before changing this historical scene.')
    if not advanced and target != 'first':
        raise APIError('unsupported_target', 'References, last frames and keyframes require Video 1.5.')
    if target in ('first', 'last'):
        if scene[target] and data.get('replace') is not True:
            raise APIError('occupied_frame', 'Enable replacement to overwrite the existing frame.')
        scene[target] = asset
    elif target == 'reference':
        if len(scene['refs']) >= 14:
            raise APIError('reference_limit', 'Use at most fourteen reference images.')
        scene['refs'].append({'id': uuid.uuid4().hex, 'source': asset})
    else:
        slot = data.get('slot')
        if isinstance(slot, bool) or not isinstance(slot, int) or not 0 < slot < scene['duration'] * 3:
            raise APIError('invalid_slot', 'Keyframe slot must be an integer on the ⅓-second grid, strictly inside the video.')
        existing = next((k for k in scene['keys'] if k['slot'] == slot), None)
        if existing:
            if data.get('replace') is not True:
                raise APIError('occupied_frame', 'This keyframe time is occupied. Choose another time or enable replacement.')
            existing['source'] = asset
        else:
            if len(scene['keys']) >= 4:
                raise APIError('keyframe_limit', 'Use at most four keyframes.')
            scene['keys'].append({'id': uuid.uuid4().hex, 'source': asset, 'slot': slot})
    if target in ('last', 'reference', 'keyframe') and scene['resolution'] == '1080p':
        scene['resolution'] = '720p'
    api.retag(before, scene)
    scene = api.normalize(scene)
    if new:
        return api.create({'title': data.get('title', 'New scene from image'), 'scene': scene})
    return api.edit(record['id'], {'expected_revision': data['expected_revision'], 'scene': scene})
