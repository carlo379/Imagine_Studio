"""Fixed-object continuity check between a shot's first and last frames.

People and other moving things are expected to change between a start frame and an end
frame. Fixed things (furniture, props, the set, the camera) must not. This check finds
each part of the first frame in the last frame and reports how far it moved and how
well it still matches:

- held:    found within the tolerance and still matching. Good.
- moved:   still matching, but displaced beyond the tolerance. A fixed object that moved,
           or the camera moved. Bad when it is meant to be fixed.
- changed: no longer matches anywhere near. Expected for people and moving things; bad
           for something that should be fixed (it morphed or was replaced).
- resized: a named region still matches, but at a different size (an edit shrank or grew a
           fixed object, e.g. a laptop 9% smaller). Bad for something that should be fixed.
- flat:    too little texture to measure (plain sky, dark walls). Not judged.

Named regions are also measured for size: the scale (in percent) at which the region's
content best matches the last frame. Draw a region's box around the whole object, edges
included; a flat area inside an object cannot show its size.

Named regions mark what must stay fixed and decide the verdict. Without regions, a grid
of tiles shows where things held, moved or changed for a human to judge.

Pure Pillow, no provider call. The result images are saved as image assets marked
continuity_check; Studio refuses them as video inputs.
"""
import copy
import io
import json
import threading
import time
import uuid
from pathlib import Path

from agent_api import APIError

KIND = 'continuity_check'
VIDEO_REFUSAL = 'Continuity check images are review aids; never send them to the video model.'
WORK_WIDTH = 704          # analysis width; boxes and shifts are reported in first-frame pixels
GRID = (16, 9)
SEARCH = 0.03             # search radius as a fraction of the width
MATCH_MIN = 0.6
FLAT_STD = 6.0
MAX_REGIONS = 24
REGION_WIDTH = 1408       # finer analysis width for named regions' size test
SCALE_RANGE = 0.15        # sizes searched: 85% to 115%
COLORS = {'held': (60, 200, 90), 'moved': (235, 50, 40), 'changed': (245, 170, 30), 'resized': (200, 60, 220), 'flat': (120, 120, 120)}


def _gray(image, width):
    from PIL import Image
    height = round(image.height * width / image.width)
    return image.convert('L').resize((width, height), Image.BILINEAR)


def _match(a, b, box, radius):
    """Best offset of box (in a) inside b within radius. Returns (dx, dy, similarity, std)."""
    from PIL import ImageChops, ImageStat
    x0, y0, x1, y1 = box
    tile = a.crop(box)
    std = ImageStat.Stat(tile).stddev[0]
    if std < FLAT_STD:
        return 0, 0, None, std

    def cost(dx, dy):
        if x0 + dx < 0 or y0 + dy < 0 or x1 + dx > b.width or y1 + dy > b.height:
            return None
        return ImageStat.Stat(ImageChops.difference(tile, b.crop((x0 + dx, y0 + dy, x1 + dx, y1 + dy)))).mean[0]

    best = (cost(0, 0), 0, 0)
    if best[0] is None:
        best = (float('inf'), 0, 0)
    step = 2 if radius > 4 else 1
    for dy in range(-radius, radius + 1, step):
        for dx in range(-radius, radius + 1, step):
            value = cost(dx, dy)
            if value is not None and value < best[0]:
                best = (value, dx, dy)
    cx, cy = best[1], best[2]
    for dy in range(cy - step, cy + step + 1):
        for dx in range(cx - step, cx + step + 1):
            value = cost(dx, dy)
            if value is not None and value < best[0]:
                best = (value, dx, dy)
    similarity = max(0.0, min(1.0, 1 - best[0] / (2.0 * std)))
    return best[1], best[2], similarity, std


