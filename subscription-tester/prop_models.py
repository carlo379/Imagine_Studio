"""Real 3D prop models (STL or OBJ) and posed reference renders for image models.

A render puts the model in front of a pinhole camera at an exact frame position,
distance, rotation and lens, so a prop can be redrawn at its true size and angle.
Two local engines: VTK (fast, flat studio light) and Blender (soft light, better
shading). Both run as separate processes with no network.

Renders are image-model references only. Studio refuses them as video inputs.
"""
import base64
import copy
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from agent_api import APIError

ROOT = Path(__file__).resolve().parent
VTK_WORKER = ROOT / 'scripts/prop_render_vtk.py'
BLENDER_WORKER = ROOT / 'scripts/prop_render_blender.py'
RENDER_KIND = 'prop_model_render'
VIDEO_REFUSAL = '3D prop renders are image-model references only; never send them to the video model.'
UNITS = {'mm': 0.001, 'cm': 0.01, 'm': 1.0, 'in': 0.0254}
FORMATS = ('stl', 'obj')
MAX_MODEL_BYTES = 64 * 1024 * 1024
MAX_SIDE = 4096
ENGINES = ('vtk', 'blender')
TIMEOUTS = {'vtk': 60, 'blender': 300}
BACKDROPS = {'gray': (205, 207, 211, 255), 'dark': (38, 40, 46, 255)}
_render_lock = threading.Lock()


def _num(data, key, default, low, high):
    value = data.get(key, default)
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise APIError('invalid_pose', f'{key} must be a number from {low} to {high}.')
    return float(value)


def mesh_points(raw, kind):
    """Validate a mesh and return its vertices. Raises ValueError on anything else."""
    if kind == 'stl':
        if len(raw) >= 84:
            count = struct.unpack_from('<I', raw, 80)[0]
            if count and 84 + 50 * count == len(raw):
                points = []
                for i in range(count):
                    values = struct.unpack_from('<12f', raw, 84 + 50 * i)
                    points.extend((values[3:6], values[6:9], values[9:12]))
                return points
        text = raw[:MAX_MODEL_BYTES].decode('ascii', 'strict') if raw.lstrip().startswith(b'solid') else ''
        points = [tuple(float(v) for v in line.split()[1:4]) for line in text.splitlines() if line.strip().startswith('vertex ')]
        if not points or len(points) % 3:
            raise ValueError('Use a binary or ASCII STL mesh.')
        return points
    if kind == 'obj':
        text = raw.decode('utf-8', 'strict')
        points = [tuple(float(v) for v in line.split()[1:4]) for line in text.splitlines() if line.startswith('v ')]
        if not points or not any(line.startswith('f ') for line in text.splitlines()):
            raise ValueError('Use an OBJ mesh with vertices and faces.')
        return points
    raise ValueError('Use an STL or OBJ mesh.')


