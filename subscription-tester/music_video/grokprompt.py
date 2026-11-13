"""Grok Imagine Video prompts for music-video shots: a writer in the short first-frame form and a linter for the
failure modes that cost real money (Claudia's recipe and failure log, adapted to speech-led videos).

Grok takes the first frame only, so identity rests on that frame. Prompts are short prose (about 40-150 words),
say "as in the first frame", give a second-by-second action, one camera line, and say each thing once. A spoken
shot quotes its line exactly, joined by commas so the take does not insert pauses, with a smile in the eyes and lips
closed until the voice begins. A visual-only shot never asks anyone to sing or speak.
"""
import re

from music_video import lyrics as lyricmod, modes

GROK_MAX_TAKE_S = 15
GROK_BEST_TAKE_S = (5, 8)
WORDS = {'spoken': (60, 150), 'visual': (30, 150)}

MOOD = re.compile(r'\b(deadpan|dry|wry|smirk\w*|sly|knowing|menacing|sinister|cold|icy|stern|blank stare|stares?|staring|'
                  r'eyes on the lens|into the lens|unblinking|expressionless|emotionless)\b', re.I)
POSTURE = re.compile(r'\b(head (stays )?upright|stands? (perfectly )?still|motionless|keeps? still|does not move|doesn\'t move|'
                     r'frozen|rigid|perfectly still|holds? (the|her|his|their) pose|no movement)\b', re.I)
SMILE = re.compile(r'\b(smil\w*|grin\w*|laugh\w*)\b', re.I)
SMILE_OK = re.compile(r'smil\w* (in|with) (the|her|his|their) eyes', re.I)
TEXT = re.compile(r'\b(text|caption\w*|subtitle\w*|title card|lettering|letters|logo\w*|sign that (says|reads)|words? on)\b', re.I)
TEXT_NEG = re.compile(r'\bno (on-screen )?(text|captions?|subtitles?|lettering|letters|logos?)\b(, no \w+)*', re.I)
LOOK_PAST = re.compile(r'\b(looks? (behind|past|over (her|his|their) shoulder)|past the (camera|lens)|behind (her|him|them)self)\b', re.I)
PULL_BACK = re.compile(r'\b(pull(s|ing)?[- ]back|pulls? out|dolly out|zoom(s|ing)? out|widens?)\b', re.I)
BIG_MOVE = re.compile(r'\b(orbit\w*|whip pan|crane|360|spin\w*|fly(ing)? through|swoop\w*)\b', re.I)
MOTION = re.compile(r'\b(turns?|nods?|tilts?|lifts?|raises?|lowers?|reach\w*|leans?|rock\w*|breath\w*|pulses?|glows?|flickers?|'
                    r'moves?|walks?|steps?|sways?|blinks?|opens?|closes?|drifts?|push(es)?|tucks?|strok\w*|rests?|settles?|'
                    r'brightens?|dims?|rises?|falls?|shifts?|waves?|touch\w*|looks?|gestures?|smoothes?|pats?|hums?)\b', re.I)
NEGATIVE = re.compile(r'\b(no|never|without|avoid|don\'t|do not)\b', re.I)
FIRST_FRAME = re.compile(r'as in the first frame', re.I)


def words(text):
    return re.findall(r"[\w']+", text or '')


def sentences(text):
    return [s.strip().lower() for s in re.split(r'(?<=[.!?])\s+', text or '') if len(s.strip()) > 12]