def _scale(a, b, box, dx, dy):
    """The size of box's content in b relative to a (1.0 = same size), searched around shift dx, dy.
    Returns (scale, similarity at that scale)."""
    from PIL import Image, ImageChops, ImageStat
    x0, y0, x1, y1 = box
    tile = a.crop(box)
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2 + dx, (y0 + y1) / 2 + dy
    std = max(ImageStat.Stat(tile).stddev[0], 1e-6)

    def cost(s, ox, oy):
        half_w, half_h = w * s / 2, h * s / 2
        left, top = cx + ox - half_w, cy + oy - half_h
        if left < 0 or top < 0 or left + 2 * half_w > b.width or top + 2 * half_h > b.height:
            return None
        crop = b.transform((w, h), Image.EXTENT, (left, top, left + 2 * half_w, top + 2 * half_h), Image.BICUBIC)
        return ImageStat.Stat(ImageChops.difference(tile, crop)).mean[0]

    def search(scales, offsets):
        best = None
        for s in scales:
            for oy in offsets:
                for ox in offsets:
                    value = cost(s, ox, oy)
                    if value is not None and (best is None or value < best[0]):
                        best = (value, s, ox, oy)
        return best

    coarse = search([1 + i / 100 for i in range(-round(SCALE_RANGE * 100), round(SCALE_RANGE * 100) + 1)], (-2, 0, 2))
    if coarse is None:
        return None, None
    _, s0, ox0, oy0 = coarse
    fine = search([s0 + i / 1000 for i in range(-10, 11)], (-1, 0, 1)) or coarse
    value, scale = fine[0], fine[1]
    return scale, max(0.0, min(1.0, 1 - value / (2.0 * std)))


def _status(shift, similarity, tolerance):
    if similarity is None:
        return 'flat'
    if similarity < MATCH_MIN:
        return 'changed'
    return 'held' if shift <= tolerance else 'moved'


def analyze(first, last, regions=(), tolerance_fraction=0.005, scale_tolerance=0.005):
    """Compare two PIL images. Returns tiles, regions, a verdict and its reasons."""
    from PIL import Image
    last = last.resize(first.size, Image.BILINEAR) if last.size != first.size else last
    a, b = _gray(first, WORK_WIDTH), _gray(last, WORK_WIDTH)
    fine_width = min(first.width, REGION_WIDTH)
    fa, fb = (_gray(first, fine_width), _gray(last, fine_width)) if regions else (None, None)
    scale = first.width / a.width
    radius = max(2, round(SEARCH * a.width))
    tolerance = max(1.0, tolerance_fraction * a.width)

    def measure(box):
        dx, dy, similarity, std = _match(a, b, box, radius)
        shift = (dx * dx + dy * dy) ** 0.5
        return dict(status=_status(shift, similarity, tolerance), dx_px=round(dx * scale), dy_px=round(dy * scale),
                    shift_px=round(shift * scale, 1), match=None if similarity is None else round(similarity, 2))

    cols, rows = GRID
    tiles = []
    for r in range(rows):
        for c in range(cols):
            box = (round(c * a.width / cols), round(r * a.height / rows), round((c + 1) * a.width / cols), round((r + 1) * a.height / rows))
            tiles.append(dict(col=c, row=r, box=[round(v * scale) for v in box], **measure(box)))
    region_results = []
    for region in regions:
        fx0, fy0, fx1, fy1 = region['box']
        box = (round(fx0 * a.width), round(fy0 * a.height), round(fx1 * a.width), round(fy1 * a.height))
        result = dict(name=region['name'], box=region['box'], **measure(box))
        result['scale_percent'] = None
        if result['status'] in ('held', 'moved'):
            k = fa.width / first.width
            fine_box = (round(fx0 * fa.width), round(fy0 * fa.height), round(fx1 * fa.width), round(fy1 * fa.height))
            size, similarity = _scale(fa, fb, fine_box, result['dx_px'] * k, result['dy_px'] * k)
            if size is not None:
                result['scale_percent'] = round(size * 100, 1)
                if round(abs(size - 1), 4) > scale_tolerance and similarity is not None and similarity >= MATCH_MIN:
                    result['status'] = 'resized'
        region_results.append(result)
    counts = {k: sum(1 for t in tiles if t['status'] == k) for k in COLORS}
    if region_results:
        failed = [r for r in region_results if r['status'] not in ('held', 'flat')]
        verdict = 'fail' if failed else 'pass'
        reasons = [f"{r['name']}: {r['status']} ({r['shift_px']} px, " + (f"size {r['scale_percent']}%, " if r.get('scale_percent') is not None else '')
                   + f"match {r['match']})" for r in failed] or ['Every fixed region held its place and size.']
    else:
        verdict = 'fail' if counts['moved'] else ('review' if counts['changed'] else 'pass')
        reasons = [f"{counts['moved']} tiles moved (displaced but still matching)" if counts['moved'] else 'No tile was displaced.',
                   f"{counts['changed']} tiles changed: check they are only people or moving things." if counts['changed'] else 'No tile changed.']
    return dict(verdict=verdict, reasons=reasons, tolerance_px=round(tolerance * scale, 1), search_px=round(radius * scale),
                scale_tolerance_percent=round(scale_tolerance * 100, 2),
                counts=counts, regions=region_results, tiles=tiles)


