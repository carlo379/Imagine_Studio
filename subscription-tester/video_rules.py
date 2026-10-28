"""Rules verified against the official video docs, snapshot 2026-10-09."""
import base64
import math
import re
from urllib.parse import urlparse

MODELS = ('grok-imagine-video-1.5', 'grok-imagine-video-1.5-lite')
MODEL_CAPABILITIES = {
    MODELS[0]: dict(reference_images=14, voices=3, keyframes=4, last_frame=True, native_1080p=True),
    MODELS[1]: dict(reference_images=0, voices=0, keyframes=0, last_frame=False, native_1080p=False),
}

def prompt_size(prompt, reference=False):
    return len(prompt.encode('utf-8')) if reference else len(prompt)

def reference_scene(scene, include_saved_voices=True):
    return bool(scene.get('recording') or scene['refs'] or (scene['voices'] if include_saved_voices or scene['audio'] else []) or scene['last'] or scene['keys'])

RATIOS = ('1:1', '16:9', '9:16', '4:3', '3:4', '3:2', '2:3', '21:9', '5:2')
# Accepted IDs from the provider's rejection roster, observed 2026-10-28.
# No documented subscription roster endpoint is assumed; validation is local.
VOICES = ('carina', 'zagan', 'helix', 'orion', 'luna', 'iris', 'altair', 'zenith',
          'perseus', 'helios', 'lux', 'kepler', 'rigel', 'cosmo', 'celeste', 'ursa',
          'sirius', 'lumen', 'castor', 'naksh', 'atlas', 'ara', 'eve', 'leo', 'rex', 'sal')


def image_input(value):
    if not isinstance(value, dict) or set(value) != {'url'} or not isinstance(value['url'], str):
        raise ValueError('Choose an image from uploads or a public HTTPS URL.')
    url = value['url']
    if url.startswith('data:'):
        match = re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)', url)
        if not match:
            raise ValueError('Images must be JPEG, PNG, or WebP.')
        try:
            raw = base64.b64decode(match[2], validate=True)
        except ValueError:
            raise ValueError('Image data is invalid.') from None
        signatures = {'png': raw.startswith(b'\x89PNG\r\n\x1a\n'), 'jpeg': raw.startswith(b'\xff\xd8'),
                      'webp': raw.startswith(b'RIFF') and raw[8:12] == b'WEBP'}
        if not signatures[match[1]]:
            raise ValueError('The image content does not match its format.')
    else:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Image links must be public HTTPS URLs without embedded credentials.')
    return value


def is_reference(body):
    return any(body.get(key) for key in ('reference_images', 'reference_audios', 'last_frame', 'keyframes'))