def bounds(points):
    xs, ys, zs = zip(*points)
    values = [min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('The mesh has invalid coordinates.')
    return values


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _rot(axis, degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    if axis == 'x':
        return [[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]]
    if axis == 'y':
        return [[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]]
    return [[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def camera(data):
    """Pinhole camera at the origin looking down -Z with +Y up (Blender's convention)."""
    width = data.get('width', 1920)
    height = data.get('height', 1080)
    if type(width) is not int or type(height) is not int or not 64 <= width <= MAX_SIDE or not 64 <= height <= MAX_SIDE:
        raise APIError('invalid_pose', f'width and height must be whole pixels from 64 to {MAX_SIDE}.')
    if data.get('lens_mm') is not None:
        lens = _num(data, 'lens_mm', 35, 8, 400)
        hfov = 2 * math.degrees(math.atan(18 / lens))  # 36 mm full-frame width
    else:
        hfov = _num(data, 'hfov_deg', 60, 5, 150)
    vfov = 2 * math.degrees(math.atan(math.tan(math.radians(hfov) / 2) * height / width))
    return dict(width=width, height=height, hfov_deg=hfov, vfov_deg=vfov,
                focal_px=width / 2 / math.tan(math.radians(hfov) / 2))


def placement(model, data):
    """The 4x4 model-to-camera matrix, in meters, and the normalized pose that made it."""
    cam = camera(data)
    unit = UNITS[model['units']]
    up = data.get('up_axis', model.get('up_axis', 'z'))
    if up not in ('z', 'y'):
        raise APIError('invalid_pose', 'up_axis must be z or y.')
    pose = dict(frame_x=_num(data, 'frame_x', 0.5, -1, 2), frame_y=_num(data, 'frame_y', 0.5, -1, 2),
                distance_m=_num(data, 'distance_m', 2, 0.05, 5000),
                yaw_deg=_num(data, 'yaw_deg', 0, -360, 360), pitch_deg=_num(data, 'pitch_deg', 0, -360, 360),
                roll_deg=_num(data, 'roll_deg', 0, -360, 360), scale=_num(data, 'scale', 1, 0.01, 100), up_axis=up)
    b = model['bounds']
    center = [(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2]
    s = unit * pose['scale']
    centered = [[s, 0, 0, -center[0] * s], [0, s, 0, -center[1] * s], [0, 0, s, -center[2] * s], [0, 0, 0, 1]]
    # Z-up models stand upright with their -Y side toward the camera; Y-up models face +Z.
    upright = [[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]] if up == 'z' else [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    # Yaw turns about the vertical, positive pitch tips the top away from the camera, roll spins in view.
    turn = _mul(_rot('z', pose['roll_deg']), _mul(_rot('x', -pose['pitch_deg']), _rot('y', pose['yaw_deg'])))
    tx = math.tan(math.radians(cam['hfov_deg']) / 2) * (2 * pose['frame_x'] - 1)
    ty = math.tan(math.radians(cam['vfov_deg']) / 2) * (1 - 2 * pose['frame_y'])
    norm = math.sqrt(tx * tx + ty * ty + 1)
    position = [pose['distance_m'] * tx / norm, pose['distance_m'] * ty / norm, -pose['distance_m'] / norm]
    move = [[1, 0, 0, position[0]], [0, 1, 0, position[1]], [0, 0, 1, position[2]], [0, 0, 0, 1]]
    matrix = _mul(move, _mul(turn, _mul(upright, centered)))
    size = [round((b[1] - b[0]) * s, 4), round((b[3] - b[2]) * s, 4), round((b[5] - b[4]) * s, 4)]
    return matrix, cam, pose, size


def project(matrix, cam, point):
    """Pixel position of a model-space point (used by tests and size reports)."""
    x, y, z = (sum(matrix[i][j] * v for j, v in enumerate((*point, 1))) for i in range(3))
    return cam['width'] / 2 + cam['focal_px'] * x / -z, cam['height'] / 2 - cam['focal_px'] * y / -z


def blender_path():
    candidate = os.environ.get('IMAGINE_BLENDER') or shutil.which('blender')
    if not candidate and platform.system() == 'Darwin':
        candidate = '/Applications/Blender.app/Contents/MacOS/Blender'
    if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
        return Path(candidate).resolve()
    return None


def engines():
    return {'vtk': dict(available=importlib.util.find_spec('vtk') is not None, light='flat studio light',
                        setup='pip install vtk into the Studio environment'),
            'blender': dict(available=blender_path() is not None, light='soft area light and shading',
                            setup='Install Blender, or set IMAGINE_BLENDER to its executable')}


def _sandboxed(args, directory, engine):
    if platform.system() != 'Darwin' or not shutil.which('sandbox-exec'):
        return args
    quoted = lambda p: json.dumps(str(p))
    policy = directory / 'isolation.sb'
    policy.write_text('(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)\n'
                      '(allow file-write* (subpath ' + quoted(directory) + ') (subpath ' + quoted(Path(directory).resolve()) + ') (literal "/dev/null"))\n')
    policy.chmod(0o600)
    return [shutil.which('sandbox-exec'), '-f', str(policy), *args]


def run_engine(engine, job, directory):
    """Render in a separate process. Returns RGBA PNG bytes."""
    job_path = directory / 'job.json'
    job_path.write_text(json.dumps(job))
    if engine == 'vtk':
        if importlib.util.find_spec('vtk') is None:
            raise APIError('prop_renderer_unavailable', 'VTK is not installed. ' + engines()['vtk']['setup'] + '.', 503)
        args = [sys.executable, '-I', str(VTK_WORKER), str(job_path)]
    else:
        blender = blender_path()
        if not blender:
            raise APIError('prop_renderer_unavailable', 'Blender is not installed. ' + engines()['blender']['setup'] + '.', 503)
        args = [str(blender), '--background', '--factory-startup', '--python-exit-code', '1',
                '--python', str(BLENDER_WORKER), '--', str(job_path)]
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL') if k in os.environ}
    env.update(HOME=str(directory), TMPDIR=str(directory), BLENDER_USER_RESOURCES=str(directory / 'blender'),
               BLENDER_USER_CONFIG=str(directory / 'blender/config'), BLENDER_USER_SCRIPTS=str(directory / 'blender/scripts'),
               BLENDER_USER_DATAFILES=str(directory / 'blender/data'))
    try:
        done = subprocess.run(_sandboxed(args, directory, engine), cwd=directory, env=env, capture_output=True,
                              timeout=TIMEOUTS[engine], stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise APIError('prop_render_failed', f'The {engine} render took longer than {TIMEOUTS[engine]} s.', 504) from None
    out = Path(job['output'])
    if done.returncode != 0 or not out.is_file():
        tail = (done.stderr or done.stdout or b'').decode('utf-8', 'replace').strip().splitlines()[-3:]
        raise APIError('prop_render_failed', f'The {engine} render failed: ' + (' '.join(tail)[:400] or 'no output.'), 500)
    return out.read_bytes()


class PropModels:
    def __init__(self, app, save_json):
        self.app = app
        self.save_json = save_json
        self.folder = Path(app.storage) / 'prop-models'
        self.path = Path(app.storage) / 'prop-models.json'
        self.lock = threading.Lock()
        try:
            self.models = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.models = []

    def _get(self, identity):
        with self.lock:
            model = next((m for m in self.models if m['id'] == identity), None)
        if not model:
            raise APIError('not_found', 'Prop model not found.', 404)
        return copy.deepcopy(model)

    def schema(self):
        return dict(formats=list(FORMATS), units=list(UNITS), max_model_bytes=MAX_MODEL_BYTES, max_side=MAX_SIDE,
                    engines=engines(), kind=RENDER_KIND, video_policy=VIDEO_REFUSAL,
                    pose=dict(camera='Pinhole camera at the origin looking down -Z, +Y up. Set lens_mm (full-frame equivalent) or hfov_deg.',
                              frame_x='0 left to 1 right: where the model center lands', frame_y='0 top to 1 bottom',
                              distance_m='camera to model center', yaw_deg='turn about the vertical',
                              pitch_deg='positive tips the top away from the camera', roll_deg='spin in the view plane',
                              up_axis='z (default): model +Z is up and its -Y side faces the camera; y: +Y up, +Z faces the camera',
                              scale='1 keeps true size'),
                    background=['transparent', 'gray', 'dark', {'asset_id': 'image to place the render over, same aspect'}])

    def create(self, data):
        name = data.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise APIError('validation_failed', 'Name the model (up to 120 characters).')
        kind = data.get('format')
        if kind not in FORMATS:
            raise APIError('validation_failed', 'format must be stl or obj.')
        units = data.get('units', 'mm')
        if units not in UNITS:
            raise APIError('validation_failed', 'units must be mm, cm, m or in.')
        up = data.get('up_axis', 'z')
        if up not in ('z', 'y'):
            raise APIError('validation_failed', 'up_axis must be z or y.')
        reference = data.get('reference_id')
        if reference is not None and not any(r['id'] == reference for r in self.app.named_library()):
            raise APIError('not_found', 'Named reference not found.', 404)
        try:
            raw = base64.b64decode(data.get('data_base64') or '', validate=True)
        except (ValueError, TypeError):
            raise APIError('validation_failed', 'data_base64 must be the model file in base64.') from None
        if not 0 < len(raw) <= MAX_MODEL_BYTES:
            raise APIError('body_limit', 'Models must be at most 64 MB.', 413)
        try:
            box = bounds(mesh_points(raw, kind))
        except (ValueError, UnicodeDecodeError, struct.error):
            raise APIError('validation_failed', f'This is not a readable {kind.upper()} mesh.') from None
        identity = uuid.uuid4().hex
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self.folder / f'{identity}.{kind}'
        target.write_bytes(raw)
        target.chmod(0o600)
        unit = UNITS[units]
        model = dict(id=identity, name=name.strip(), format=kind, units=units, up_axis=up, bytes=len(raw),
                     bounds=box, size_m=[round((box[1] - box[0]) * unit, 4), round((box[3] - box[2]) * unit, 4), round((box[5] - box[4]) * unit, 4)],
                     reference_id=reference, created_at=time.time())
        with self.lock:
            self.models.append(model)
            self.save_json(self.path, self.models)
        return copy.deepcopy(model)

    def render(self, identity, data):
        model = self._get(identity)
        engine = data.get('engine', 'vtk')
        if engine not in ENGINES:
            raise APIError('invalid_pose', 'engine must be vtk or blender.')
        matrix, cam, pose, size = placement(model, data)
        background = data.get('background', 'transparent')
        base = None
        if isinstance(background, dict) and set(background) == {'asset_id'}:
            asset, base_path = self.app.asset(background['asset_id'])
            base = base_path
        elif not isinstance(background, str) or (background != 'transparent' and background not in BACKDROPS):
            raise APIError('invalid_pose', 'background must be transparent, gray, dark or {"asset_id": ...}.')
        color = data.get('color', [0.94, 0.94, 0.95])
        if not isinstance(color, list) or len(color) != 3 or not all(type(c) in (int, float) and 0 <= c <= 1 for c in color):
            raise APIError('invalid_pose', 'color must be three numbers from 0 to 1.')
        light = data.get('light') or {}
        if not isinstance(light, dict) or set(light) - {'key_color', 'ambient_color', 'key_strength', 'ambient_strength', 'key_direction', 'exposure'}:
            raise APIError('invalid_pose', 'light takes key_color, ambient_color, key_strength, ambient_strength, key_direction and exposure.')
        for field in ('key_color', 'ambient_color', 'key_direction'):
            value = light.get(field)
            low, high = (-10, 10) if field == 'key_direction' else (0, 1)
            if value is not None and (not isinstance(value, list) or len(value) != 3 or not all(type(c) in (int, float) and low <= c <= high for c in value)):
                raise APIError('invalid_pose', f'light.{field} must be three numbers from {low} to {high}.')
        for field in ('key_strength', 'ambient_strength'):
            if field in light:
                _num(light, field, 1, 0, 50)
        if 'exposure' in light:
            _num(light, 'exposure', 0, -10, 10)
        shadow = data.get('ground_shadow', False)
        if type(shadow) is not bool or (shadow and engine != 'blender'):
            raise APIError('invalid_pose', 'ground_shadow is true or false, and needs engine blender.')
        name = data.get('name') or f"{model['name']} · {engine} render"
        if not isinstance(name, str) or len(name) > 120:
            raise APIError('invalid_pose', 'name must be text up to 120 characters.')
        with _render_lock, tempfile.TemporaryDirectory(prefix='prop-render-') as folder:
            directory = Path(folder).resolve()
            mesh = directory / f"model.{model['format']}"
            shutil.copyfile(self.folder / f"{model['id']}.{model['format']}", mesh)
            job = dict(mesh=str(mesh), format=model['format'], output=str(directory / 'render.png'),
                       width=cam['width'], height=cam['height'], vfov_deg=cam['vfov_deg'], hfov_deg=cam['hfov_deg'],
                       matrix=matrix, color=color, light=light, ground_shadow=shadow,
                       up_vector=[0, 0, 1] if pose['up_axis'] == 'z' else [0, 1, 0])
            png = run_engine(engine, job, directory)
        png = self._finish(png, cam, background, base)
        corners = [project(matrix, cam, (x, y, z)) for x in model['bounds'][0:2] for y in model['bounds'][2:4] for z in model['bounds'][4:6]]
        xs, ys = [c[0] for c in corners], [c[1] for c in corners]
        provenance = dict(kind=RENDER_KIND, model_id=model['id'], model_name=model['name'], engine=engine,
                          camera={k: round(v, 3) if isinstance(v, float) else v for k, v in cam.items()}, pose=pose,
                          size_m=size, bounding_box_px=[round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))],
                          background=background, light=light, ground_shadow=shadow, video_policy=VIDEO_REFUSAL)
        return self._save(png, name, provenance)

    def _finish(self, png, cam, background, base):
        from PIL import Image
        image = Image.open(io.BytesIO(png)).convert('RGBA')
        if image.size != (cam['width'], cam['height']):
            image = image.resize((cam['width'], cam['height']))
        if isinstance(background, str) and background in BACKDROPS:
            canvas = Image.new('RGBA', image.size, BACKDROPS[background])
            canvas.alpha_composite(image)
            image = canvas
        elif base is not None:
            canvas = Image.open(base).convert('RGBA')
            if abs(canvas.width / canvas.height - cam['width'] / cam['height']) > 0.01:
                raise APIError('invalid_pose', 'The background image must have the same aspect ratio as the render.')
            canvas = canvas.resize(image.size)
            canvas.alpha_composite(image)
            image = canvas
        out = io.BytesIO()
        image.save(out, 'PNG')
        return out.getvalue()

    def _save(self, png, name, provenance):
        identity = uuid.uuid4().hex
        path = Path(self.app.storage) / 'assets' / f'{identity}.png'
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(png)
        path.chmod(0o600)
        asset = dict(id=identity, name=name[:120], ext='png', mime='image/png', bytes=len(png),
                     src=f'/api/assets/{identity}', **provenance)
        with self.app.lock:
            self.app.assets.append(asset)
            self.save_json(self.app.assets_path, self.app.assets)
        return copy.deepcopy(asset)

    def dispatch(self, method, parts, data, key):
        if parts == ['schema'] and method == 'GET':
            return 200, self.schema()
        if not parts:
            if method == 'GET':
                with self.lock:
                    return 200, copy.deepcopy(self.models)
            if method == 'POST':
                return 201, self.create(data)
        if len(parts) == 1 and method == 'GET':
            return 200, self._get(parts[0])
        if len(parts) == 2 and parts[1] == 'render' and method == 'POST':
            return 201, self.render(parts[0], data)
        raise APIError('not_found', 'Prop model route not found.', 404)