def render_images(first, last, result):
    """Annotated map, 50% overlay and difference heat map, as PNG bytes."""
    from PIL import Image, ImageChops, ImageDraw, ImageOps
    last = last.resize(first.size) if last.size != first.size else last
    base = Image.blend(first.convert('RGB'), last.convert('RGB'), 0.5)
    overlay = base.copy()
    marked = Image.new('RGBA', base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(marked)
    for tile in result['tiles']:
        if tile['status'] == 'held':
            continue
        draw.rectangle(tile['box'], fill=(*COLORS[tile['status']], 70 if tile['status'] != 'flat' else 25))
    width = max(3, first.width // 400)
    for region in result['regions']:
        fx0, fy0, fx1, fy1 = region['box']
        box = [fx0 * first.width, fy0 * first.height, fx1 * first.width, fy1 * first.height]
        color = COLORS['held'] if region['status'] in ('held', 'flat') else COLORS[region['status']]
        draw.rectangle(box, outline=(*color, 255), width=width)
        size = f" {region['scale_percent']}%" if region.get('scale_percent') is not None else ''
        draw.text((box[0] + width * 2, box[1] + width * 2), f"{region['name']}: {region['status']} {region['shift_px']}px{size}",
                  fill=(*color, 255), font_size=max(14, first.width // 90))
    annotated = Image.alpha_composite(base.convert('RGBA'), marked).convert('RGB')
    diff = ImageOps.autocontrast(ImageChops.difference(first.convert('RGB'), last.convert('RGB')).convert('L'))
    heat = ImageOps.colorize(diff, black=(0, 0, 0), white=(255, 60, 40))
    out = {}
    for name, image in (('map', annotated), ('overlay', overlay), ('difference', heat)):
        data = io.BytesIO()
        image.save(data, 'PNG')
        out[name] = data.getvalue()
    return out


def _regions(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_REGIONS:
        raise APIError('invalid_regions', f'regions must be a list of at most {MAX_REGIONS} named boxes.')
    cleaned = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {'name', 'box'} or not isinstance(item.get('name'), str) or not item['name'].strip():
            raise APIError('invalid_regions', 'Each region is {"name": ..., "box": [x0, y0, x1, y1]} with fractions of the frame from 0 to 1.')
        box = item.get('box')
        if (not isinstance(box, list) or len(box) != 4 or not all(type(v) in (int, float) and 0 <= v <= 1 for v in box)
                or box[2] - box[0] < 0.01 or box[3] - box[1] < 0.01):
            raise APIError('invalid_regions', f"Region “{item['name']}” needs a box of fractions [x0, y0, x1, y1] with x1 > x0 and y1 > y0.")
        cleaned.append(dict(name=item['name'].strip()[:80], box=[float(v) for v in box]))
    return cleaned


def lock_regions(first, last, regions, feather_px=12):
    """Copy each fixed region's pixels from the first frame into the last frame, with a soft edge.
    A region is a box [x0, y0, x1, y1] or a polygon [[x, y], ...], in fractions of the frame."""
    from PIL import Image, ImageDraw, ImageFilter
    last = last.resize(first.size, Image.LANCZOS) if last.size != first.size else last
    mask = Image.new('L', first.size, 0)
    draw = ImageDraw.Draw(mask)
    w, h = first.size
    for region in regions:
        if region.get('polygon'):
            draw.polygon([(x * w, y * h) for x, y in region['polygon']], fill=255)
        else:
            x0, y0, x1, y1 = region['box']
            draw.rectangle([x0 * w, y0 * h, x1 * w, y1 * h], fill=255)
    if feather_px:
        mask = mask.filter(ImageFilter.GaussianBlur(feather_px / 2))
    return Image.composite(first.convert('RGB'), last.convert('RGB'), mask)


def _lock_regions(value):
    if not isinstance(value, list) or not value or len(value) > MAX_REGIONS:
        raise APIError('invalid_regions', f'regions must list 1 to {MAX_REGIONS} fixed objects.')
    cleaned = []
    for item in value:
        if isinstance(item, dict) and 'polygon' in item:
            polygon = item.get('polygon')
            if (set(item) - {'name', 'polygon'} or not isinstance(polygon, list) or not 3 <= len(polygon) <= 64
                    or not all(isinstance(p, list) and len(p) == 2 and all(type(v) in (int, float) and 0 <= v <= 1 for v in p) for p in polygon)):
                raise APIError('invalid_regions', 'A polygon region is {"name", "polygon": [[x, y], ...]} with 3 to 64 points as fractions of the frame.')
            cleaned.append(dict(name=str(item.get('name') or 'region')[:80], polygon=[[float(x), float(y)] for x, y in polygon]))
        else:
            cleaned.extend(_regions([item]))
    return cleaned


class FrameContinuity:
    def __init__(self, app, save_json):
        self.app = app
        self.save_json = save_json
        self.path = Path(app.storage) / 'continuity-checks.json'
        self.lock = threading.Lock()
        try:
            self.checks = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.checks = []

    def get(self, identity):
        with self.lock:
            check = next((c for c in self.checks if c['id'] == identity), None)
        if not check:
            raise APIError('not_found', 'Continuity check not found.', 404)
        return copy.deepcopy(check)

    def latest_for(self, first_id, last_id):
        with self.lock:
            matches = [c for c in self.checks if c['first'] == first_id and c['last'] == last_id]
        return copy.deepcopy(matches[-1]) if matches else None

    def _image(self, source, label):
        from PIL import Image
        if not isinstance(source, dict) or set(source) != {'asset_id'}:
            raise APIError('invalid_frame', f'{label} must be {{"asset_id": ...}}.')
        try:
            asset, path = self.app.asset(source['asset_id'])
        except ValueError:
            raise APIError('not_found', f'{label} asset not found.', 404) from None
        if asset.get('kind') in (KIND, 'prop_model_render'):
            raise APIError('invalid_frame', f'{label} must be a frame, not a review image or 3D render.')
        return asset['id'], Image.open(path).convert('RGB')

    def create(self, data):
        if not isinstance(data, dict) or set(data) - {'first', 'last', 'regions', 'tolerance_percent', 'scale_tolerance_percent', 'title'}:
            raise APIError('invalid_check', 'Send first and last ({"asset_id": ...}), optional regions, tolerance_percent, scale_tolerance_percent and title.')
        first_id, first = self._image(data.get('first'), 'first')
        last_id, last = self._image(data.get('last'), 'last')
        if abs(first.width / first.height - last.width / last.height) > 0.02:
            raise APIError('invalid_frame', 'The two frames must have the same aspect ratio.')
        regions = _regions(data.get('regions'))
        tolerance = data.get('tolerance_percent', 0.5)
        if type(tolerance) not in (int, float) or not 0.05 <= tolerance <= 10:
            raise APIError('invalid_check', 'tolerance_percent must be a number from 0.05 to 10 (percent of the frame width).')
        scale_tolerance = data.get('scale_tolerance_percent', 0.5)
        if type(scale_tolerance) not in (int, float) or not 0.1 <= scale_tolerance <= 10:
            raise APIError('invalid_check', 'scale_tolerance_percent must be a number from 0.1 to 10 (percent of the object\'s size).')
        title = data.get('title') or 'Continuity check'
        if not isinstance(title, str) or len(title) > 120:
            raise APIError('invalid_check', 'title must be text up to 120 characters.')
        result = analyze(first, last, regions, tolerance / 100, scale_tolerance / 100)
        images = {}
        for name, png in render_images(first, last, result).items():
            images[name] = self._save_image(png, f'{title} · {name}')
        # result['regions'] carries each region's name and box with its measurement.
        check = dict(id=uuid.uuid4().hex, title=title.strip(), first=first_id, last=last_id,
                     tolerance_percent=float(tolerance), created_at=time.time(), images=images, accepted=None, **result)
        with self.lock:
            self.checks.append(check)
            self.save_json(self.path, self.checks)
        return copy.deepcopy(check)

    def lock_fixed(self, data):
        """Make a new last frame whose fixed objects are the first frame's own pixels."""
        import base64
        if not isinstance(data, dict) or set(data) - {'first', 'last', 'regions', 'feather_px', 'name'}:
            raise APIError('invalid_lock', 'Send first and last ({"asset_id": ...}), regions, optional feather_px and name.')
        first_id, first = self._image(data.get('first'), 'first')
        last_id, last = self._image(data.get('last'), 'last')
        if abs(first.width / first.height - last.width / last.height) > 0.02:
            raise APIError('invalid_frame', 'The two frames must have the same aspect ratio.')
        regions = _lock_regions(data.get('regions'))
        feather = data.get('feather_px', 12)
        if type(feather) is not int or not 0 <= feather <= 200:
            raise APIError('invalid_lock', 'feather_px must be a whole number from 0 to 200.')
        name = data.get('name') or 'Last frame with locked fixed objects'
        if not isinstance(name, str) or len(name) > 120:
            raise APIError('invalid_lock', 'name must be text up to 120 characters.')
        out = io.BytesIO()
        lock_regions(first, last, regions, feather).save(out, 'PNG')
        asset = self.app.upload({'name': name.strip() + '.png', 'data_url': 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()})
        return dict(asset=asset, first=first_id, last=last_id, regions=regions, feather_px=feather,
                    next_steps=['Run a Grok edit of this image with "Reproduce the input image exactly. Change nothing." to blend the copied areas.',
                                'Check it again with POST image-studio/continuity using the same named boxes, then show it to the human for approval.'])

    def accept(self, identity, data):
        words = (data or {}).get('human_words')
        if not isinstance(words, str) or not words.strip() or len(words) > 2000:
            raise APIError('human_words_required', "Relay the human's own words, verbatim, accepting this check (1–2,000 characters).")
        with self.lock:
            check = next((c for c in self.checks if c['id'] == identity), None)
            if not check:
                raise APIError('not_found', 'Continuity check not found.', 404)
            check['accepted'] = dict(human_words=words.strip(), at=time.time())
            self.save_json(self.path, self.checks)
            return copy.deepcopy(check)

    def _save_image(self, png, name):
        identity = uuid.uuid4().hex
        path = Path(self.app.storage) / 'assets' / f'{identity}.png'
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(png)
        path.chmod(0o600)
        asset = dict(id=identity, name=name[:120], ext='png', mime='image/png', bytes=len(png),
                     src=f'/api/assets/{identity}', kind=KIND, video_policy=VIDEO_REFUSAL)
        with self.app.lock:
            self.app.assets.append(asset)
            self.save_json(self.app.assets_path, self.app.assets)
        return identity

    def dispatch(self, method, parts, data, key):
        if not parts:
            if method == 'GET':
                with self.lock:
                    return 200, [{k: c[k] for k in ('id', 'title', 'first', 'last', 'verdict', 'created_at', 'accepted')} for c in reversed(self.checks)]
            if method == 'POST':
                return 201, self.create(data)
        if parts == ['lock'] and method == 'POST':
            return 201, self.lock_fixed(data)
        if len(parts) == 1 and method == 'GET':
            return 200, self.get(parts[0])
        if len(parts) == 2 and parts[1] == 'accept' and method == 'POST':
            return 200, self.accept(parts[0], data)
        raise APIError('not_found', 'Continuity check route not found.', 404)
