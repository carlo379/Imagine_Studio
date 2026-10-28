"""Conservative preflight checks for prepared video direction.

Visual/story conflicts come from the writer's actual multimodal review. Runtime
checks cover deterministic settings, timing and authoring cues. They do not infer
actions, door mechanisms or character appearances from prose.
"""
import copy
import re
from collections import Counter
from video_rules import VOICES

ISSUE_SCHEMA = dict(type='array', items=dict(type='object', additionalProperties=False,
    required=['code', 'severity', 'message'], properties=dict(
        code=dict(type='string', enum=['visual_conflict', 'continuity_conflict', 'timing_conflict']),
        severity=dict(type='string', enum=['warning', 'error']), message=dict(type='string'))))

POLICY = """Return issues=[] when the final direction is coherent. Use issues only for constraints that remain unresolved: visual_conflict for a requested action incompatible with visible frame/reference facts, continuity_conflict for incompatible approved story/identity requirements, timing_conflict when required action or exact dialogue cannot fit the supported duration. Each issue needs a short actionable message and severity=error when generation should wait, warning for uncertainty that does not prevent a coherent continuation. Resolve differences between old AI direction, old script staging, actual attached frame and current human instructions into ONE coherent direction; a resolved adjustment belongs in notes, never issues. Current human corrections govern action/camera; approved reference pixels govern identity and the actual first frame governs starting state. Explain an irreconcilable request rather than silently rewriting story or guessing hidden details. Do not change crops, frame inputs or shot structure without approval. After two failed takes, suggest a shot change in notes instead of rewording the same beat. Do not fill notes or issues with routine success messages. Character references establish exact appearance: omit their full descriptions and biographies from generation direction. The app adds the exact name-to-image preservation sentence once. Use performance, actions, eyelines and interactions in direction. For each image_backed asset return an empty summary; only voice-only assets may need a compact continuity cue. Required dialogue with audio off must be identified as silent performance, not claimed as audible speech.
"""


RUNTIME_WARNING_CODES = ('voice_tag_repeated', 'voice_name_in_body', 'character_without_direction', 'dialogue_timing')

# Partial names must be distinctive enough that ordinary staging prose does not
# count as a character mention. Exact full names/handles still work as before.
COMMON_NAME_WORDS = frozenset('''a an the and or but of to in on at by for from with
without as is are was were be been being this that these those it its he she they
them his her their who what where when how does do did has have had will would
can could may might must should not no stays stands holds watches waits moves
place behind beside near above below over under into onto toward towards through
box character robot bot man woman boy girl mr mrs ms dr sir'''.split())


