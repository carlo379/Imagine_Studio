"""On-screen lyrics: every spoken word drawn at a measured time, as an ASS subtitle file with karaoke timing."""
from music_video import lyrics


def stamp(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f'{int(h)}:{int(m):02d}:{s:05.2f}'


def word_times(text, first, last):
    """Spread the line's words over the measured speech window by syllable weight (a documented approximation)."""
    words = lyrics.WORD.findall(text)
    weights = [max(1, lyrics.syllables(w)) for w in words]
    span = max(.05, last - first)
    out, t = [], first
    for w, k in zip(words, weights):
        d = span * k / sum(weights)
        out.append(dict(word=w, start=round(t, 3), end=round(t + d, 3)))
        t += d
    return out


def build_ass(entries, width=1080, height=1920, font='Arial', size=84):
    """entries: [{text, start, end}] in song time (seconds). Karaoke wipe across each line's words."""
    head = ('[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 2\n\n'
            '[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,'
            'Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n'
            'Style: Lyric,%s,%d,&H00FFFFFF,&H0000D7FF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,4,1,2,80,80,%d,1\n\n'
            '[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n') % (
        width, height, font, size, int(height * .12))
    rows = []
    for e in entries:
        words = word_times(e['text'], e['start'], e['end'])
        body = ''.join('{\\k%d}%s ' % (max(1, round((w['end'] - w['start']) * 100)), w['word']) for w in words).strip()
        rows.append('Dialogue: 0,%s,%s,Lyric,,0,0,0,,%s' % (stamp(e['start']), stamp(e['end'] + .25), body))
    return head + '\n'.join(rows) + '\n'


def lyric_gate(entries, sheet_text):
    """Every sung/spoken word must appear on screen exactly once. Returns (ok, expected, drawn)."""
    expected = len(lyrics.clean_words(sheet_text))
    drawn = sum(len(lyrics.WORD.findall(e['text'])) for e in entries)
    return dict(ok=expected == drawn, expected_words=expected, drawn_words=drawn)


def render_frames(entries, outdir, width=1080, height=1920, size=84, band=.26):
    """Transparent PNG per word state (line shown, spoken words lit) for builds of FFmpeg without text filters.

    Returns [{png, start, end, y}] to overlay at y. Uses Pillow only."""
    from pathlib import Path
    from PIL import Image, ImageDraw, ImageFont
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    font = _font(size)
    h = int(height * band)
    y = int(height * (1 - band) - height * .06)
    overlays = []
    for li, e in enumerate(entries):
        words = word_times(e['text'], e['start'], e['end'])
        shown = [w['word'] for w in words]
        for wi, w in enumerate(words):
            end = words[wi + 1]['start'] if wi + 1 < len(words) else e['end'] + .25
            img = Image.new('RGBA', (width, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            rows = _wrap(draw, shown, font, int(width * .86))
            total_h = len(rows) * int(size * 1.25)
            top = max(0, (h - total_h) // 2)
            k = 0
            for r, row in enumerate(rows):
                row_w = sum(draw.textlength(x + ' ', font=font) for x in row)
                x = (width - row_w) / 2
                for word in row:
                    lit = k <= wi
                    fill = (255, 215, 0, 255) if lit else (255, 255, 255, 235)
                    draw.text((x, top + r * int(size * 1.25)), word, font=font, fill=fill, stroke_width=4, stroke_fill=(0, 0, 0, 255))
                    x += draw.textlength(word + ' ', font=font)
                    k += 1
            path = outdir / f'l{li:03d}_{wi:02d}.png'
            img.save(path)
            overlays.append(dict(png=str(path), start=w['start'], end=end, y=y))
    return overlays


def _font(size):
    from PIL import ImageFont
    for name in ('/System/Library/Fonts/Helvetica.ttc', '/Library/Fonts/Arial.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 'DejaVuSans-Bold.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(draw, words, font, max_w):
    rows, row = [], []
    for w in words:
        trial = row + [w]
        if row and sum(draw.textlength(x + ' ', font=font) for x in trial) > max_w:
            rows.append(row)
            row = [w]
        else:
            row = trial
    return rows + ([row] if row else [])
