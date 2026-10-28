"""Editable reference suggestions from the saved generation prompt; entirely local."""
import re
import unicodedata

PLACES = r'laboratory|lab|studio|workshop|office|kitchen|bedroom|library|warehouse|hangar|forest|desert|city|spaceship|street|garden|castle|cabin|beach|classroom|hospital'

def suggest(job, output, existing, config, category=None):
    prompt = job['draft']['settings'].get('prompt', '').strip()
    # Use the generation snapshot, never whichever draft happens to be open now.
    clean = re.sub(r'<(?:IMAGE|AUDIO)_[^>]+>', '', prompt)
    clean = re.sub(r'\s+', ' ', clean).strip()
    place = re.search(r'\b('+PLACES+r')\b', clean, re.I)
    category = category or 'Location'
    title = job['draft'].get('title', 'Generated reference')
    generic = bool(re.fullmatch(r'(?:first|new|untitled|generated|test|lab)?\s*image(?:\s+\d+|\s+refinement)?', title, re.I))
    if place and (category == 'Location'):
        # Keep up to three immediately preceding descriptive words, avoiding commands.
        prefix = clean[:place.start()].split()[-3:]
        stops = {'a','an','the','of','in','inside','at','for','with','create','generate','render','show','image','picture','featuring','into','to','this'}
        start = max((i+1 for i,w in enumerate(prefix) if w.lower().strip(',.') in stops), default=0)
        words = prefix[start:] + [place.group()]
        title = ' '.join(words).strip(' ,.:;').title()
    elif generic:
        title = f'Generated {category}'
    title = title[:config['reference_title_limit']].strip() or 'Generated reference'
    handle = re.sub(r'[^A-Za-z0-9 ]', '', unicodedata.normalize('NFKD', title)).strip().replace(' ', '_')
    handle = re.sub(r'^[^A-Za-z]+', '', handle) or 'Reference'
    limit = config['reference_handle_limit']; handle = handle[:limit]
    used = {r['handle'].lower() for r in existing}
    base = handle; n = 2
    while handle.lower() in used:
        suffix = '_'+str(n); handle = base[:limit-len(suffix)]+suffix; n += 1
    description = re.sub(r'^(?:please\s+)?(?:create|generate|render|draw|show)\s+(?:an?\s+)?(?:image|picture|photo|illustration)(?:\s+of)?\s*', '', clean, flags=re.I)
    description = description[:config['reference_description_limit']].strip()
    return {'title': title, 'handle': handle, 'description': description, 'category': category,
            'voice': None, 'images': [{'asset_id': output['id']}],
            'suggestion_note': 'Suggested from the saved generation prompt, not image analysis. Edit to describe only the reusable subject. No AI call or usage.'}