def first_name(title):
    # Split CamelCase titles too, for snapshots named EveFoster.
    spaced = re.sub(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', ' ', title)
    words = re.findall(r'[^\W\d_]+', spaced)
    word = words[0] if words else ''
    return word if len(word) >= 3 and word.casefold() not in COMMON_NAME_WORDS else ''


def validated_issues(value):
    if not isinstance(value, list):
        raise ValueError('Return up to 12 concise unresolved video conflicts.')
    output = []
    for issue in value:
        if (not isinstance(issue, dict) or set(issue) != {'code', 'severity', 'message'}
                or issue['code'] not in ('visual_conflict', 'continuity_conflict', 'timing_conflict', *RUNTIME_WARNING_CODES)
                or issue['severity'] not in ('warning', 'error')
                or not isinstance(issue['message'], str) or not 1 <= len(issue['message'].strip()) <= 1000):
            raise ValueError('Each video conflict needs a code, severity and concise explanation.')
        if issue['code'] in RUNTIME_WARNING_CODES:
            if issue['severity'] != 'warning':
                raise ValueError('Runtime authoring checks must remain warnings.')
            # Completed proposals are validated again on apply. Recompute these
            # warnings from current text instead of retaining stale findings.
            continue
        output.append({**issue, 'message': issue['message'].strip()})
    if len(output) > 12:
        raise ValueError('Return up to 12 concise unresolved video conflicts.')
    return output


def authoring_warnings(scene):
    """Check authored bodies and compiled requests without interpreting the story."""
    prompt = scene.get('prompt', '')
    header, body = '', prompt
    if prompt.startswith('Reference identities:\n'):
        header, separator, body = prompt.partition('\n\n')
        if not separator:
            body = ''
    issues = []
    tags = Counter(re.findall(r'<AUDIO_\d+>', prompt))
    body_tags = set(re.findall(r'<AUDIO_\d+>', body))
    for tag in sorted(tags):
        if tags[tag] > 1 or tag in body_tags:
            issues.append(dict(code='voice_tag_repeated', severity='warning',
                message=f'{tag} belongs once in the Reference identities header. Use the speaker name in the direction.'))

    characters = {}
    attached_characters = set()
    names = []
    active_images = {r['id'] for r in scene.get('refs', [])}
    for binding in scene.get('named', []):
        aliases = [binding.get('title', ''), binding.get('handle', '')]
        names.extend(aliases)
        if binding.get('category') == 'Character':attached_characters.add(aliases[0])
        if binding.get('category') == 'Character' and active_images.intersection(binding.get('refIds', [])):
            characters.setdefault(aliases[0], set()).update(a for a in aliases if a)
    for line in header.splitlines()[1:]:
        character = re.match(r"Preserve (.+)'s exact appearance as shown in .*<IMAGE_\d+>", line)
        legacy = re.match(r'Character: (.+?) \(.*<IMAGE_\d+>', line)
        asset = re.match(r'(?:Character|Location|Prop): (.+?) \(', line)
        speaker = re.match(r'Voice for (.+?): <AUDIO_\d+>', line)
        for match in (character, legacy, asset, speaker):
            if match:
                names.append(match[1])
        if character or legacy:
            name = (character or legacy)[1]
            attached_characters.add(name)
            characters.setdefault(name, set()).add(name)
        if speaker:attached_characters.add(speaker[1])

    def mentioned(name):
        return re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', body, re.I)

    # Check only attached presets, and exempt asset names/handles containing them.
    attached = {v.get('voice', v.get('voice_id', '')).casefold()
                for v in scene.get('voices', scene.get('reference_audios', []))}
    for voice in VOICES:
        if voice in attached and not any(voice in name.casefold() for name in names) and mentioned(voice):
            issues.append(dict(code='voice_name_in_body', severity='warning',
                message=f'Use the speaker name instead of the preset voice name “{voice}” in the direction. The header binds the voice.'))
    firsts = Counter(first_name(name).casefold() for name in attached_characters if first_name(name))
    for name, aliases in characters.items():
        first = first_name(name)
        shared = first and firsts[first.casefold()] > 1
        candidates = {alias for alias in aliases if not shared or alias.casefold() != first.casefold()}
        if first and not shared:
            candidates.add(first)
        if not any(mentioned(alias) for alias in candidates):
            issues.append(dict(code='character_without_direction', severity='warning',
                message=f'{name} appears in the shot but the direction never says what they do. Add an action or a hold.'))
    return issues


def dialogue_words(text):
    """Count explicitly cued spoken lines, excluding quoted visual labels.

    Use the prompt or script total, never add duplicate script and prompt copies.
    This is a pacing estimate, not a claim about the generated performance.
    """
    cue = r'(?:\b(?:says|replies|asks|whispers|shouts|speaks|sings|dialogue)\b[^"“\n]{0,100}|(?:^|(?<=\s))@?[A-Z][\w .-]{0,59}:)\s*["“]([^"”\n]+)["”]'
    spoken = re.findall(cue, text, re.M | re.I)
    return sum(len(re.findall(r"\b\w+(?:['’]\w+)*\b", line)) for line in spoken)


def checks(scene, prepared_issues=(), script=''):
    issues = copy.deepcopy(list(prepared_issues))
    prompt = scene.get('prompt', '')
    # Match explicit action-beat headers only, not lenses, dialogue or dimensions.
    beats = re.findall(r'(?m)^\s*(\d+(?:\.\d+)?)\s*(?:s\s*)?[-–—]\s*(\d+(?:\.\d+)?)\s*(?:s|seconds)\s*:', prompt)
    duration = scene.get('duration', 0)
    if any(float(start) >= float(end) or float(end) > duration for start, end in beats):
        issues.append(dict(code='timing_conflict', severity='error',
            message='The prompt has action beats outside the selected duration. Adjust duration or use Prepare again to retime the direction.'))
    # Quotes in actual dialogue cues are a signal, not every quoted prop label.
    dialogue = re.search(r'(?m)^.*(?:says|replies|asks|delighted|disbelief|amused|directly to|dialogue).*[:]\s*["“]', prompt, re.I)
    dialogue = dialogue or re.search(r'(?m)^\s*(?:\d+\s*[-–]\s*\d+\s*s:\s*)?@?[A-Z][\w ]{0,39}(?:\s*\([^\n)]*\))?:\s*["“][^"”]+["”]', prompt)
    dialogue = dialogue or re.search(r'(?m)^\s*[^\n:]{1,80}:\s*["“][^"”]+["”]', script)
    if not scene.get('audio', True) and dialogue:
        issues.append(dict(code='audio_disabled', severity='warning',
            message='Audio is off, so the scripted dialogue will be silent. Enable Audio and use Prepare again if you want spoken lines.'))
    words=max(dialogue_words(prompt),dialogue_words(script))
    minimum=words/2.5+1
    if words and duration and minimum>duration:
        issues.append(dict(code='dialogue_timing',severity='warning',
            message=f'{words} spoken words need about {minimum:g}s at 2.5 words/second plus 0.5s at each end; this clip is {duration:g}s. Extend the duration or review a shorter line or split shot with the user.'))
    issues.extend(authoring_warnings(scene))
    return list({(i['code'], i['message']): i for i in issues}.values())


def blocked(issues):
    return any(issue['severity'] == 'error' for issue in issues)


def apply_summaries(scene, summaries):
    """Keep legacy result compatibility while excluding prose for image identities."""
    if not isinstance(summaries, list):
        raise ValueError('Return the attached video asset summaries.')
    state = copy.deepcopy(scene)
    expected = {n['handle']: n for n in state['named']}
    seen = set()
    active = {r['id'] for r in state['refs']}
    for item in summaries:
        if (not isinstance(item, dict) or set(item) != {'handle', 'summary'}
                or item['handle'] not in expected or item['handle'] in seen
                or not isinstance(item['summary'], str)):
            raise ValueError('Video summaries must match the attached assets exactly once.')
        named = expected[item['handle']]
        seen.add(item['handle'])
        if active.intersection(named['refIds']):
            # Older completed proposals have nonempty cues. They remain readable
            # but those cues must never override actual approved image pixels.
            named.pop('video_summary', None)
            continue
        summary = item['summary'].strip()
        if (not 1 <= len(summary) <= 220 or '\n' in summary or '\r' in summary
                or re.search(r'@[A-Za-z]|<(?:IMAGE|AUDIO)_', summary)):
            raise ValueError('Use one concise plain sentence for each voice-only identity cue.')
        named['video_summary'] = summary
    if seen != set(expected):
        raise ValueError('The AI must account for every attached named asset.')
    return state