def validate_video(body, config):
    if not isinstance(body, dict):
        raise ValueError('The video request is invalid.')
    if set(body) - {'model', 'prompt', 'duration', 'aspect_ratio', 'resolution', 'image', 'last_frame',
                    'reference_images', 'reference_audios', 'keyframes', 'generate_audio'}:
        raise ValueError('Unsupported request field.')
    if body.get('model') not in MODELS:
        raise ValueError('Choose one of the two documented video models.')
    lite = body['model'] == MODELS[1]
    duration = body.get('duration')
    if type(duration) is not int or not 1 <= duration <= 15:
        raise ValueError('Duration must be a whole number from 1 to 15 seconds.')
    if body.get('aspect_ratio') not in RATIOS:
        raise ValueError('Choose a documented aspect ratio.')
    allowed = ('480p', '720p') if is_reference(body) else ('480p', '720p', '1080p')
    if body.get('resolution') not in allowed:
        raise ValueError('Reference-to-video supports at most 720p.')
    refs, voices, keys = (body.get(key, []) for key in ('reference_images', 'reference_audios', 'keyframes'))
    if not all(isinstance(x, list) for x in (refs, voices, keys)):
        raise ValueError('Image, voice, and keyframe selections must be lists.')
    if len(refs) > 14 or len(voices) > 3 or len(keys) > 4:
        raise ValueError('Use at most 14 references, 3 voices, and 4 keyframes.')
    if lite and is_reference(body):
        raise ValueError('Video 1.5 Lite supports text or one starting image only. Remove references, voices, last frames and keyframes, or choose Video 1.5.')
    if 'generate_audio' in body:
        if type(body['generate_audio']) is not bool:
            raise ValueError('Audio must be on or off.')
    if voices and body.get('generate_audio') is False:
        raise ValueError('Enable audio to use preset voices.')
    prompt = body.get('prompt', '')
    if not isinstance(prompt, str):
        raise ValueError('Prompt must be text.')
    reference = is_reference(body)
    limit = config.get('prompt_limit_bytes', 4096) if reference else config['prompt_limit_chars']
    size = prompt_size(prompt, reference)
    if size > limit:
        unit = 'UTF-8 bytes' if reference else 'characters'
        raise ValueError(f'Expanded prompt has {size} {unit}; the limit is {limit}. Shorten the prompt or saved reference descriptions.')
    pinned = bool(body.get('image') or body.get('last_frame') or keys)
    # Capability docs allow prompt omission with visual inputs; REST schema is older.
    if not prompt.strip() and not (pinned or refs):
        raise ValueError('Add a prompt. Voice-only and text-to-video requests need one.')
    for item in refs:
        image_input(item)
    for field in ('image', 'last_frame'):
        if field in body:
            image_input(body[field])
    slots = set()
    for key in keys:
        if not isinstance(key, dict) or set(key) != {'image', 'timestamp_s'}:
            raise ValueError('Each keyframe needs an image and a time.')
        image_input(key['image'])
        timestamp = key['timestamp_s']
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or not 0 < timestamp < duration:
            raise ValueError('Keyframes must be strictly between the opening and closing times.')
        slot = math.floor(timestamp * 3 + .5)
        if not 0 < slot < duration * 3:
            raise ValueError('Rounded keyframes must remain strictly inside the clip.')
        key['timestamp_s'] = slot / 3
        if slot in slots:
            raise ValueError('Two keyframes cannot share a ⅓-second slot.')
        slots.add(slot)
    for voice in voices:
        if isinstance(voice,dict) and set(voice)=={'url'}:
            url=voice['url']
            if not isinstance(url,str):raise ValueError('Audio reference needs a URL.')
            if url.startswith('data:'):
                match=re.fullmatch(r'data:audio/(wav|mpeg);base64,([A-Za-z0-9+/=]+)',url)
                if not match:raise ValueError('Use a valid WAV or MP3 recording.')
                try:raw=base64.b64decode(match[2],validate=True)
                except ValueError:raise ValueError('Recording data is invalid.') from None
                if not 0<len(raw)<=64*1024*1024:raise ValueError('Recording exceeds the upload limit.')
                if match[1]=='wav' and not (raw.startswith(b'RIFF') and raw[8:12]==b'WAVE'):raise ValueError('Recording content does not match WAV format.')
            else:
                parsed=urlparse(url)
                if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError('Audio links must use HTTPS without embedded credentials.')
            continue
        if isinstance(voice, dict) and isinstance(voice.get('voice_id'), str):
            voice['voice_id'] = voice['voice_id'].lower()
        if not isinstance(voice, dict) or set(voice) != {'voice_id'} or voice['voice_id'] not in VOICES:
            raise ValueError('Choose a voice from the documented preset roster.')
    if re.search(r'<(?:IMAGE|AUDIO)_REMOVED_\d+>', prompt):
        raise ValueError('A tagged input was removed. Replace its REMOVED tag with an existing tag.')
    image_count = len(refs) + bool(body.get('image'))
    for kind, index in re.findall(r'<(IMAGE|AUDIO)_(\d+)>', prompt):
        if int(index) >= (image_count if kind == 'IMAGE' else len(voices)):
            raise ValueError(f'<{kind}_{index}> does not exist. Add it or remove the tag.')
    return body
