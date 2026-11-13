"""Set plates painted in code: layered cut-paper SVG with cast shadows and paper grain, in a fixed palette.

FABLE's sets were painted in SVG and then rebuilt by an image model as a physical set; the code-painted plate becomes
the `set` reference every still is made from, so the world stays one place. A plate is either a list of layers
(painted here) or SVG the agent wrote. It is rasterised headlessly as an image (no scripts, no external loads).
"""

import re

from music_video import previz

KINDS = ('rect', 'ellipse', 'polygon', 'path')
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
PATH_D = re.compile(r'^[MmLlHhVvCcSsQqTtAaZz0-9eE.,\s+-]{1,20000}$')
FORBIDDEN = re.compile(r'<\s*(script|foreignObject|iframe|image|use)\b|\bon\w+\s*=|href\s*=\s*["\'](?!#)', re.I)
MAX_SVG = 1_000_000


class PlateError(ValueError):
    pass


def _num(v, name, low=-10000, high=10000):
    if type(v) not in (int, float) or not low <= v <= high:
        raise PlateError(f'{name} must be a number from {low} to {high}.')
    return v


def paint(width, height, background, layers, palette=None, grain=.5, shadow=.35):
    """SVG text for a cut-paper plate. layers: [{kind, fill, depth 0-6, ...shape}] painted back to front."""
    if not HEX.match(str(background)):
        raise PlateError('background is a #rrggbb colour.')
    if not isinstance(layers, list) or not 1 <= len(layers) <= 200:
        raise PlateError('Give 1-200 layers.')
    if palette is not None and (not isinstance(palette, list) or not all(HEX.match(str(c)) for c in palette)):
        raise PlateError('palette is a list of #rrggbb colours.')
    _num(grain, 'grain', 0, 1)
    _num(shadow, 'shadow', 0, 1)
    allowed = {c.lower() for c in palette} | {background.lower()} if palette else None
    shapes = []
    for n, layer in enumerate(layers):
        if not isinstance(layer, dict) or layer.get('kind') not in KINDS or not HEX.match(str(layer.get('fill', ''))):
            raise PlateError(f'Layer {n + 1}: needs kind ({", ".join(KINDS)}) and a #rrggbb fill.')
        if allowed and layer['fill'].lower() not in allowed:
            raise PlateError(f"Layer {n + 1}: {layer['fill']} is not in the plate's palette.")
        depth = _num(layer.get('depth', 1), f'layer {n + 1} depth', 0, 6)
        k, f = layer['kind'], layer['fill']
        if k == 'rect':
            geo = 'x="{}" y="{}" width="{}" height="{}" rx="{}"'.format(*(_num(layer.get(a, 0), f'layer {n + 1} {a}') for a in ('x', 'y', 'w', 'h', 'r')))
            tag = f'<rect {geo}'
        elif k == 'ellipse':
            geo = 'cx="{}" cy="{}" rx="{}" ry="{}"'.format(*(_num(layer.get(a, 0), f'layer {n + 1} {a}') for a in ('cx', 'cy', 'rx', 'ry')))
            tag = f'<ellipse {geo}'
        elif k == 'polygon':
            pts = layer.get('points')
            if not isinstance(pts, list) or not 3 <= len(pts) <= 400:
                raise PlateError(f'Layer {n + 1}: points is a list of 3-400 [x, y] pairs.')
            tag = '<polygon points="' + ' '.join(f'{_num(x, "x")},{_num(y, "y")}' for x, y in pts) + '"'
        else:
            d = str(layer.get('d', ''))
            if not PATH_D.match(d):
                raise PlateError(f'Layer {n + 1}: d is an SVG path of commands and numbers.')
            tag = f'<path d="{d}"'
        filt = f' filter="url(#s{int(depth)})"' if depth and shadow else ''
        shapes.append(f'{tag} fill="{f}"{filt}/>')
    shadows = ''.join(f'<filter id="s{d}" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="{d * 2}" dy="{d * 3}" '
                      f'stdDeviation="{d * 2.5}" flood-color="#000" flood-opacity="{shadow:.2f}"/></filter>' for d in range(1, 7))
    paper = (f'<filter id="paper"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="3" seed="7"/>'
             f'<feColorMatrix values="0 0 0 0 0.5  0 0 0 0 0.45  0 0 0 0 0.4  0 0 0 {grain * .35:.3f} 0"/></filter>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<defs>{shadows}{paper}</defs><rect width="100%" height="100%" fill="{background}"/>' + ''.join(shapes)
            + (f'<rect width="100%" height="100%" filter="url(#paper)"/>' if grain else '') + '</svg>')


def check_svg(text):
    if not isinstance(text, str) or not text.lstrip().startswith('<svg') or len(text) > MAX_SVG:
        raise PlateError(f'svg is SVG text starting with <svg, up to {MAX_SVG:,} characters.')
    if FORBIDDEN.search(text):
        raise PlateError('The SVG may not contain scripts, event handlers, embedded documents, images or external links.')
    return text


def render(svg_text, out, width, height):
    try:
        return previz.render_svg(svg_text, out, width, height)
    except previz.PrevizError as error:
        raise PlateError(str(error)) from None


