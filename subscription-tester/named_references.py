"""Local reference metadata. Nothing here is an xAI reference-library endpoint."""
import copy
import re
import time
import uuid
from video_rules import VOICES, image_input

CATEGORIES = ('Character', 'Location', 'Prop')

def normalize(data, existing, resolve_asset, config):
    if not isinstance(data, dict):
        raise ValueError('Enter reference details.')
    identity = data.get('id') or uuid.uuid4().hex
    if data.get('id') and not any(r['id'] == identity for r in existing):
        raise ValueError('This reference no longer exists.')
    title, handle, description = (data.get(k, '') for k in ('title','handle','description'))
    if not all(isinstance(v, str) for v in (title, handle, description)):
        raise ValueError('Title, mention name and description must be text.')
    title, handle, description = title.strip(), handle.strip().lstrip('@'), description.strip()
    if not title or len(title) > config['reference_title_limit']:
        raise ValueError(f"Enter a title up to {config['reference_title_limit']} characters.")
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,' + str(config['reference_handle_limit']-1) + '}', handle):
        raise ValueError('Mention names must start with a letter and use letters, numbers or underscores.')
    if any(r['id'] != identity and r['handle'].casefold() == handle.casefold() for r in existing):
        raise ValueError('This mention name is already used. Choose another.')
    if len(description) > config['reference_description_limit']:
        raise ValueError('Description exceeds the configured local limit.')
    if data.get('category') not in CATEGORIES:
        raise ValueError('Choose Character, Location or Prop.')
    voice = data.get('voice') or None
    if voice is not None and voice not in VOICES:
        raise ValueError('Choose a documented preset voice.')
    images = data.get('images', [])
    if not isinstance(images, list) or len(images) > 7:
        raise ValueError('Save at most 7 images in a reference.')
    if not images and not voice:
        raise ValueError('Add at least one image or preset voice.')
    cleaned = []
    for image in images:
        if isinstance(image, dict) and set(image) == {'asset_id'}:
            resolve_asset(image['asset_id'])
        else:
            image_input(image)
            if image['url'].startswith('data:'):
                raise ValueError('Upload the image first, then choose it from the library.')
        cleaned.append(copy.deepcopy(image))
    return {'id': identity, 'title': title, 'handle': handle, 'description': description,
            'category': data['category'], 'images': cleaned, 'voice': voice,
            'archived': False, 'updated_at': time.time()}
