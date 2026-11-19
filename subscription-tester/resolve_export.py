"""Hand a cut to DaVinci Resolve (or Final Cut Pro) without screen control.

- FCPXML: picture clips in order on the main track, and sound stems on their own named
  audio tracks at their timeline times. In Resolve: File → Import → Timeline… and pick the
  .fcpxml; it links the original media files, which stay where they are.
- Lua: adds the stems as new named audio tracks to a copy of the timeline that is open in
  Resolve (for an edit already made there). Run it in Resolve's Workspace → Console (Lua)
  with dofile([[path]]).

The picture comes from a Studio editing timeline (timeline_id) or a list of local files;
the stems come from sound/stems or local files. Times snap to whole frames.
"""
import copy
import json
import threading
import time
import uuid
from pathlib import Path
from xml.sax.saxutils import quoteattr

from agent_api import APIError

FPS = (24, 25, 30, 48, 50, 60)
MAX_ITEMS = 200


def _num(value, name, low, high):
    if type(value) not in (int, float) or not low <= value <= high:
        raise APIError('invalid_export', f'{name} must be a number from {low} to {high}.')
    return float(value)


def _name(value, label, default=None):
    value = default if value is None else value
    if not isinstance(value, str) or not value.strip() or len(value) > 120 or any(ord(c) < 32 for c in value):
        raise APIError('invalid_export', f'{label} must be text of 1 to 120 characters.')
    return value.strip()


def _local(value, label):
    if not isinstance(value, str) or not value.startswith('/') or len(value) > 4096:
        raise APIError('invalid_path', f'{label}: path must be absolute.')
    path = Path(value)
    if not path.is_file():
        raise APIError('not_found', f'{label}: no file at {value}.', 404)
    return path


