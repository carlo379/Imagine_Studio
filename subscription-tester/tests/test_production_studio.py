import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from studio_server import Studio
from agent_api import APIError
from image_studio import mock_png

class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name)
    def tearDown(self):
        self.app.productions.sql.close();self.tmp.cleanup()
    def call(self,method,path='',data=None):
        return self.app.agent.dispatch(method,'/agent/v1/productions'+path,data or {})[1]
    def quick(self):return self.call('POST',data={'kind':'quick','title':'A signal'})
    def test_uploaded_video_is_a_persistent_shot_take_without_changing_draft(self):
        from studio_server import ROOT
        raw=(ROOT/'static'/'mock-video.mp4').read_bytes()
        media=self.app.editing.upload(dict(name='Seedance clip.mp4',base64=base64.b64encode(raw).decode()))
        shot=self.quick()['shots'][0];before=copy.deepcopy(self.app.agent.record(shot['video_id']))
        imported=self.call('POST','/shots/'+shot['id']+'/import-video',dict(expected_revision=shot['revision'],media_id=media['id'],source_label='Seedance',select=True))
        take=imported['take'];self.assertEqual(imported['shot']['selected_video'],take['id'])
        self.assertEqual(self.app.agent.record(shot['video_id']),before)
        self.assertEqual(self.app.download(take['id']),self.app.editing.media_file(media['id'])[1])
        self.assertEqual(self.app.download(take['id']).read_bytes(),raw)
        self.assertIn(take['id'],[j['id'] for j in self.app.records()])
        self.assertEqual(self.call('GET','/shots/'+shot['id'])['video_takes'][0]['source_label'],'Seedance')
        self.assertTrue(self.call('GET','/shots/'+shot['id'])['video_ready'])
        from frame_tools import capture
        frame=capture(self.app,take,{'timestamp_s':0.1});self.assertEqual(frame['source_video_job_id'],take['id'])
        info,path=self.app.editing.source(dict(kind='take',id=take['id']));self.assertTrue(info['video']);self.assertEqual(path.read_bytes(),raw)
        with self.assertRaises(APIError):self.call('POST','/shots/'+shot['id']+'/import-video',dict(expected_revision=shot['revision'],media_id=media['id']))
        self.assertEqual(len(self.app.productions.all('imported-video')),1)
        current=self.call('GET','/shots/'+shot['id']);second=self.call('POST','/shots/'+shot['id']+'/import-video',dict(expected_revision=current['revision'],media_id=media['id'],select=False))
        self.assertEqual(second['shot']['selected_video'],take['id']);self.assertEqual(len(second['shot']['video_takes']),2)
        restored=Studio(mock=True,storage=self.tmp.name)
        try:self.assertEqual(restored.download(take['id']).read_bytes(),raw);self.assertEqual(restored.productions.get(shot['id'],'shot')['selected_video'],take['id'])
        finally:restored.productions.sql.close()

    def test_reorder_keeps_scene_groups_in_script_order(self):
        outline=self.call('POST',data={'kind':'story','title':'Sequence'});p=outline['production'];ep=outline['episodes'][0]
        ep=self.app.stories.episode_edit(self.app.stories.record('episodes',ep['id']),dict(expected_revision=ep['revision'],scenes=[dict(title='First',text='First scene'),dict(title='Second',text='Second scene')]))
        shots=[self.call('POST','/'+p['id']+'/shots',dict(title=str(i),episode_id=ep['id'],story_scene_id=scene['id'])) for scene in ep['scenes'] for i in range(2)]
        later=shots[2:];self.call('POST','/'+p['id']+'/reorder-shots',dict(episode_id=ep['id'],story_scene_id=ep['scenes'][1]['id'],shot_ids=[s['id'] for s in reversed(later)],expected_revisions={s['id']:s['revision'] for s in later}))
        self.assertEqual([s['id'] for s in self.call('GET','/'+p['id'])['shots']],[s['id'] for s in shots[:2]+list(reversed(later))])

    def test_shared_direction_and_atomic_reorder(self):
        p=self.quick()['production'];a=self.call('POST','/'+p['id']+'/shots',{'title':'A'})
        original=self.call('GET','/'+p['id'])['shots'];ids=[shot['id'] for shot in reversed(original)]
        payload=dict(shot_ids=ids,expected_revisions={shot['id']:shot['revision'] for shot in original})
        changed=self.call('POST','/'+p['id']+'/reorder-shots',payload)
        self.assertEqual([shot['id'] for shot in changed['shots']],ids)
        with self.assertRaises(APIError):self.call('POST','/'+p['id']+'/reorder-shots',payload)
        self.assertEqual([shot['id'] for shot in self.call('GET','/'+p['id'])['shots']],ids)
        with self.assertRaises(APIError):self.call('POST','/'+p['id']+'/reorder-shots',dict(payload,story_scene_id='elsewhere'))
        current=self.call('GET','/shots/'+a['id']);video=self.app.agent.record(current['video_id']);prompt=video['scene']['prompt']
        saved=self.call('PUT','/shots/'+a['id'],dict(expected_revision=current['revision'],title='Door already open',story_direction='Start with the door open. Hold their eyelines.'))
        self.assertEqual(self.call('GET','/shots/'+a['id'])['story_direction'],saved['story_direction'])
        self.assertEqual(self.app.filmmaking.video_directions.seed(saved,video),('Start with the door open. Hold their eyelines.',True))
        self.assertEqual(video['scene']['prompt'],prompt)
        self.assertEqual(saved['video_id'],a['video_id']);self.assertEqual(saved['image_id'],a['image_id'])
        with self.assertRaises(APIError):self.call('PUT','/shots/'+a['id'],dict(expected_revision=current['revision'],story_direction='Overwrite newer edits'))

    def test_reversible_shot_archive_and_order_preserve_media(self):
        p=self.quick()['production']
        a=self.call('POST','/'+p['id']+'/shots',{'title':'A'})
        b=self.call('POST','/'+p['id']+'/shots',{'title':'B'})
        self.call('PUT','/shots/'+a['id'],{'expected_revision':a['revision'],'shot_order':2})
        self.call('PUT','/shots/'+b['id'],{'expected_revision':b['revision'],'shot_order':1})
        ordered=self.call('GET','/'+p['id'])['shots']
        self.assertLess([s['id'] for s in ordered].index(b['id']),[s['id'] for s in ordered].index(a['id']))
        a=self.call('GET','/shots/'+a['id'])
        hidden=self.call('PUT','/shots/'+a['id'],{'expected_revision':a['revision'],'archived':True})
        self.assertNotIn(a['id'],[s['id'] for s in self.call('GET','/'+p['id'])['shots']])
        self.assertEqual(hidden['video_id'],a['video_id'])
        self.call('PUT','/shots/'+a['id'],{'expected_revision':hidden['revision'],'archived':False})
        self.assertIn(a['id'],[s['id'] for s in self.call('GET','/'+p['id'])['shots']])

    def test_project_library_excludes_standalone_images_and_keeps_quick_video(self):
        image=self.app.images.create({'title':'Loose image'})
        quick=self.quick()['production']
        located=self.call('POST','/locate',{'kind':'image','id':image['id']})
        self.call('POST','/workspace',{'production_id':located['production_id'],'shot_id':located['shot_id'],'stage':'storyboard','board_view':'image'})
        # Legacy records have no origin marker; a lazily paired video is not proof of Quick Video.
        with self.app.productions.sql:
            for identity in (quick['id'],located['production_id']):
                record=self.app.productions.get(identity,'production');record.pop('origin',None);self.app.productions.put('production',record)
        page=self.call('POST','/recent',{'projects_only':True})
        self.assertEqual([p['id'] for p in page['items']],[quick['id']])
        self.assertEqual(page['production_total'],1)
        self.assertEqual(page['items'][0]['project_label'],'Quick Video')
        self.assertTrue(any(p['title']==image['title'] for p in self.call('POST','/recent')['items']))

    def test_workshop_and_refinement_ownership_repairs_existing_image_wrappers(self):
        story=self.call('POST',data={'kind':'story','title':'Example Series'})['production']
        original=self.app.images.create({'title':'Location'})
        self.call('POST','/recent')
        with self.app.productions.sql:
            self.app.productions.new('world-asset',draft_id=original['id'],production_id=story['id'])
        base=self.app.upload({'data_url':'data:image/png;base64,'+base64.b64encode(mock_png()).decode()})['id']
        self.app.images.db['jobs'].append({'id':'source','mock':True,'draft':copy.deepcopy(original),'outputs':[{'id':base}],'created_at':100})
        edited=self.app.images.create({'title':'Edited location','settings':{'base':{'asset_id':base}}})
        self.app.images.draft(edited['id'])['updated_at']=2000000000
        unrelated=self.app.images.create({'title':'Inspiration only','settings':{'extras':[{'asset_id':base}]}})
        page=self.call('POST','/recent',{'projects_only':True})
        self.assertEqual([p['id'] for p in page['items']],[story['id']])
        self.assertEqual(page['production_total'],1)
        self.assertEqual(page['items'][0]['child_count'],0)
        self.assertEqual(page['items'][0]['last_updated'],2000000000)
        shots=self.app.productions.all('shot')
        for draft in (original,edited):
            shot=next(s for s in shots if s['image_id']==draft['id'])
            wrapper=self.app.productions.get(shot['production_id'],'production')
            self.assertEqual(wrapper['parent_production_id'],story['id'])
        shot=next(s for s in shots if s['image_id']==unrelated['id'])
        self.assertFalse(self.app.productions.get(shot['production_id'],'production').get('parent_production_id'))
        self.assertEqual(len(self.app.images.db['drafts']),3)
        self.assertEqual(self.call('POST','/recent',{'projects_only':True,'parent_id':story['id']})['items'],[])

    def test_media_rename_updates_single_quick_project_and_outline(self):
        outline=self.quick();shot=outline['shots'][0];p=outline['production']
        video=shot['video'];saved=self.app.agent.edit(video['id'],{'expected_revision':video['revision'],'title':'Teaser Scene 6B'})
        updated=self.call('GET','/'+p['id'])
        self.assertEqual(updated['production']['title'],'Teaser Scene 6B')
        self.assertEqual(updated['shots'][0]['title'],'Teaser Scene 6B')
        self.assertEqual(saved['scene'],video['scene'])
        self.assertEqual(self.call('POST','/recent')['items'][0]['title'],'Teaser Scene 6B')
        image=updated['shots'][0]['image'];self.app.images.edit(image['id'],{'expected_revision':image['revision'],'title':'New visual name'})
        self.assertEqual(self.call('GET','/'+p['id'])['production']['title'],'New visual name')
        self.app.agent.edit(saved['id'],{'expected_revision':saved['revision'],'scene':dict(saved['scene'],prompt='Only change the prompt')})
        self.assertEqual(self.call('GET','/'+p['id'])['production']['title'],'New visual name')
        with self.assertRaises(APIError):self.app.agent.edit(video['id'],{'expected_revision':video['revision'],'title':'Stale rename'})
        self.assertEqual(self.call('GET','/'+p['id'])['production']['title'],'New visual name')

    def test_project_and_series_rename_preserve_linked_work(self):
        story=self.call('POST',data={'kind':'story','title':'Original series','brief':'Keep this brief'})
        p=story['production'];child=self.group(self.quick()['production'],p)
        ep=story['episodes'][0];ep=self.call('POST','/'+p['id']+'/scenes',{'episode_id':ep['id'],'expected_revision':ep['revision'],'title':'A scene'})
        self.call('POST','/'+p['id']+'/shots',{'title':'A shot','episode_id':ep['id'],'story_scene_id':ep['scenes'][0]['id']})
        before=self.call('GET','/'+p['id']);media=copy.deepcopy(self.app.agent.db);images=copy.deepcopy(self.app.images.db)
        updated=self.call('PUT','/'+p['id'],{'expected_revision':p['revision'],'title':'  Renamed series  '})
        self.assertEqual(updated['title'],'Renamed series');self.assertEqual(updated['brief'],'Keep this brief')
        self.assertEqual(self.app.stories.record('series',p['series_id'])['title'],'Renamed series')
        self.assertEqual(self.call('POST','/recent')['items'][0]['title'],'Renamed series')
        after=self.call('GET','/'+p['id']);self.assertEqual(after['episodes'],before['episodes']);self.assertEqual(after['shots'],before['shots'])
        self.assertEqual(self.call('GET','/'+child['id'])['production']['parent_production_id'],p['id'])
        self.assertEqual(self.app.agent.db,media);self.assertEqual(self.app.images.db,images)
        with self.assertRaises(APIError):self.call('PUT','/'+p['id'],{'expected_revision':p['revision'],'title':'Stale name'})
        with self.assertRaises(APIError):self.call('PUT','/'+p['id'],{'expected_revision':updated['revision'],'title':'   '})
        self.assertEqual(self.app.stories.record('series',p['series_id'])['title'],'Renamed series')
        quick=self.call('GET','/'+child['id']);renamed=self.call('PUT','/'+child['id'],{'expected_revision':quick['production']['revision'],'title':'My project'})
        self.assertEqual(renamed['title'],'My project');self.assertEqual(self.call('GET','/'+child['id'])['shots'],quick['shots'])
        self.app.productions.sql.close();self.app=Studio(mock=True,storage=self.tmp.name)
        self.assertEqual(self.call('GET','/'+p['id'])['production']['title'],'Renamed series')
        self.assertEqual(self.app.stories.record('series',p['series_id'])['title'],'Renamed series')

    def test_series_rename_rolls_back_if_project_save_fails(self):
        p=self.call('POST',data={'kind':'story','title':'Original'})['production']
        before=copy.deepcopy(self.app.stories.db)
        with patch.object(self.app.productions,'put',side_effect=RuntimeError('Storage unavailable')):
            with self.assertRaises(RuntimeError):self.call('PUT','/'+p['id'],{'expected_revision':p['revision'],'title':'Uncommitted'})
        self.assertEqual(self.app.stories.db,before)
        self.assertEqual(self.call('GET','/'+p['id'])['production']['title'],'Original')

    def test_multi_shot_rename_keeps_project_name_and_other_shot(self):
        outline=self.quick();p=outline['production'];first=outline['shots'][0]
        second=self.call('POST','/'+p['id']+'/shots',{'title':'Another shot'})
        self.app.agent.edit(first['video']['id'],{'expected_revision':first['video']['revision'],'title':'Renamed shot'})
        updated=self.call('GET','/'+p['id'])
        self.assertEqual(updated['production']['title'],p['title'])
        self.assertEqual(next(s for s in updated['shots'] if s['id']==first['id'])['title'],'Renamed shot')
        self.assertEqual(next(s for s in updated['shots'] if s['id']==second['id'])['title'],'Another shot')
    def group(self,p,parent):return self.call('POST','/'+p['id']+'/membership',{'expected_revision':p['revision'],'parent_production_id':parent['id'] if parent else None})
    def test_group_move_detach_preserve_media_scripts_and_timeline(self):
        a=self.call('POST',data={'kind':'story','title':'Story A'})['production'];b=self.call('POST',data={'kind':'story','title':'Story B'})['production'];o=self.quick();p=o['production']
        timeline=self.app.editing.timeline(p['id'])
        before={n:(Path(self.tmp.name)/n).read_bytes() for n in ('scenes.json','image-studio.json','stories.json')}
        moved=self.group(p,a);self.assertEqual(self.call('POST','/recent',{'parent_id':a['id']})['items'][0]['id'],p['id'])
        moved=self.group(moved,b);self.assertEqual(self.call('POST','/recent',{'parent_id':a['id']})['total'],0)
        detached=self.group(moved,None);self.assertIsNone(detached['parent_production_id'])
        self.assertIn(p['id'],[r['id'] for r in self.call('POST','/recent')['items']])
        for n,raw in before.items():self.assertEqual((Path(self.tmp.name)/n).read_bytes(),raw)
        self.assertEqual(self.app.editing.timeline(p['id']),timeline)
        self.assertEqual(self.call('GET','/'+p['id'])['shots'],o['shots'])
    def test_trash_restore_no_rediscovery_or_data_loss(self):
        o=self.quick();p=o['production'];self.call('POST','/workspace',{'production_id':p['id'],'shot_id':o['shots'][0]['id']})
        before=copy.deepcopy(self.app.agent.db);trashed=self.call('POST','/'+p['id']+'/trash',{'expected_revision':p['revision']})
        self.assertEqual(self.call('GET'),[]);self.assertEqual(self.call('GET','/workspace')['production_id'],None)
        self.assertEqual(self.call('POST','/recent',{'archived':True})['items'][0]['id'],p['id'])
        self.assertEqual(self.app.agent.db,before)
        with self.assertRaises(APIError):self.call('POST','/workspace',{'production_id':p['id']})
        self.app.productions.sql.close();self.app=Studio(mock=True,storage=self.tmp.name)
        self.assertEqual(self.call('GET'),[])
        restored=self.call('POST','/'+p['id']+'/restore',{'expected_revision':trashed['revision']})
        self.assertFalse(restored['archived']);self.assertEqual(len(self.call('GET')),1)
        self.assertEqual(self.call('GET','/'+p['id'])['shots'],o['shots'])
    def test_trashing_group_keeps_children_available_and_restore_respects_moves(self):
        a=self.call('POST',data={'kind':'story','title':'Story A'})['production'];b=self.call('POST',data={'kind':'story','title':'Story B'})['production']
        x=self.group(self.quick()['production'],a);y=self.group(self.quick()['production'],a)
        a=self.call('POST','/'+a['id']+'/trash',{'expected_revision':a['revision']})
        roots=self.call('POST','/recent')['items'];self.assertIn(x['id'],[r['id'] for r in roots]);self.assertIn(y['id'],[r['id'] for r in roots])
        self.group(y,b);self.call('POST','/'+a['id']+'/restore',{'expected_revision':a['revision']})
        self.assertEqual([r['id'] for r in self.call('POST','/recent',{'parent_id':a['id']})['items']],[x['id']])
    def test_invalid_cycles_stale_membership_and_foreign_workspace_rejected(self):
        a=self.call('POST',data={'kind':'story','title':'Story A'})['production'];b=self.call('POST',data={'kind':'story','title':'Story B'})['production'];q=self.quick()['production']
        a=self.group(a,b);before=self.call('GET')
        for p,parent in ((b,a),(a,a),(b,q)):
            with self.assertRaises(APIError):self.group(p,parent)
        with self.assertRaises(APIError):self.group(dict(a,revision=1),None)
        with tempfile.TemporaryDirectory() as root:
            other=Studio(mock=True,storage=root)
            try:
                with self.assertRaises(APIError):other.productions.dispatch('POST',[a['id'],'trash'],{'expected_revision':a['revision']})
            finally:other.productions.sql.close()
        self.assertEqual(self.call('GET'),before)
    def test_group_pagination_counts_and_ancestor_activity(self):
        a=self.call('POST',data={'kind':'story','title':'A'})['production'];b=self.call('POST',data={'kind':'story','title':'B'})['production'];self.group(b,a)
        for i in range(12):self.group(self.quick()['production'],b)
        roots=self.call('POST','/recent');self.assertEqual(roots['total'],1);self.assertEqual(roots['production_total'],14);self.assertEqual(roots['items'][0]['child_count'],1)
        page=self.call('POST','/recent',{'parent_id':b['id']});self.assertEqual(page['total'],12);self.assertEqual(len(page['items']),10);self.assertTrue(page['has_more'])
        more=self.call('POST','/recent',{'parent_id':b['id'],'offset':10});self.assertEqual(len(more['items']),2);self.assertFalse(more['has_more'])
        self.assertGreaterEqual(roots['items'][0]['last_updated'],page['items'][0]['last_updated'])
    def test_inferred_group_uses_script_context_and_manual_detach_persists(self):
        story=self.call('POST',data={'kind':'story','title':'Story'})
        o=self.quick();p=o['production'];v=self.app.agent.record(o['shots'][0]['video_id']);v['story_context']={'series_id':story['production']['series_id']}
        page=self.call('POST','/recent',{'parent_id':story['production']['id']});self.assertEqual(page['items'][0]['id'],p['id'])
        p=self.call('GET','/'+p['id'])['production'];self.group(p,None)
        self.assertEqual(self.call('POST','/recent',{'parent_id':story['production']['id']})['total'],0)
        self.assertIn(p['id'],[r['id'] for r in self.call('POST','/recent')['items']])
    def story(self):
        o=self.call('POST',data={'kind':'story','title':'Example Series','episode_title':'Teaser'})
        ep=o['episodes'][0]
        ep=self.call('POST','/'+o['production']['id']+'/scenes',{'episode_id':ep['id'],'expected_revision':1,'title':'The lab','text':'SampleHero discovers a clue.'})
        self.assertEqual(ep['title'],'Teaser')
        s=self.call('POST','/'+o['production']['id']+'/shots',{'episode_id':ep['id'],'story_scene_id':ep['scenes'][0]['id'],'title':'Lab wide'})
        return o,ep,s
    def test_quick_creates_linked_drafts_without_provider_calls(self):
        with patch.object(self.app,'start_video',side_effect=AssertionError('No generation')):
            o=self.quick();s=o['shots'][0]
            self.assertEqual(o['production']['kind'],'quick');self.assertEqual(o['episodes'],[])
            self.assertEqual(s['video']['scene']['prompt'],'');self.assertEqual(s['image']['settings']['prompt'],'')
            w=self.call('POST','/workspace',{'production_id':o['production']['id'],'shot_id':s['id'],'stage':'generate'})
            self.assertEqual(w['shot_id'],s['id']);self.assertEqual(self.app.agent.db['current_id'],s['video']['id']);self.assertEqual(self.app.images.db['current_id'],s['image']['id'])
    def test_story_hierarchy_and_context_revision_warning(self):
        o,ep,s=self.story();v=copy.deepcopy(self.app.agent.record(s['video_id']))
        self.assertEqual(v['story_context']['scene_text'],'SampleHero discovers a clue.')
        ep=self.app.stories.episode_edit(self.app.stories.record('episodes',ep['id']),{'expected_revision':2,'scenes':[dict(ep['scenes'][0],text='A new clue.')]})
        shot=self.call('GET','/shots/'+s['id']);self.assertTrue(shot['script_changed']);self.assertEqual(self.app.agent.record(s['video_id']),v)
        self.call('POST','/shots/'+s['id']+'/refresh-context',{'expected_revision':s['revision']})
        self.assertFalse(self.call('GET','/shots/'+s['id'])['script_changed'])
        self.assertEqual(self.app.agent.record(s['video_id'])['scene'],v['scene'])
    def test_invalid_parent_and_stale_edit_leave_records_intact(self):
        a=self.quick();b=self.quick();sid=a['shots'][0]['id']
        with self.assertRaises(APIError):self.call('POST','/workspace',{'production_id':b['production']['id'],'shot_id':sid})
        with self.assertRaises(APIError):self.call('POST','/workspace',{'production_id':b['production']['id'],'stage':'script'})
        p=a['production'];self.call('PUT','/'+p['id'],{'expected_revision':1,'brief':'A quiet laboratory.'})
        with self.assertRaises(APIError):self.call('PUT','/'+p['id'],{'expected_revision':1,'brief':'Stale'})
        self.assertEqual(self.call('GET','/'+p['id'])['production']['brief'],'A quiet laboratory.')
        self.assertEqual(len(self.call('GET','/'+p['id']+'/versions')),2)
    def test_failed_creation_rolls_back_linked_drafts_and_relationships(self):
        before=copy.deepcopy(self.app.agent.db)
        with patch.object(self.app.images,'create',side_effect=APIError('failed','Test failure')):
            with self.assertRaises(APIError):self.quick()
        self.assertEqual(self.app.agent.db,before);self.assertEqual(self.call('GET'),[])
    def test_migration_is_idempotent_and_does_not_rewrite_existing_work(self):
        video=self.app.agent.create({'title':'Original','scene':{'prompt':'Keep me','duration':12}})
        image=self.app.images.create({'title':'Original image'})
        before={n:(Path(self.tmp.name)/n).read_bytes() for n in ('scenes.json','image-studio.json','stories.json')}
        prods=self.call('GET');self.assertEqual(len(prods),2)
        self.assertEqual(self.call('GET'),prods)
        for n,raw in before.items():self.assertEqual((Path(self.tmp.name)/n).read_bytes(),raw)
        self.app.productions.sql.close();self.app=Studio(mock=True,storage=self.tmp.name)
        self.assertEqual(len(self.call('GET')),2)
        self.assertEqual(self.app.agent.record(video['id'])['scene']['duration'],12)
        self.assertEqual(self.app.images.draft(image['id'])['settings']['prompt'],'')
    def test_existing_linked_image_and_video_pair_share_one_shot(self):
        o,ep,s=self.story()
        # Simulate an older creation path: both media are for a script scene but have no shot relation.
        vid=self.app.stories.media(self.app.stories.record('episodes',ep['id']),{'expected_revision':2,'scene_id':ep['scenes'][0]['id'],'kind':'video'})
        img=self.app.stories.media(self.app.stories.record('episodes',ep['id']),{'expected_revision':2,'scene_id':ep['scenes'][0]['id'],'kind':'image'})
        shots=self.call('GET','/'+o['production']['id'])['shots']
        paired=next(x for x in shots if x['video_id']==vid['id']);self.assertEqual(paired['image_id'],img['id']);self.assertEqual(len(shots),2)
    def test_image_placement_preserves_prompt_and_respects_video_revision(self):
        o=self.quick();s=o['shots'][0];v=s['video']
        self.app.agent.patch(v['id'],{'expected_revision':v['revision'],'changes':{'prompt':'Keep the camera steady.'}})
        a=self.app.upload({'data_url':'data:image/png;base64,'+base64.b64encode(mock_png()).decode()})
        body={'expected_revision':s['revision'],'expected_video_revision':v['revision'],'asset_id':a['id'],'target':'first'}
        with self.assertRaises(APIError):self.call('POST','/shots/'+s['id']+'/place-image',body)
        result=self.call('POST','/shots/'+s['id']+'/place-image',{**body,'expected_video_revision':2})
        self.assertEqual(result['video']['scene']['prompt'],'Keep the camera steady.');self.assertEqual(result['video']['scene']['first']['id'],a['id'])
        self.assertTrue(result['shot']['image_ready'])
    def test_invalid_keyframe_does_not_change_shot_or_video(self):
        o=self.quick();s=o['shots'][0];a=self.app.upload({'data_url':'data:image/png;base64,'+base64.b64encode(mock_png()).decode()})
        with self.assertRaises(APIError):self.call('POST','/shots/'+s['id']+'/place-image',{'expected_revision':1,'expected_video_revision':1,'asset_id':a['id'],'target':'keyframe','slot':15})
        self.assertEqual(self.call('GET','/shots/'+s['id'])['revision'],1);self.assertEqual(self.app.agent.record(s['video_id'])['revision'],1)
    def test_removed_scene_keeps_shot_and_media_recoverable(self):
        o,ep,s=self.story();self.app.stories.episode_edit(self.app.stories.record('episodes',ep['id']),{'expected_revision':2,'scenes':[]})
        shot=self.call('GET','/shots/'+s['id']);self.assertTrue(shot['orphaned'])
        w=self.call('POST','/workspace',{'production_id':o['production']['id'],'shot_id':s['id'],'stage':'generate'})
        self.assertEqual(w['shot_id'],s['id']);self.assertEqual(self.app.agent.db['current_id'],s['video_id'])
    def test_mode_separation_and_selected_take_validation(self):
        o=self.quick();s=o['shots'][0]
        self.app.history.append({'id':'other','status':'done','video':'test','settings':{'_studio_video_id':'different'}})
        self.assertEqual(self.call('GET','/shots/'+s['id'])['video_takes'],[])
        with self.assertRaises(APIError):self.call('POST','/shots/'+s['id']+'/select-take',{'expected_revision':1,'kind':'video','id':'other'})

    def test_deselect_video_preserves_takes_and_checks_revision(self):
        s=self.quick()['shots'][0]
        self.app.history.append({'id':'take','status':'done','video':'test','settings':{'_studio_video_id':s['video_id']}})
        chosen=self.call('POST','/shots/'+s['id']+'/select-take',dict(expected_revision=s['revision'],kind='video',id='take'))
        with self.assertRaises(APIError):
            self.call('POST','/shots/'+s['id']+'/select-take',dict(expected_revision=s['revision'],kind='video',id=None))
        cleared=self.call('POST','/shots/'+s['id']+'/select-take',dict(expected_revision=chosen['revision'],kind='video',id=None))
        self.assertIsNone(cleared['selected_video'])
        self.assertEqual([t['id'] for t in cleared['video_takes']],['take'])
        self.assertTrue(cleared['video_ready'])
        with self.assertRaises(APIError):
            self.call('POST','/shots/'+s['id']+'/select-take',dict(expected_revision=cleared['revision'],kind='video'))

    def test_ambiguous_legacy_take_is_not_claimed_by_multiple_shots(self):
        a=self.quick();b=self.quick();s=a['shots'][0]
        self.app.history.append({'id':'old','status':'done','video':'test','settings':{'_studio_scene':s['video']['scene']}})
        self.assertEqual(self.call('GET','/shots/'+s['id'])['video_takes'],[])
        self.app.history.append({'id':'new','status':'done','video':'test','settings':{'_studio_video_id':s['video_id']}})
        self.assertEqual([j['id'] for j in self.call('GET','/shots/'+s['id'])['video_takes']],['new'])
    def test_locate_context_and_private_backup(self):
        o=self.quick();s=o['shots'][0]
        location=self.call('POST','/locate',{'kind':'image','id':s['image_id']})
        self.assertEqual(location['shot_id'],s['id'])
        self.call('POST','/workspace',{**location,'stage':'storyboard','board_view':'image'})
        context=self.call('GET','/context');self.assertEqual(context['workspace']['stage'],'storyboard');self.assertNotIn('token',json.dumps(context))
        backup=Path(self.tmp.name)/'backups/before-production-release-1'
        self.assertTrue(backup.exists());self.assertFalse((backup/'agent-token').exists())
        self.assertEqual((Path(self.tmp.name)/'productions.sqlite3').stat().st_mode&0o777,0o600)

    def test_failed_link_mutation_keeps_worker_job_identity(self):
        job={'id':'in-flight','status':'pending'};chat={'id':'writing','status':'pending'}
        self.app.images.db['jobs'].append(job);self.app.stories.db['chats'].append(chat)
        with self.assertRaises(APIError):
            with self.app.productions.mutation():
                raise APIError('failed','Simulated failed placement')
        self.assertIs(self.app.images.db['jobs'][0],job);self.assertIs(self.app.stories.db['chats'][0],chat)

    def test_recent_pages_are_ten_newest_and_keep_original_edit_times(self):
        for i in range(12):
            image=self.app.images.create({'title':f'Image {i}'})
            self.app.images.draft(image['id'])['updated_at']=1000+i
        page=self.call('POST','/recent')
        self.assertEqual(page['total'],12);self.assertEqual(len(page['items']),10);self.assertTrue(page['has_more'])
        self.assertEqual([p['last_updated'] for p in page['items']],list(range(1011,1001,-1)))
        more=self.call('POST','/recent',{'offset':10,'limit':10})
        self.assertEqual(len(more['items']),2);self.assertFalse(more['has_more'])
        self.assertFalse({p['id'] for p in page['items']}&{p['id'] for p in more['items']})
        for body in ({'limit':0},{'limit':101},{'offset':-1},{'limit':True}):
            with self.assertRaises(APIError):self.call('POST','/recent',body)
    def test_recent_icons_follow_media_and_script_not_names(self):
        image=self.app.images.create({'title':'Not called an image','settings':{'prompt':'A laboratory.'}})
        self.app.images.draft(image['id'])['updated_at']=1234
        video=self.app.agent.create({'title':'Not called a video','scene':{'prompt':'Camera pans.'}})
        story=self.call('POST',data={'kind':'story','title':'Scripts'})
        ep=story['episodes'][0];self.call('POST','/'+story['production']['id']+'/scenes',{'episode_id':ep['id'],'expected_revision':1,'title':'Opening'})
        page=self.call('POST','/recent');bytitle={p['title']:p for p in page['items']}
        self.assertEqual(bytitle[image['title']]['item_type'],'image');self.assertEqual(bytitle[video['title']]['item_type'],'video');self.assertEqual(bytitle['Scripts']['item_type'],'script')
        self.assertEqual(bytitle[image['title']]['last_updated'],1234)
        p=bytitle[image['title']];shot=self.call('GET','/'+p['id'])['shots'][0]
        self.call('POST','/workspace',{'production_id':p['id'],'shot_id':shot['id'],'stage':'storyboard','board_view':'image'})
        current=next(p for p in self.call('POST','/recent')['items'] if p['title']==image['title'])
        self.assertEqual(current['item_type'],'image');self.assertEqual(current['last_updated'],1234)