def lint(prompt, kind, line_text=None, seconds=None):
    """Findings for one shot prompt: [{severity, kind, message}]. kind: 'spoken' or a visual kind."""
    out = []
    def add(sev, k, msg):
        out.append(dict(severity=sev, kind=k, message=msg))
    p = prompt or ''
    if not p.strip() or p.strip() == 'TODO':
        return out
    spoken = kind == 'spoken'
    n = len(words(p))
    low, high = WORDS['spoken' if spoken else 'visual']
    if n < low or n > high:
        add('warn', 'length', f'{n} words; Grok prompts work best at about {low}-{high} (short prose, each thing once).')
    unquoted = re.sub(r'[“"][^”"]*[”"]', '', p)
    if MOOD.search(unquoted):
        add('warn', 'mood_words', f'"{MOOD.search(unquoted).group(0)}": the model obeys every mood word; stacked dry or knowing words produce a cold stare. Choose warm, specific feelings.')
    if POSTURE.search(unquoted):
        add('warn', 'posture_rule', f'"{POSTURE.search(unquoted).group(0)}": posture rules freeze the performance. Put fixed traits in the first frame; give the take one plain movement.')
    if not MOTION.search(unquoted):
        add('warn', 'no_movement', 'Nothing visibly moves. Give one plain, visible action per moment.')
    if spoken:
        quoted = re.findall(r'[“"]([^”"]+)[”"]', p)
        if SMILE.search(unquoted) and not SMILE_OK.search(unquoted):
            add('warn', 'smile_while_speaking', 'A smiling mouth while speaking reads wrong. Put the smile in the eyes and keep lips closed until the voice begins.')
        if quoted and re.search(r'[.!?;:]\s+\S', quoted[0]):
            add('warn', 'full_stop_inside_line', 'A full stop inside the spoken line makes the take pause there. Join the phrases with commas.')
        if line_text and quoted and lyricmod.clean_words(quoted[0]) != lyricmod.clean_words(line_text):
            add('error', 'quote_mismatch', 'The quoted words must be exactly the lyric line.')
        if not quoted:
            add('error', 'no_quote', 'A spoken shot must quote its line in quotation marks.')
    else:
        if re.search(r'[“"][^”"]+[”"]', p) or modes.SINGING_WORDS.search(p):
            add('error', 'vocal_in_visual_prompt', 'A visual-only shot must not ask anyone to sing, speak or quote words.')
    if not FIRST_FRAME.search(p):
        add('warn', 'first_frame', 'Say "as in the first frame": Grok has no reference sheet, so identity rests on that frame.')
    stripped = TEXT_NEG.sub('', p)
    if TEXT.search(stripped):
        add('warn', 'on_screen_text', 'The prompt mentions text or lettering; Grok garbles it. Keep words off the picture.')
    if not TEXT_NEG.search(p):
        add('warn', 'no_text_line', 'End with "No on-screen text."')
    if LOOK_PAST.search(p):
        add('warn', 'look_past_lens', 'Looking behind or past the lens fails; point with a hand instead.')
    if PULL_BACK.search(p):
        add('warn', 'pull_back', 'Grok tends to push in when asked to pull back. Ask for the push-in and reverse the clip, or hold the camera.')
    if BIG_MOVE.search(p):
        add('warn', 'big_move', 'Big camera moves make Grok redraw the set and garble detail. Prefer one slow move.')
    seen, dup = set(), None
    for s in sentences(p):
        if s in seen:
            dup = s
        seen.add(s)
    if dup:
        add('warn', 'repeated_sentence', 'A sentence is repeated; say each thing once.')
    if len(NEGATIVE.findall(stripped)) > 3:
        add('warn', 'list_of_fixes', 'Many negatives read as a list of fixes; keep one short policy and describe what should happen.')
    if seconds is not None:
        if seconds > GROK_MAX_TAKE_S:
            add('error', 'over_take_limit', f'{seconds:.1f}s is longer than one Grok take ({GROK_MAX_TAKE_S}s).')
        elif seconds > GROK_BEST_TAKE_S[1] + 1:
            add('warn', 'long_take', f'{seconds:.1f}s: identity holds best in {GROK_BEST_TAKE_S[0]}-{GROK_BEST_TAKE_S[1]}s Grok takes.')
    return out


CAMERA = {'push_in': 'The camera pushes in slowly.', 'pull_back': 'The camera holds, then eases closer.',
          'orbit_left': 'The camera drifts slowly to the left.', 'orbit_right': 'The camera drifts slowly to the right.',
          'drift_high': 'High angle, the camera drifts gently.', 'low_push': 'Low angle, the camera pushes in slowly.'}


def commas(line):
    """Join a line's phrases with commas so the take does not pause between them."""
    keep = lambda w: w if re.match(r"^I('|\b)", w) else w[:1].lower() + w[1:]
    t = re.sub(r'\s*[.;:!?]+\s+(\S+)', lambda m: ', ' + keep(m.group(1)), line.strip())
    return t[0].upper() + t[1:] if t else t


def write(shot, moment=None, move=None, speaker='the speaker', action=None):
    """A draft Grok prompt for one board shot, in the short first-frame form."""
    seconds = max(1, round(shot['end'] - shot['start']))
    from music_video.keyframes import MOVE_TEXT
    for hint in MOVE_TEXT.values():                  # the camera is said once, in the camera line
        moment = re.sub(r'\s*' + re.escape(hint[0].upper() + hint[1:]) + r'\.', '', moment or '')
    scene = (moment or 'The scene').strip().rstrip('.')
    cam = CAMERA.get(move or '', 'The camera holds steady, with a slight drift.')
    if shot['kind'] == 'spoken':
        lead = min(1, max(.5, shot.get('lead_in_s', .3) + .4))
        line = commas(shot['text'])
        body = (f"As in the first frame: {scene}. 0-{lead:g}s: {speaker} is still for a breath, a smile in the eyes, lips closed. "
                f"{lead:g}-{seconds}s: {speaker} speaks, warm and clear: \"{line}\" "
                f"{action or 'A small, natural movement follows the words.'} {cam} Keep the look as in the first frame. "
                "Natural hands and anatomy. No music, no other voices. No on-screen text.")
    else:
        mid = max(1, seconds // 2)
        body = (f"As in the first frame: {scene}. 0-{mid}s: {action or 'one slow, natural movement begins'}. "
                f"{mid}-{seconds}s: the movement settles. {cam} Keep the look as in the first frame. "
                "Natural hands and anatomy. One continuous take. No on-screen text.")
    return re.sub(r'\s+', ' ', body).strip()
