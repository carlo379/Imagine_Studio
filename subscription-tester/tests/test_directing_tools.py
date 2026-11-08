import base64
import io
import json
import subprocess
import unittest

from PIL import Image, ImageDraw
from agent_client import AgentError
import test_camera_reference


class DirectingToolTests(unittest.TestCase):
    setUpClass = test_camera_reference.CameraReferenceTests.__dict__['setUpClass']

    def image(self, name, color):
        image = Image.new('RGB', (120, 192), '#282828')
        draw = ImageDraw.Draw(image)
        draw.rectangle((30, 70, 90, 170), fill='#777777')
        draw.ellipse((40, 25, 80, 75), fill=color)
        with io.BytesIO() as buffer:
            image.save(buffer, 'PNG')
            url = 'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
        asset = self.client.request('assets', 'POST', dict(name=name, data_url=url))
        self.client.request('assets/'+asset['id']+'/annotations', 'POST', {'approved': True})
        return asset

    def video(self, shot):
        return self.client.request('productions/shots/'+shot['id'])['video']

    def test_face_switch_browser_write_reads_back_in_agent_api(self):
        p = self.client.create_production('Face switch fixture')['production']
        before = self.client.create_shot(p['id'], 'Hunter before')
        after = self.client.create_shot(p['id'], 'Hunter after')
        self.client.request('references', 'POST', dict(title='Hunter',handle='Hunter',category='Character',voice='rex'))
        for shot, name, color in ((before,'Original face','#c98160'),(after,'Changed face','#ead7a5')):
            self.client.edit_scene(self.video(shot), {'first': self.image(name,color),
                'prompt':'@Hunter looks down at his hands.'}, named_references=['Hunter'])
            preview = self.client.request('productions/shots/'+shot['id']+'/generation-preview')
            self.assertEqual(preview['request']['reference_audios'], [{'voice_id':'rex'}])
        path = 'productions/continuity/'+p['id']+'/quick'
        catalog = {s['shot_id']: s for s in self.client.request(path+'/frames')}
        review = self.client.request(path, 'POST', dict(title='Face switch',
            consistent='Armor, pose, framing, lighting', changes='Only the hunter’s face changes.',
            frames=[{**catalog[s['id']]['frames'][0], 'shot_id': s['id']} for s in (before, after)]))
        target = self.client.create_shot(p['id'], 'Next shot')
        self.browser(productionId=p['id'], episodeId=None, reviewId=review['id'], targetId=target['id'])
        saved = self.client.request(path+'/'+review['id'])
        self.assertIn('checked by the director', saved['findings'])
        self.assertEqual(saved['changes'], review['changes'])
        self.assertEqual(saved['frames'], review['frames'])
        self.assertEqual(saved['revision'], 2)
        with self.assertRaises(AgentError) as conflict:
            self.client.request(path+'/'+saved['id'],'PUT',dict(expected_revision=1,findings='Earlier copy'))
        self.assertEqual(conflict.exception.status,409)
        self.browser(scenario='hunter',shotId=after['id'])
        video = self.video(target)
        self.assertEqual(video['scene']['refs'][0]['source']['id'], saved['frames'][1]['asset_id'])
        retry = self.client.request(path+'/'+saved['id']+'/attach', 'POST', dict(
            expected_revision=saved['revision'], side=1, target_shot_id=target['id'],
            expected_video_revision=video['revision']))
        self.assertEqual(retry,video)

    def browser(self, **fields):
        subprocess.run(['node', 'tests/directing_ui_fixture.cjs', json.dumps(dict(
            base=f'http://127.0.0.1:{self.server.server_port}', **fields))], check=True, timeout=20)

    def test_video_preview_and_two_frames_in_one_shot(self):
        p = self.client.create_production('Tavern test')['production']
        shot = self.client.create_shot(p['id'], 'Chicken escape')
        first = self.image('Armor collar at opening', '#a66558')
        key = self.image('Armor collar at emergence', '#a66558')
        last = self.image('Armor collar at closing', '#a66558')
        voice = self.client.request('references', 'POST', {
            'title': 'Sorceress', 'handle': 'Sorceress', 'category': 'Character', 'voice': 'eve'})
        self.assertEqual(voice['voice'], 'eve')
        video = self.client.edit_scene(self.video(shot), {
            'first': first, 'last': last, 'keys': [dict(slot=4, source=key)],
            'duration': 4, 'prompt': 'The chicken escapes the armor. @Sorceress watches in silence.'
        }, named_references=['Sorceress'])
        path = 'productions/shots/'+shot['id']
        self.client.request(path, 'PUT', dict(expected_revision=shot['revision'], intended_edit_duration=1.5))
        preview = self.client.request(path+'/generation-preview')
        self.assertEqual(preview['request']['reference_audios'], [{'voice_id':'eve'}], preview['issues'])
        self.assertEqual(preview['request']['prompt'], self.client.validate(video)['request']['prompt'])
        self.assertEqual([i['asset_id'] for i in preview['images']], [a['id'] for a in (first,key,last)])
        self.assertEqual(preview['intended_edit_duration'], 1.5)
        self.browser(scenario='preview', shotId=shot['id'])
        self.assertEqual(self.client.request(path+'/generation-preview')['intended_edit_duration'],1.25)
        review_path = 'productions/continuity/'+p['id']+'/quick'
        group = next(g for g in self.client.request(review_path+'/frames') if g['shot_id']==shot['id'])
        review = self.client.request(review_path,'POST',dict(consistent='Armor collar', frames=[
            {**f, 'shot_id': shot['id']} for f in group['frames'] if f['role'] in ('First frame','Keyframe')]))
        self.assertEqual([f['timestamp_s'] for f in review['frames']], [0,4/3])
        self.assertEqual({f['state']['video']['revision'] for f in review['frames']}, {video['revision']})
        bad = self.client.edit_scene(video, {'resolution':'1080p'})
        preview = self.client.request(path+'/generation-preview')
        self.assertEqual(preview['video_revision'],bad['revision'])
        self.assertFalse(preview['valid'])
        self.assertTrue(any('720p' in issue['message'] for issue in preview['issues']))
        self.assertEqual(len(preview['images']),3)
        self.assertFalse(self.client.request('jobs'))

    def test_shared_alley_geometry_views_export_and_director_update(self):
        p = self.client.create_production('Alley blocking test')['production']
        slide = self.client.create_shot(p['id'], 'Low slide')
        rivals = self.client.create_shot(p['id'], 'From the rivals')
        defaults = self.client.camera_presets()['defaults']
        actor = defaults['subjects'][0]
        def prop(name, x, y, z, width, height, depth):
            return dict(name=name,x=x,y=y,z=z,width=width,height=height,depth=depth,rotation=0)
        geometry = dict(subjects=[
            dict(actor,name='Hunter',x=0,z=-.7),
            dict(actor,name='Hooded sorceress',pose='walk',x=2,z=-1.5),
            dict(actor,name='Rival',x=-1.8,z=2.2,rotation=140),
        ], props=[
            prop('Stall',1.9,.85,.3,1.4,.12,.8),prop('Cloak peg',2.35,1.5,-.3,.09,.12,.25),
            prop('Basket',1,0,.65,.42,.37,.36),prop('Basket stack',1.55,0,1,.5,.66,.5),
        ], eyelines=[dict(subject=2,x=0,y=.65,z=-1.3)], environment='Market alley',style='Overcast')
        camera = defaults['camera']
        mark = dict(subject=1,x=1.9,z=.3,rotation=0,pose='slide',arms=0,head=0)
        views = [dict(id='slide',name='Low slide',marks=[mark],camera=dict(camera,elevation=-5,target_y=.65,distance=4,lens=28)),
                 dict(id='rivals',name='Rivals’ angle',camera=dict(camera,yaw=-30,elevation=10,distance=3.4,lens=32))]
        path = 'filmmaking/blocking/'+p['id']+'/quick'
        layout = self.client.request(path,'POST',dict(title='Market alley', geometry=geometry, views=views))
        saved_path = path+'/'+layout['id']
        self.client.request('filmmaking/shots/'+slide['id']+'/blocking','PUT',
            dict(expected_revision=0, expected_layout_revision=layout['revision'], layout_id=layout['id'],view_id='slide'))
        self.browser(scenario='blocking', shotId=rivals['id'],layoutId=layout['id'])
        saved = self.client.request(saved_path)
        self.assertEqual(saved['geometry']['props'][0]['name'],'Market stall')
        self.assertEqual(saved['geometry']['props'][0]['x'],1.25)
        link = self.client.request('filmmaking/shots/'+rivals['id']+'/blocking')
        self.assertEqual((link['layout_id'],link['view_id']),(layout['id'],'rivals'))
        outputs = []
        for view in views:
            url = saved_path+'/views/'+view['id']
            stage = self.client.request(url)
            self.assertEqual(stage['props'],saved['geometry']['props'])
            self.assertEqual(stage['subjects'][1]['pose'], 'slide' if view['id']=='slide' else 'walk')
            raw = self.client.request(url+'/reference.png','POST',dict(expected_revision=saved['revision']))
            with Image.open(io.BytesIO(raw)) as im:
                self.assertEqual(im.size,(720,1280))
                im.verify()
            outputs.append(raw)
        self.assertNotEqual(*outputs)
        self.assertFalse(self.client.request('jobs'))
