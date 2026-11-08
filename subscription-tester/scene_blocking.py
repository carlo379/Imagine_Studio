"""Revisioned scene geometry and camera views for Camera Control."""
import math
import re
from agent_api import APIError
from directing_tools import active_shot, check_revision, scoped_record
from story_studio import text

KIND = 'scene-blocking'


def number(value, minimum, maximum):
    if type(value) not in (int, float) or not minimum <= value <= maximum or not math.isfinite(value):
        raise APIError('invalid_blocking', 'A layout position, size or rotation is out of bounds.')
    return value


def objects(value, limit, label):
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(item, dict) for item in value):
        raise APIError('invalid_blocking', f'Use up to {limit} {label}.')
    return value


def normalize(film, data, validate_assets=True):
    geometry = data.get('geometry')
    if not isinstance(geometry, dict) or set(geometry) != {'subjects', 'environment', 'style', 'props', 'eyelines'}:
        raise APIError('invalid_blocking', 'Supply subjects, environment, style, props and eyelines.')
    views = objects(data.get('views'), 16, 'camera views')
    if not views:
        raise APIError('invalid_blocking', 'Save at least one camera view.')
    base = {k: geometry[k] for k in ('subjects', 'environment', 'style')}
    props, eyelines, cameras = [], [], []
    for prop in objects(geometry['props'], 24, 'props'):
        bounds = dict(x=(-5,5), y=(0,4), z=(-5,5), width=(.02,8), height=(.02,5), depth=(.02,8), rotation=(-180,180))
        if set(prop) != {'name', *bounds}:
            raise APIError('invalid_blocking', 'Each prop needs a name, position, dimensions and rotation.')
        props.append(dict(name=text(prop['name'], 80, 'Prop name', True),
                          **{key: number(prop[key], *limits) for key, limits in bounds.items()}))
    for eye in objects(geometry['eyelines'], 4, 'eyelines'):
        if set(eye) != {'subject', 'x', 'y', 'z'} or type(eye['subject']) is not int:
            raise APIError('invalid_blocking', 'Set the actor index and target coordinates for each eyeline.')
        eyelines.append(dict(subject=eye['subject'], x=number(eye['x'],-5,5),
                             y=number(eye['y'],0,5), z=number(eye['z'],-5,5)))
    for view in views:
        if set(view)-{'id', 'name', 'camera', 'marks'} or not {'id','name','camera'} <= set(view) or not isinstance(view['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', view['id']):
            raise APIError('invalid_blocking', 'Each camera view needs a unique ID, name and camera controls.')
        stage = film.normalize_staging({**base, 'ratio': '9:16', 'camera': view['camera']}, validate_assets=validate_assets, allow_slide=True)
        marks = []
        for mark in objects(view.get('marks', []), 4, 'actor marks per view'):
            fields = {'x', 'z', 'rotation', 'pose', 'arms', 'head'}
            index = mark.get('subject')
            if set(mark) != {'subject', *fields} or type(index) is not int or not 0 <= index < len(stage['subjects']):
                raise APIError('invalid_blocking', 'A camera mark needs a staged actor index and complete pose controls.')
            subject = {**stage['subjects'][index], **{k: mark[k] for k in fields}}
            normalized = film.normalize_staging({**base, 'subjects': [subject], 'ratio': '9:16',
                'camera': stage['camera']}, validate_assets=False, allow_slide=True)['subjects'][0]
            marks.append(dict(subject=index, **{k: normalized[k] for k in fields}))
        if len({mark['subject'] for mark in marks}) != len(marks):
            raise APIError('invalid_blocking', 'Save at most one mark per actor in each camera view.')
        cameras.append(dict(id=view['id'], name=text(view['name'], 80, 'Camera view name', True), camera=stage['camera'], marks=marks))
    if len({v['id'] for v in cameras}) != len(cameras):
        raise APIError('invalid_blocking', 'Camera view IDs must be unique.')
    subjects = stage['subjects']
    if len({e['subject'] for e in eyelines}) != len(eyelines) or any(not 0 <= e['subject'] < len(subjects) for e in eyelines):
        raise APIError('invalid_blocking', 'Set at most one eyeline for each staged actor.')
    return dict(title=text(data.get('title'), 120, 'Layout title', True),
                geometry=dict(subjects=subjects, environment=stage['environment'], style=stage['style'],
                              props=props, eyelines=eyelines), views=cameras)


def view_stage(layout, view_id):
    view = next((v for v in layout['views'] if v['id'] == view_id), None)
    if not view:
        raise APIError('not_found', 'Choose a saved camera view from this layout.', 404)
    marks = {m['subject']: {k: v for k, v in m.items() if k != 'subject'} for m in view.get('marks', [])}
    subjects = [{**actor, **marks.get(i, {})} for i, actor in enumerate(layout['geometry']['subjects'])]
    return {**layout['geometry'], 'subjects': subjects, 'ratio': '9:16', 'camera': view['camera']}


def route(film, method, parts, data):
    p = film.p
    if len(parts) == 3 and parts[0] == 'shots' and parts[2] == 'blocking':
        shot = active_shot(p, parts[1])
        identity = 'blocking-link-'+shot['id']
        record = next((r for r in p.all('blocking-link') if r['shot_id'] == shot['id']),
                      dict(id=identity, shot_id=shot['id'], revision=0, layout_id=None, view_id=None))
        if method == 'GET':
            return 200, record
        if method == 'PUT':
            check_revision(p, record, data.get('expected_revision'))
            layout_id, view_id = data.get('layout_id'), data.get('view_id')
            if layout_id is not None or view_id is not None:
                if not isinstance(layout_id, str) or not isinstance(view_id, str):
                    raise APIError('invalid_blocking', 'Supply both layout and view IDs, or clear both.')
                layout = scoped_record(p, KIND, layout_id, shot['production_id'], shot.get('episode_id'))
                check_revision(p, layout, data.get('expected_layout_revision'))
                view_stage(layout, view_id)
            with p.sql:
                return 200, p.put('blocking-link', {**record, 'revision': record['revision']+1,
                                                    'layout_id': layout_id, 'view_id': view_id})
    if len(parts) >= 3 and parts[0] == 'blocking':
        pid, scope = parts[1:3]
        production = film.production(pid)
        eid = None if scope == 'quick' else scope
        if production['kind'] == 'story':
            p.episode(production, eid)
        elif eid is not None:
            raise APIError('invalid_scope', 'Use quick for a Quick Video.')
        if len(parts) == 3 and method == 'GET':
            return 200, [{k: r[k] for k in ('id', 'revision', 'title')} for r in p.all(KIND)
                         if (r['production_id'], r.get('episode_id')) == (pid, eid)]
        if len(parts) == 3 and method == 'POST':
            fields = normalize(film, data)
            with p.sql:
                return 201, p.new(KIND, production_id=pid, episode_id=eid, **fields)
        if len(parts) >= 4:
            record = scoped_record(p, KIND, parts[3], pid, eid)
            if len(parts) == 4 and method == 'GET':
                return 200, record
            if len(parts) == 4 and method == 'PUT':
                check_revision(p, record, data.get('expected_revision'))
                fields = normalize(film, data)
                linked = {r['view_id'] for r in p.all('blocking-link') if r['layout_id'] == record['id']}
                if linked - {view['id'] for view in fields['views']}:
                    raise APIError('view_in_use', 'Unlink or reassign shots before removing a camera view they use.', 409)
                with p.sql:
                    return 200, p.put(KIND, {**record, **fields, 'revision': record['revision']+1})
            if len(parts) == 6 and parts[4] == 'views' and method == 'GET':
                return 200, view_stage(record, parts[5])
            if len(parts) == 7 and parts[4] == 'views' and parts[6] == 'reference.png' and method == 'POST':
                from camera_renderer import render_reference
                check_revision(p, record, data.get('expected_revision'))
                saved = normalize(film, record, validate_assets=False)
                return 200, (render_reference(view_stage(saved, parts[5])), 'image/png')
    return None
