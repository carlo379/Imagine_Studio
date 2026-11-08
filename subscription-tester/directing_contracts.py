"""Agent discovery contracts for the shared directing tools."""


def contracts(paths, operation):
    def obj(properties, required=()):
        return dict(type='object', properties=properties, required=list(required), additionalProperties=False)

    def string(limit=120):
        return dict(type='string', maxLength=limit)

    def number(minimum, maximum):
        return dict(type='number', minimum=minimum, maximum=maximum)

    def array(items, limit):
        return dict(type='array', items=items, maxItems=limit)

    def ref(name):
        return {'$ref': '#/components/schemas/'+name}

    def path_params(path, *names):
        for op in paths[path].values():
            op['parameters'] = [dict(name=name, **{'in': 'path'}, required=True, schema=string()) for name in names]

    revision = dict(type='integer', minimum=0)
    point = dict(x=number(-5,5), y=number(0,5), z=number(-5,5))
    notes = dict(title=string(), consistent=string(6000), changes=string(6000), findings=string(12000))
    frame = obj(dict(shot_id=string(), asset_id=string(), role=string(), timestamp_s=dict(type=['number','null'])),
                ('shot_id','asset_id','role','timestamp_s'))
    review = '/productions/continuity/{production_id}/{episode_scope}'
    paths[review] = {'get': operation('List saved frame continuity reviews in this episode or quick production'),
                     'post': operation('Save two frame positions and their current shot states',
                                       obj(dict(frames={**array(frame,2), 'minItems':2}, **notes), ('frames',)))}
    paths[review+'/frames'] = {'get': operation('List selectable local assets and their roles by shot')}
    paths[review+'/{review_id}'] = {
        'get': operation('Read both frame sources, their shot snapshots, expectations and visual findings'),
        'put': operation('Update continuity notes with a saved review revision', obj(dict(expected_revision=revision, **notes), ('expected_revision',)))}
    attach = dict(expected_revision=revision, expected_video_revision=revision, target_shot_id=string(),
                  side=dict(type='integer', enum=[0,1]))
    paths[review+'/{review_id}/attach'] = {'post': operation('Attach one reviewed asset as a video reference',
                                                           obj(attach, attach))}
    for suffix, names in (('', ()), ('/frames', ()), ('/{review_id}', ('review_id',)), ('/{review_id}/attach', ('review_id',))):
        path_params(review+suffix, 'production_id','episode_scope', *names)

    preview = '/productions/shots/{id}/generation-preview'
    paths[preview] = {'get': operation('Compile saved video inputs, voices and render timing locally; never submit a provider request')}
    path_params(preview, 'id')
    paths['/productions/shots/{id}']['put']['requestBody']['content']['application/json']['schema']['properties']['intended_edit_duration'] = {
        'type':['number','null'], 'exclusiveMinimum':0, 'maximum':3600, 'description':'Planned edit seconds; null clears. Independent of render duration.'}
    prop = dict(name=string(80), **{**point, 'y':number(0,4)}, width=number(.02,8),
                height=number(.02,5), depth=number(.02,8), rotation=number(-180,180))
    eyeline = dict(subject=dict(type='integer',minimum=0,maximum=3), **point)
    view = dict(id=string(80), name=string(80), camera=ref('StagingCamera'))
    subject = dict(name=string(80), asset_id=dict(type=['string','null']), x=point['x'], z=point['z'],
                   rotation=prop['rotation'], arms=number(-90,150), head=number(-60,60),
                   pose=dict(enum=['stand','walk','sit','crouch','reach','fight','slide']))
    mark = dict(subject=eyeline['subject'], **{k: subject[k] for k in ('x','z','rotation','pose','arms','head')})
    view_schema = obj(dict(**view, marks=array(obj(mark,mark),4)), view)
    geometry = dict(subjects={**array(obj(subject,subject),4), 'minItems':1}, environment=string(800), style=string(500),
                    props=array(obj(prop,prop),24), eyelines=array(obj(eyeline,eyeline),4))
    layout = dict(title=string(), geometry=obj(geometry,geometry), views={**array(view_schema,16), 'minItems':1})
    blocking = '/filmmaking/blocking/{production_id}/{episode_scope}'
    paths[blocking] = {'get':operation('List shared layouts for this episode or quick production'),
                       'post':operation('Save scene geometry and multiple portrait camera views', obj(layout,layout))}
    paths[blocking+'/{layout_id}'] = {
        'get':operation('Read saved scene geometry, named views and layout revision'),
        'put':operation('Replace geometry and views at the saved layout revision',
                        obj(dict(expected_revision=revision,**layout),('expected_revision',*layout)))}
    staged = blocking+'/{layout_id}/views/{view_id}'
    paths[staged] = {'get':operation('Read saved geometry with the selected portrait camera applied')}
    paths[staged+'/reference.png'] = {'post':operation('Export a portrait PNG from saved geometry and camera with no provider call',
                                                        obj(dict(expected_revision=revision),('expected_revision',)))}
    paths[staged+'/reference.png']['post']['responses']['200'] = {
        'description':'720 by 1280 PNG','content':{'image/png':{'schema':{'type':'string','format':'binary'}}}}
    for suffix,names in (('',()), ('/{layout_id}',('layout_id',)), ('/{layout_id}/views/{view_id}',('layout_id','view_id')),
                         ('/{layout_id}/views/{view_id}/reference.png',('layout_id','view_id'))):
        path_params(blocking+suffix,'production_id','episode_scope',*names)
    link = '/filmmaking/shots/{id}/blocking'
    paths[link] = {'get':operation('Read the shot’s shared layout and view link'),
                   'put':operation('Link a saved shared view or pass null for both IDs to unlink',
                                   obj(dict(expected_revision=revision, expected_layout_revision=revision,
                                            layout_id=dict(type=['string','null']), view_id=dict(type=['string','null'])),
                                       ('expected_revision','layout_id','view_id')))}
    path_params(link,'id')
