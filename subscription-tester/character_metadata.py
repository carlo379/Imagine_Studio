"""Complete character context for the writer, never generation-prompt prose.

Visual references remain authoritative. Historical source-card fallbacks are
identified explicitly and do not change a saved profile or an approved image.
"""
import copy

APPEARANCE_FIELDS = ('description', 'age', 'gender', 'height', 'build', 'hair',
                     'eyes', 'skin', 'ethnicity', 'clothing', 'palette')
BIOGRAPHY_FIELDS = ('role', 'personality', 'motivation', 'relationships', 'voice')
OMITTED = 'Additional complete fields are retained in the structured profile.'


def character_context(entity):
    """Separate visuals from narrative; recover blank visuals from their source.

    Never match by character name: this helper accepts the already-linked entity.
    A nonempty current value always wins, including a deliberately refined outfit.
    Fallback text is context for the writer to compare with pixels, not a second
    visual specification for the video engine.
    """
    profile = entity.get('profile') or {}
    original = entity.get('source_card_snapshot') or {}
    appearance, provenance = {}, {}
    for field in APPEARANCE_FIELDS:
        value = profile.get(field)
        source = 'current_profile'
        if not value and original.get(field):
            value, source = original[field], 'original_source_card'
        if value:
            appearance[field] = copy.deepcopy(value)
            provenance[field] = source
    biography = {field: copy.deepcopy(profile[field]) for field in BIOGRAPHY_FIELDS
                 if profile.get(field)}
    return dict(appearance=appearance, biography=biography,
                appearance_provenance=provenance,
                appearance_authority='Attached approved reference pixels; metadata is supporting context.')


def video_assets(app, scene, shot=None):
    """Enrich the attached identities by exact canonical-reference association."""
    shot = shot or {}
    entities = app.productions.all('world-entity')
    output = []
    for named in scene.get('named', []):
        item = dict(handle=named['handle'], name=named['title'], category=named['category'])
        bound_ids = set(named.get('refIds') or [])
        item['image_tags'] = ['<IMAGE_' + str(index + bool(scene.get('first'))) + '>'
                              for index, reference in enumerate(scene.get('refs') or [])
                              if reference.get('id') in bound_ids]
        item['image_backed'] = bool(item['image_tags'])
        item['voice_tag'] = next(('<AUDIO_' + str(index) + '>'
                                  for index, voice in enumerate(scene.get('voices') or [])
                                  if named.get('voiceId') and voice.get('id') == named['voiceId']), None) if scene.get('audio') else None
        matches = [entity for entity in entities
                   if entity.get('reference_id') == named.get('id')
                   and entity.get('category') == named['category']
                   and (not shot.get('production_id')
                        or entity.get('production_id') == shot['production_id'])
                   and (not entity.get('episode_id')
                        or entity.get('episode_id') == shot.get('episode_id'))]
        # Episode refinements take precedence over the series entity only when
        # they belong to this shot's episode and share the exact reference ID.
        matches.sort(key=lambda entity: (bool(entity.get('episode_id')), entity.get('revision', 0)), reverse=True)
        if matches:
            entity = matches[0]
            item['entity_id'] = entity['id']
            if named['category'] == 'Character':
                item.update(character_context(entity))
            else:
                item['profile'] = copy.deepcopy(entity.get('profile') or {})
                item['description'] = entity.get('description', '')
        else:
            # Legacy library descriptions may mix biography and appearance.
            # Retain them whole, explicitly as unstructured supporting context.
            item['supporting_metadata'] = named.get('description', '')
            item['metadata_kind'] = 'unstructured_library_description'
        output.append(item)
    return output


def profile_description(profile, limit=10000):
    """A display/library summary made of complete fields, with explicit omissions.

    Full authoring context always comes from the original structured fields.
    No field is ever cut halfway through a word or sentence to fit a summary.
    """
    fields = [field for field in APPEARANCE_FIELDS if field != 'palette']
    fields += [field for field in profile if field not in fields and field not in ('id', 'name')]
    lines = [field.replace('_', ' ').title() + ': ' + profile[field]
             for field in fields if isinstance(profile.get(field), str) and profile[field].strip()]
    complete = '\n'.join(lines)
    if len(complete) <= limit:
        return complete
    retained, omitted = [], False
    for line in lines:
        # Reserve the omission marker even when a long earlier field is skipped.
        if len('\n'.join(retained + [line, OMITTED])) <= limit:
            retained.append(line)
        else:
            omitted = True
    if omitted and len(OMITTED) <= limit:
        retained.append(OMITTED)
    return '\n'.join(retained)


def library_description(entity, limit=1500):
    """Prefer complete visual fields when publishing a bounded library summary."""
    if entity.get('category') == 'Character':
        context = character_context(entity)
        fields = {**context['appearance'], **context['biography']}
        if fields:
            return profile_description(fields, limit)
    profile = entity.get('profile') or {}
    if profile:
        return profile_description(profile, limit)
    description = entity.get('description', '')
    return description if len(description) <= limit else OMITTED