class ResolveExport:
    def __init__(self, app, save_json):
        self.app = app
        self.save_json = save_json
        self.root = Path(app.storage) / 'resolve'
        self.path = Path(app.storage) / 'resolve-exports.json'
        self.lock = threading.Lock()
        try:
            self.exports = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.exports = []

    # ----- inputs -----
    def _media_info(self, path):
        from delivery_check import probe
        from sound_tools import duration
        try:
            info = probe(path)
            return dict(duration=info['duration_s'], video=True, audio=info['audio'] is not None,
                        width=info['video']['width'], height=info['video']['height'])
        except APIError:
            return dict(duration=duration(path), video=False, audio=True, width=None, height=None)

    def _picture_from_timeline(self, identity):
        try:
            timeline = self.app.editing.p.get(identity, 'timeline')
        except (ValueError, KeyError):
            raise APIError('not_found', 'Editing timeline not found.', 404) from None
        clips, at = [], 0.0
        for i, clip in enumerate(timeline.get('clips', [])):
            if clip.get('source', {}).get('kind') == 'gap':
                at += clip['out'] - clip['in']
                continue
            meta, path = self.app.editing.source(clip['source'])
            if meta.get('image'):
                raise APIError('invalid_export', f'Clip {i + 1} is a still image; render it to a video clip first or leave it out.')
            overlap = (clip.get('transition') or {}).get('duration', 0) or 0
            at = max(0.0, at - overlap)
            clips.append(dict(path=str(path), in_s=clip['in'], duration_s=clip['out'] - clip['in'], at_s=at, name=clip.get('label') or meta.get('name')))
            at += clip['out'] - clip['in']
        stems = []
        for item in timeline.get('audio', []):
            meta, path = self.app.editing.source(item['source'])
            stems.append(dict(path=str(path), at_s=item.get('start', 0), in_s=item['in'], duration_s=item['out'] - item['in'],
                              track=(item.get('lane') or 'audio').title(), name=item.get('label')))
        return timeline.get('title') or 'Studio timeline', (timeline.get('output') or {}).get('fps', 24), clips, stems

    def _picture(self, items):
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
            raise APIError('invalid_export', f'video must list 1 to {MAX_ITEMS} clips.')
        out, at = [], 0.0
        for i, item in enumerate(items):
            label = f'video clip {i + 1}'
            if not isinstance(item, dict) or set(item) - {'path', 'in_s', 'duration_s', 'at_s', 'name'}:
                raise APIError('invalid_export', f'{label}: fields are path, in_s, duration_s, at_s and name.')
            path = _local(item.get('path'), label)
            start = _num(item.get('in_s', 0), f'{label} in_s', 0, 36000)
            length = _num(item['duration_s'], f'{label} duration_s', 0.01, 36000) if 'duration_s' in item else None
            at = _num(item['at_s'], f'{label} at_s', 0, 36000) if 'at_s' in item else at
            out.append(dict(path=str(path), in_s=start, duration_s=length, at_s=at, name=item.get('name')))
            if length is not None:
                at += length
            else:
                at += self._media_info(path)['duration'] - start
        return out

    def _stems(self, items):
        if items is None:
            return []
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise APIError('invalid_export', f'audio must list up to {MAX_ITEMS} stems.')
        out = []
        for i, item in enumerate(items):
            label = f'audio stem {i + 1}'
            if not isinstance(item, dict) or set(item) - {'stem_id', 'path', 'track', 'at_s', 'in_s', 'duration_s', 'name'}:
                raise APIError('invalid_export', f'{label}: fields are stem_id or path, track, at_s, in_s, duration_s and name.')
            if isinstance(item.get('stem_id'), str):
                record = self.app.sound.stem(item['stem_id'])
                path = self.app.sound.stem_file(record['id'])
                name = item.get('name') or record['name']
            else:
                path = _local(item.get('path'), label)
                name = item.get('name') or path.stem
            out.append(dict(path=str(path), track=_name(item.get('track'), f'{label} track', name), name=name,
                            at_s=_num(item.get('at_s', 0), f'{label} at_s', 0, 36000), in_s=_num(item.get('in_s', 0), f'{label} in_s', 0, 36000),
                            duration_s=_num(item['duration_s'], f'{label} duration_s', 0.01, 36000) if 'duration_s' in item else None))
        return out

    # ----- writers -----
    @staticmethod
    def fcpxml(title, fps, width, height, clips, stems, media):
        """FCPXML 1.9: clips on the primary storyline, stems as connected clips on their own lanes."""
        frames = lambda seconds: max(0, round(seconds * fps))
        t = lambda n: f'{n}/{fps}s' if n else '0s'
        assets, ids = [], {}
        for path in dict.fromkeys([c['path'] for c in clips] + [s['path'] for s in stems]):
            info = media[path]
            ids[path] = f'a{len(ids) + 2}'
            attrs = (f' hasVideo="1" format="r1"' if info['video'] else '') + \
                    (' hasAudio="1" audioSources="1" audioChannels="2" audioRate="48000"' if info['audio'] else '')
            assets.append(f'    <asset id="{ids[path]}" name={quoteattr(Path(path).stem)} start="0s" duration="{t(frames(info["duration"]))}"{attrs}>\n'
                          f'      <media-rep kind="original-media" src={quoteattr(Path(path).as_uri())}/>\n    </asset>')
        lanes = {}
        for stem in stems:
            lanes.setdefault(stem['track'], -(len(lanes) + 1))
        spine = []
        clips = sorted(clips, key=lambda c: c['at_s'])
        cursor = 0
        placed = []
        for clip in clips:
            start_f, in_f = frames(clip['at_s']), frames(clip['in_s'])
            length_f = frames(clip['duration_s'] if clip['duration_s'] is not None else media[clip['path']]['duration'] - clip['in_s'])
            if start_f > cursor:
                spine.append(dict(kind='gap', offset=cursor, start=0, duration=start_f - cursor, children=[]))
            start_f = max(start_f, cursor)
            spine.append(dict(kind='clip', clip=clip, offset=start_f, start=in_f, duration=length_f, children=[]))
            cursor = start_f + length_f
            placed.append(spine[-1])
        total = cursor
        for stem in stems:
            at_f, in_f = frames(stem['at_s']), frames(stem['in_s'])
            length_f = frames(stem['duration_s'] if stem['duration_s'] is not None else media[stem['path']]['duration'] - stem['in_s'])
            total = max(total, at_f + length_f)
            if at_f >= cursor or not spine:
                spine.append(dict(kind='gap', offset=cursor, start=0, duration=max(1, at_f + length_f - cursor), children=[]))
                cursor = spine[-1]['offset'] + spine[-1]['duration']
            parent = next(p for p in spine if p['offset'] <= at_f < p['offset'] + p['duration'])
            parent['children'].append(dict(stem=stem, offset=parent['start'] + at_f - parent['offset'], start=in_f, duration=length_f))
        body = []
        for item in spine:
            kids = ''.join(
                f'\n          <asset-clip ref="{ids[k["stem"]["path"]]}" lane="{lanes[k["stem"]["track"]]}" offset="{t(k["offset"])}" '
                f'start="{t(k["start"])}" duration="{t(k["duration"])}" name={quoteattr(k["stem"]["track"] + ": " + k["stem"]["name"])} '
                f'audioRole={quoteattr("dialogue." + k["stem"]["track"])}/>' for k in item['children'])
            if item['kind'] == 'gap':
                body.append(f'        <gap name="Gap" offset="{t(item["offset"])}" start="0s" duration="{t(item["duration"])}">{kids}\n        </gap>')
            else:
                clip = item['clip']
                name = clip.get('name') or Path(clip['path']).stem
                body.append(f'        <asset-clip ref="{ids[clip["path"]]}" offset="{t(item["offset"])}" start="{t(item["start"])}" '
                            f'duration="{t(item["duration"])}" name={quoteattr(name)}>{kids}\n        </asset-clip>')
        return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.9">\n  <resources>\n'
                f'    <format id="r1" name="FFVideoFormat{height}p{fps}" frameDuration="1/{fps}s" width="{width}" height="{height}"/>\n'
                + '\n'.join(assets) + '\n  </resources>\n  <library>\n'
                f'    <event name={quoteattr(title)}>\n      <project name={quoteattr(title)}>\n'
                f'        <sequence format="r1" duration="{t(total)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">\n'
                '      <spine>\n' + '\n'.join(body) + '\n      </spine>\n        </sequence>\n      </project>\n    </event>\n  </library>\n</fcpxml>\n'), \
            dict(tracks=[{'track': name, 'lane': lane} for name, lane in lanes.items()], duration_s=round(total / fps, 3), frames=total)

    @staticmethod
    def lua(title, fps, stems):
        """Adds each stem on a new named audio track to a copy of the timeline open in Resolve."""
        lines = [f'-- Imagine Studio: add sound stems to a copy of the open timeline ({title}).',
                 '-- Run in Resolve: Workspace > Console > Lua, then dofile([[this file]]).',
                 'local resolve = resolve or (Resolve and Resolve())',
                 'local proj = resolve:GetProjectManager():GetCurrentProject()',
                 'local mp = proj:GetMediaPool()',
                 'local src = proj:GetCurrentTimeline()',
                 'if not src then print("Open the timeline to add sound to, then run this again."); return end',
                 f'local tl = src:DuplicateTimeline(src:GetName() .. {json.dumps(" + " + title)})',
                 'if not tl then print("Could not duplicate the timeline; nothing changed."); return end',
                 'proj:SetCurrentTimeline(tl)',
                 f'local folder = mp:AddSubFolder(mp:GetRootFolder(), {json.dumps(title + " sound")})',
                 'mp:SetCurrentFolder(folder)',
                 'local T0 = tl:GetStartFrame()',
                 'local tracks = {}',
                 'local stems = {']
        for stem in stems:
            start = round(stem['in_s'] * fps)
            end = start + round(stem['duration_s'] * fps) if stem['duration_s'] is not None else -1
            lines.append(f'  {{{json.dumps(stem["path"])}, {json.dumps(stem["track"])}, {round(stem["at_s"] * fps)}, {start}, {end}}},')
        lines += ['}',
                  'for _, s in ipairs(stems) do',
                  '  local idx = tracks[s[2]]',
                  '  if not idx then',
                  '    tl:AddTrack("audio", "stereo"); idx = tl:GetTrackCount("audio"); tracks[s[2]] = idx',
                  '    pcall(function() tl:SetTrackName("audio", idx, s[2]) end)',
                  '  end',
                  '  local r = mp:ImportMedia({s[1]}); local item = r and r[1]',
                  '  local clip = {mediaPoolItem = item, startFrame = s[4], trackIndex = idx, recordFrame = T0 + s[3], mediaType = 2}',
                  '  if s[5] >= 0 then clip.endFrame = s[5] end',
                  '  local placed = item and mp:AppendToTimeline({clip})',
                  '  print(string.format("A%d %s: %s", idx, s[2], (placed and placed[1]) and "placed" or "FAILED"))',
                  'end',
                  'print("Done: " .. tl:GetName())']
        return '\n'.join(lines) + '\n'

    # ----- route -----
    def create(self, data):
        allowed = {'title', 'timeline_id', 'video', 'audio', 'fps', 'width', 'height', 'output_folder'}
        if not isinstance(data, dict) or set(data) - allowed:
            raise APIError('invalid_export', 'Send title, timeline_id or video, optional audio, fps, width, height and output_folder.')
        if 'timeline_id' in data and 'video' in data:
            raise APIError('invalid_export', 'Send timeline_id or video, not both.')
        if 'timeline_id' in data:
            if not isinstance(data['timeline_id'], str):
                raise APIError('invalid_export', 'timeline_id must be an editing timeline ID.')
            default_title, default_fps, clips, timeline_stems = self._picture_from_timeline(data['timeline_id'])
        elif 'video' in data:
            default_title, default_fps, clips, timeline_stems = 'Imagine Studio cut', 24, self._picture(data['video']), []
        else:
            default_title, default_fps, clips, timeline_stems = 'Imagine Studio sound', 24, [], []
        stems = timeline_stems + self._stems(data.get('audio'))
        if not clips and not stems:
            raise APIError('invalid_export', 'Nothing to export: send video clips, a timeline_id or audio stems.')
        title = _name(data.get('title'), 'title', default_title)
        fps = data.get('fps', default_fps)
        if fps not in FPS:
            raise APIError('invalid_export', 'fps is one of ' + ', '.join(map(str, FPS)) + '.')
        media = {p: self._media_info(Path(p)) for p in dict.fromkeys([c['path'] for c in clips] + [s['path'] for s in stems])}
        first = next((media[c['path']] for c in clips if media[c['path']]['video']), {})
        width = data.get('width', first.get('width') or 1920)
        height = data.get('height', first.get('height') or 1080)
        if type(width) is not int or type(height) is not int or not 16 <= width <= 8192 or not 16 <= height <= 8192:
            raise APIError('invalid_export', 'width and height are whole pixels.')
        identity = uuid.uuid4().hex
        folder = data.get('output_folder')
        if folder is not None:
            if not isinstance(folder, str) or not folder.startswith('/') or not Path(folder).is_dir():
                raise APIError('invalid_path', 'output_folder must be an existing absolute folder.')
            folder = Path(folder)
        else:
            folder = self.root / identity
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        safe = ''.join(c if c.isalnum() or c in ' -_' else '_' for c in title).strip() or 'Imagine Studio'
        xml_path, lua_path = folder / f'{safe}.fcpxml', folder / f'{safe} - add sound.lua'
        n = 2
        while xml_path.exists() or lua_path.exists():
            xml_path, lua_path = folder / f'{safe} {n}.fcpxml', folder / f'{safe} {n} - add sound.lua'
            n += 1
        for stem in stems:
            if stem['duration_s'] is None:
                stem['duration_s'] = max(0.01, media[stem['path']]['duration'] - stem['in_s'])
        xml, layout = self.fcpxml(title, fps, width, height, clips, stems, media)
        xml_path.write_text(xml)
        if stems:
            lua_path.write_text(self.lua(title, fps, stems))
        record = dict(id=identity, title=title, created_at=time.time(), fps=fps, width=width, height=height,
                      clips=len(clips), stems=len(stems), fcpxml=str(xml_path), lua=str(lua_path) if stems else None, **layout,
                      how_to=['Resolve: File → Import → Timeline…, choose the .fcpxml. It links the original files where they are.',
                              'To add only the sound to a timeline already open in Resolve: Workspace → Console → Lua, then '
                              f'dofile([[{lua_path}]]).' if stems else 'No stems, so no Lua script.'])
        with self.lock:
            self.exports.append(record)
            self.save_json(self.path, self.exports[-200:])
        return copy.deepcopy(record)

    def file(self, identity, kind):
        with self.lock:
            record = next((r for r in self.exports if r['id'] == identity), None)
        if not record or not record.get(kind):
            raise APIError('not_found', 'Export not found.', 404)
        return Path(record[kind]).read_bytes()

    def dispatch(self, method, parts, data, key):
        if parts == ['exports']:
            if method == 'GET':
                with self.lock:
                    return 200, copy.deepcopy(list(reversed(self.exports)))
            if method == 'POST':
                return 201, self.create(data)
        if len(parts) == 3 and parts[0] == 'exports' and parts[2] in ('timeline.fcpxml', 'add-sound.lua') and method == 'GET':
            kind = 'fcpxml' if parts[2] == 'timeline.fcpxml' else 'lua'
            return 200, (self.file(parts[1], kind), 'application/xml' if kind == 'fcpxml' else 'text/plain; charset=utf-8')
        raise APIError('not_found', 'Resolve export route not found.', 404)
