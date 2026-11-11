import tempfile
import time
import unittest
from unittest.mock import patch
import studio_server as studio
from agent_api import APIError
from test_studio import PNG

class ShotKitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=studio.Studio(mock=True,storage=self.temp.name);self.api=self.app.agent
        self.app.update(signed_in=True);self.network=patch('httpx.Client');self.network.start()
    def tearDown(self):self.network.stop();self.temp.cleanup()
    def call(self,method,path,data=None,key=None):return self.api.dispatch(method,'/agent/v1/'+path,data or {},key)[1]
    def upload(self,**flags):
        asset=self.app.upload({'name':'f.png','data_url':PNG})
        if flags:next(a for a in self.app.assets if a['id']==asset['id']).update(flags)
        return asset['id']
    def scene(self,**changes):
        scene=self.call('POST','scenes',{'title':'Knight enters','scene':{'prompt':'The knight walks to the counter and sits.'}})
        return self.call('PATCH','scenes/'+scene['id'],{'expected_revision':scene['revision'],'changes':changes}) if changes else scene
    def kit(self,scene,**fields):
        scene=self.call('GET','scenes/'+scene['id'])
        return self.call('PUT',f"scenes/{scene['id']}/kit",{'expected_revision':scene['revision'],**fields})
    def failing(self,view):return sorted(c['id'] for c in view['checks'] if not c['ok'])

    def test_an_empty_shot_lists_everything_missing(self):
        view=self.call('GET',f"scenes/{self.scene()['id']}/kit")
        self.assertFalse(view['ready'])
        self.assertEqual(self.failing(view),['complexity','direction','end_state','first_frame','staging'])
        self.assertTrue(all(view['missing']))

    def test_end_state_needs_a_last_frame_made_from_the_first(self):
        staging=self.upload();scene=self.scene(first={'asset_id':self.upload()})
        base=dict(camera='Medium shot, slow push-in.',action='He walks to the counter.',complex_action=False,staging_asset_id=staging)
        view=self.kit(scene,**base,end_state='He ends seated at the counter.')
        self.assertEqual(self.failing(view),['last_frame','last_from_first'])
        scene=self.call('PATCH','scenes/'+scene['id'],{'expected_revision':view['revision'],'changes':{'last':{'asset_id':self.upload()}}})
        self.assertEqual(self.failing(self.kit(scene)),['last_from_first'])
        self.assertTrue(self.kit(scene,last_frame_from_first=True)['ready'])
        # Free motion needs no last frame; a shot cannot be both.
        other=self.scene(first={'asset_id':self.upload()})
        self.assertTrue(self.kit(other,**base,free_motion=True)['ready'])
        with self.assertRaises(APIError):self.kit(other,end_state='Ends seated.')

    def test_complex_action_needs_an_approved_middle_keyframe_made_from_the_first(self):
        staging=self.upload();scene=self.scene(first={'asset_id':self.upload()})
        base=dict(camera='Wide, locked.',action='He trips on the step, then catches the railing and steadies himself.',
                  free_motion=True,staging_asset_id=staging)
        # Leaving the decision open fails; a multi-beat action marked simple shows a visible hint.
        self.assertIn('complexity',self.failing(self.kit(scene,**base)))
        simple=self.kit(scene,complex_action=False)
        self.assertTrue(simple['ready']);self.assertIn('middle keyframe',simple['hints'][0])
        view=self.kit(scene,complex_action=True)
        self.assertEqual(self.failing(view),['middle_frame','middle_from_first'])
        duration=self.call('GET','scenes/'+scene['id'])['scene']['duration']
        # A keyframe at the very end, an unapproved one or the staging render does not count.
        for key in ({'source':{'asset_id':self.upload()},'slot':duration*3},{'source':{'asset_id':self.upload(generated=True,approved=False)},'slot':3},
                    {'source':{'asset_id':staging},'slot':3}):
            fresh=self.call('GET','scenes/'+scene['id'])
            self.call('PATCH','scenes/'+scene['id'],{'expected_revision':fresh['revision'],'changes':{'keys':[key]}})
            self.assertIn('middle_frame',self.failing(self.call('GET',f"scenes/{scene['id']}/kit")),key)
        fresh=self.call('GET','scenes/'+scene['id'])
        self.call('PATCH','scenes/'+scene['id'],{'expected_revision':fresh['revision'],'changes':{'keys':[{'source':{'asset_id':self.upload()},'slot':3}]}})
        self.assertEqual(self.failing(self.call('GET',f"scenes/{scene['id']}/kit")),['middle_from_first'])
        ready=self.kit(scene,middle_frame_from_first=True)
        self.assertTrue(ready['ready']);self.assertTrue(ready['has_middle_frame']);self.assertEqual(ready['hints'],[])

    def test_the_staging_render_never_reaches_the_video_model(self):
        staging=self.upload()
        for changes in ({'first':{'asset_id':staging}},{'first':{'asset_id':self.upload()},'refs':[{'source':{'asset_id':staging}}]}):
            view=self.kit(self.scene(**changes),camera='Wide.',action='Walks.',complex_action=False,free_motion=True,staging_asset_id=staging)
            self.assertIn('no_mockup',self.failing(view));self.assertIn('mannequins',' '.join(view['missing']))

    def test_generated_frames_must_be_approved(self):
        frame=self.upload(generated=True,approved=False)
        view=self.kit(self.scene(first={'asset_id':frame}),camera='Wide.',action='Walks.',complex_action=False,free_motion=True,staging_asset_id=self.upload())
        # Studio's own validation also refuses an unapproved generated start frame.
        self.assertEqual(self.failing(view),['first_frame','prompt']);self.assertIn('not approved',view['missing'][0])
        next(a for a in self.app.assets if a['id']==frame)['approved']=True
        self.assertTrue(self.call('GET',f"scenes/{view['scene_id']}/kit")['ready'])

    def test_prompt_issues_block_readiness(self):
        scene=self.scene(first={'asset_id':self.upload()})
        self.kit(scene,camera='Wide.',action='Walks.',complex_action=False,free_motion=True,staging_asset_id=self.upload())
        with patch.object(self.api,'validation',return_value={'valid':True,'errors':[],'prompt_issues':[{'message':'Mention Rex with an action or hold.'}]}):
            view=self.call('GET',f"scenes/{scene['id']}/kit")
        self.assertEqual(self.failing(view),['prompt']);self.assertIn('Rex',view['missing'][0])

    def test_kit_edits_are_scene_revisions_and_invalid_fields_are_refused(self):
        scene=self.scene()
        view=self.kit(scene,camera='Wide.')
        self.assertEqual(view['revision'],scene['revision']+1)
        for bad in ({'free_motion':'yes'},{'staging_asset_id':'missing'},{'camera':'x'*2001},{'lens':'35mm'}):
            with self.assertRaises(APIError,msg=bad):self.kit(scene,**bad)
        with self.assertRaises(APIError) as error:
            self.call('PUT',f"scenes/{scene['id']}/kit",{'expected_revision':1,'camera':'Wide.'})
        self.assertEqual(error.exception.status,409)
        # The kit survives ordinary scene edits.
        fresh=self.call('GET','scenes/'+scene['id'])
        self.call('PATCH','scenes/'+scene['id'],{'expected_revision':fresh['revision'],'changes':{'prompt':'The knight runs.'}})
        self.assertEqual(self.call('GET',f"scenes/{scene['id']}/kit")['kit']['camera'],'Wide.')

    def test_takes_record_the_kit_and_stats_compare_keep_rates(self):
        ready=self.scene(first={'asset_id':self.upload()},last={'asset_id':self.upload()})
        self.kit(ready,camera='Wide.',action='Walks.',complex_action=False,end_state='Seated.',last_frame_from_first=True,staging_asset_id=self.upload())
        bare=self.scene()
        for scene,key,verdict in ((ready,'kit-stats-ready-1','keep'),(bare,'kit-stats-bare-1','reject')):
            scene=self.call('GET','scenes/'+scene['id'])
            job=self.call('POST',f"scenes/{scene['id']}/generate",{'expected_revision':scene['revision'],'approved':True},key)
            for _ in range(50):
                job=next(j for j in self.app.records() if j['id']==job['id'])
                if job['status']!='pending':break
                time.sleep(.1)
            self.assertEqual(job['kit']['ready'],scene is ready or key.endswith('ready-1'))
            self.call('POST',f"jobs/{job['id']}/human-review",{'verdict':verdict,'human_words':'Noted.','notes':'Noted.'})
        groups=self.call('GET','kit/stats')['groups']
        self.assertEqual(groups['complete kit'],{'takes':1,'keep':1,'retry':0,'reject':0,'keep_rate':1.0})
        self.assertEqual(groups['incomplete kit']['keep_rate'],0.0)
        self.assertEqual(groups['first and last frames']['takes'],1);self.assertEqual(groups['first frame only']['takes'],1)

if __name__=='__main__':unittest.main()
