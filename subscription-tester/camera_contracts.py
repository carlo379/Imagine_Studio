"""Typed local Camera Control contracts; no provider generation or browser consent."""
def contracts(paths, operation):
    def ref(name): return {'$ref': '#/components/schemas/' + name}
    def obj(properties, required=None):
        return dict(type='object', additionalProperties=False, properties=properties,
            required=list(properties) if required is None else list(required))
    def number(lo, hi): return dict(type='number', minimum=lo, maximum=hi)
    revision = dict(type='integer', minimum=0, description='Saved shot staging revision; separate from image and video draft revisions.')
    camera = obj({k:number(*bounds) for k,bounds in dict(yaw=(-180,180), elevation=(-10,85), distance=(1,15),
        target_x=(-5,5), target_y=(.1,3), target_z=(-5,5), lens=(18,120)).items()})
    subject = obj(dict(name=dict(type='string',minLength=1,maxLength=80), asset_id=dict(type=['string','null'],description='Active character reference ID, or null; never an image URL.'),
        x=number(-5,5),z=number(-5,5),rotation=number(-180,180),
        pose=dict(enum=['stand','walk','sit','crouch','reach','fight']),arms=number(-90,150),head=number(-60,60)))
    staging = obj(dict(camera=ref('StagingCamera'), subjects=dict(type='array',minItems=1,maxItems=4,items=ref('StagingSubject')),
        ratio=dict(enum=['16:9','9:16','1:1']),environment=dict(type='string',maxLength=800),style=dict(type='string',maxLength=500)))
    direction = obj(dict(id=dict(type='string'),shot_id=dict(type='string'),revision=revision,
        staging=dict(anyOf=[ref('ShotStaging'),dict(type='null')]),composition_asset_id=dict(type='string'),updated_at=dict(type='number')),('id','shot_id','revision','staging'))
    preset = obj(dict(id=dict(type='string'),name=dict(type='string'),patch=obj(camera['properties'],()),camera=ref('StagingCamera')))
    movement = obj({key:dict(type='string') for key in ('id','name','group','effect','prompt')})
    dimensions = obj(dict(width=dict(type='integer',minimum=1),height=dict(type='integer',minimum=1)))
    catalog = obj(dict(version=dict(type='integer',const=1),defaults=ref('ShotStaging'),
        frame_sizes=obj({ratio:dimensions for ratio in ('16:9','9:16','1:1')}),
        camera=dict(type='array',items=ref('CameraPreset')),movements=dict(type='array',items=ref('MovementPreset')),
        renderer=obj(dict(engine=dict(const='Node Skia Canvas 2D'),local_only=dict(const=True),available=dict(type='boolean'),
            saved_only=dict(const=True),guides=dict(const=False),timeout_seconds=dict(type='integer',minimum=1),
            reference_route=dict(const='filmmaking/shots/{id}/reference.png')))))
    paths['/filmmaking/presets']={'get':operation('List the shared camera/movement presets, export dimensions and local renderer availability')}
    paths['/filmmaking/presets']['get']['responses']['200']=dict(description='Shared UI preset catalog',content={'application/json':dict(schema=ref('CameraPresetCatalog'))})
    paths['/filmmaking/shots/{id}/reference.png']={'post':operation('Render saved staging to a local PNG; no generation, uploads or saved-state changes',obj(dict(expected_revision=revision)))}
    png=paths['/filmmaking/shots/{id}/reference.png']['post']
    png['responses']={
        '200':dict(description='PNG for this saved staging revision; guides and subject labels disabled',content={'image/png':dict(schema=dict(type='string',format='binary'))}),
        '400':dict(description='Invalid body or no saved staging; no inline staging, workspace selectors, URLs or paths accepted'),
        '401':dict(description='Missing or invalid local workspace token'),
        '403':dict(description='Local access or matching browser origin required'),
        '404':dict(description='Shot absent from the authenticated workspace'),
        '409':dict(description='Saved staging revision changed or production archived; reread before retrying'),
        '503':dict(description='Local Node/Skia dependency unavailable, busy, failed or timed out; no saved work changed')}
    direction_route=paths['/filmmaking/shots/{id}']
    direction_route['put']['requestBody']['content']['application/json']['schema']=obj(dict(expected_revision=revision,staging=ref('ShotStaging')))
    for op in direction_route.values():
        op['responses']['200']=dict(description='Saved shot staging and its revision',content={'application/json':dict(schema=ref('ShotDirection'))})
    return dict(StagingCamera=camera,StagingSubject=subject,ShotStaging=staging,ShotDirection=direction,
        CameraPreset=preset,MovementPreset=movement,CameraPresetCatalog=catalog)
