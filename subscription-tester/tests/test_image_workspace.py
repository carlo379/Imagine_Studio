"""Image versions stay in their shot; refinement sources and cleanup are deliberate."""
import base64, copy, tempfile, unittest
from unittest.mock import patch
from studio_server import Studio
from image_studio import mock_png
from agent_api import APIError

class ImageWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name)
        self.p=self.call('POST','',{'kind':'quick','title':'Delivery'});self.shot=self.p['shots'][0]
    def tearDown(self):self.app.productions.sql.close();self.tmp.cleanup()
    def call(self,method,path,data=None):return self.app.productions.dispatch(method,path.strip('/').split('/') if path else [],data or {})[1]
    def job(self,draft=None):
        draft=draft or self.app.images.draft(self.shot['image']['id'])
        asset=self.app.upload({'name':'frame.png','data_url':'data:image/png;base64,'+base64.b64encode(mock_png()).decode()})
        job=dict(id=asset['id']+'job',mock=True,status='done',draft=copy.deepcopy(draft),outputs=[{**asset,'approved':True,'candidate_index':0}],created_at=1)
        self.app.images.db['jobs'].insert(0,job);self.app.images.persist();return job
    def refine(self,job):return self.app.images.dispatch('POST',['jobs',job['id'],'refine'],{'asset_id':job['outputs'][0]['id']},None)[1]
    def test_versions_survive_restart_without_new_shots(self):
        job=self.job();selected=self.call('POST','shots/'+self.shot['id']+'/select-take',{'expected_revision':self.shot['revision'],'kind':'image','id':job['outputs'][0]['id']})
        first=self.refine(job);self.call('GET',self.p['production']['id']);second=self.refine(self.job(first))
        copydraft=self.app.images.create({'title':'Saved copy','settings':second['settings'],'parent_draft_id':second['id']})
        outline=self.call('GET',self.p['production']['id']);self.assertEqual(len(outline['shots']),1);shot=outline['shots'][0]
        self.assertEqual(shot['selected_image'],selected['selected_image']);self.assertEqual(len(shot['image_versions']),4);self.assertEqual(len(shot['image_takes']),2)
        self.assertEqual(self.call('POST','locate',{'kind':'image','id':copydraft['id']})['shot_id'],shot['id'])
        self.assertEqual(self.call('GET','shots/'+shot['id'])['image']['id'],copydraft['id'])
        self.app.productions.sql.close();self.app=Studio(mock=True,storage=self.tmp.name)
        self.assertEqual(len(self.call('GET',self.p['production']['id'])['shots']),1);self.assertEqual(len(self.app.images.db['drafts']),4)
    def test_base_only_and_mentions_do_not_resend_references(self):
        source=self.app.images.draft(self.shot['image']['id']);job=self.job(source);asset=job['outputs'][0]['id']
        ref=self.app.save_reference({'title':'Mark','handle':'Mark','category':'Character','description':'Blue shirt','images':[{'asset_id':asset}]})
        source['settings']['bindings']=[{'snapshot':ref,'selected':[0]}];source['settings']['extras']=[{'asset_id':asset}];job['draft']=copy.deepcopy(source)
        record=self.refine(job);self.assertEqual(record['settings']['bindings'][0]['selected'],[]);self.assertEqual(record['settings']['extras'],[])
        record=self.app.images.edit(record['id'],{'expected_revision':record['revision'],'settings':{**record['settings'],'prompt':'Move @Mark onto the walkway. Preserve everything else.'}})
        result=self.app.images.validate(record);self.assertTrue(result['valid']);self.assertEqual(result['source_count'],1);self.assertNotIn('@Mark',result['request']['prompt']);self.assertNotIn('Blue shirt',result['request']['prompt'])
        settings=copy.deepcopy(record['settings']);settings['bindings'][0]['selected']=[0];self.assertEqual(len(self.app.images.expanded_prompt(settings)[1]),2)
    def test_manual_review_invalidates_on_edit_and_checks_revision(self):
        draft=self.app.images.edit(self.shot['image']['id'],{'expected_revision':1,'settings':{'prompt':'Family waits on the walkway.'}})
        reviewed=self.app.images.dispatch('POST',['drafts',draft['id'],'review-prompt'],{'expected_revision':draft['revision'],'reviewed':True},None)[1]
        self.assertTrue(self.app.images.validate(reviewed)['prompt_preparation_current'])
        changed=self.app.images.edit(draft['id'],{'expected_revision':reviewed['revision'],'settings':{**reviewed['settings'],'prompt':'Family stands near the house.'}})
        self.assertFalse(self.app.images.validate(changed)['prompt_preparation_current'])
        with self.assertRaises(APIError):self.app.images.dispatch('POST',['drafts',draft['id'],'review-prompt'],{'expected_revision':reviewed['revision'],'reviewed':True},None)
    def test_agent_direct_image_review_allows_live_submission_but_not_authorization_bypass(self):
        images = self.app.images
        draft = images.create(dict(settings=dict(prompt='A robot waits on the walkway.')))
        self.app.mock = False
        self.app.state['signed_in'] = True
        route = '/agent/v1/image-studio/drafts/'+draft['id']+'/review-prompt'
        generate = '/agent/v1/image-studio/drafts/'+draft['id']+'/generate'
        data = dict(expected_revision=draft['revision'], approved=True)
        with patch.dict(images.config, {'live_generations_enabled':True}), patch.object(self.app, 'spawn') as spawn:
            with self.assertRaises(APIError) as error:
                self.app.agent.dispatch('POST', generate, data, 'agent-image-no-review')
            self.assertEqual(error.exception.code, 'prompt_preparation_required')
            reviewed = self.app.agent.dispatch('POST', route, dict(expected_revision=draft['revision'],
                reviewed=True, authored_by='agent'))[1]
            self.assertEqual(reviewed['manual_prompt_review']['authored_by'], 'agent')
            validation = images.validate(reviewed)
            self.assertTrue(validation['prompt_preparation_current'])
            self.assertTrue(validation['prompt_review_provenance']['current'])
            self.assertEqual(validation['prompt_review_provenance']['authored_by'], 'agent')
            for approved in (False, None):
                with self.assertRaises(APIError) as error:
                    self.app.agent.dispatch('POST', generate, {**data,'approved':approved}, 'agent-image-no-approval')
                self.assertEqual(error.exception.code, 'approval_required')
            with self.assertRaises(APIError) as error:
                self.app.agent.dispatch('POST', generate, data)
            self.assertEqual(error.exception.code, 'idempotency_required')
            spawn.assert_not_called()
            job = self.app.agent.dispatch('POST', generate, data, 'agent-image-approved')[1]
            spawn.assert_called_once()  # Worker is mocked: no image or provider call.
            self.assertEqual(job['prompt_review_provenance']['authored_by'], 'agent')
            self.assertEqual(job['draft']['manual_prompt_review'], reviewed['manual_prompt_review'])
            self.assertEqual(images.job(job['id'])['prompt_review_provenance'], job['prompt_review_provenance'])
            self.assertEqual(self.app.agent.dispatch('POST', generate, data, 'agent-image-approved')[1]['id'], job['id'])
            self.app.state['phase'] = 'idle'
            changed = images.edit(draft['id'], dict(expected_revision=draft['revision'],
                settings=dict(prompt='The robot walks.')))
            self.assertFalse(images.validate(changed)['prompt_preparation_current'])
            self.assertFalse(images.validate(changed)['prompt_review_provenance']['current'])
            with self.assertRaises(APIError) as error:
                self.app.agent.dispatch('POST', generate, dict(expected_revision=changed['revision'], approved=True), 'agent-image-after-edit')
            self.assertEqual(error.exception.code, 'prompt_preparation_required')
            spawn.assert_called_once()

    def test_review_author_defaults_to_human_and_invalid_author_does_not_review(self):
        images = self.app.images
        draft = images.create(dict(settings=dict(prompt='A family waits.')))
        route = ['drafts', draft['id'], 'review-prompt']
        with self.assertRaises(APIError) as error:
            images.dispatch('POST', route, dict(expected_revision=draft['revision'], reviewed=True, authored_by='robot'), None)
        self.assertEqual(error.exception.code, 'invalid_author')
        self.assertNotIn('manual_review_revision', images.draft(draft['id']))
        reviewed = images.dispatch('POST', route, dict(expected_revision=draft['revision'], reviewed=True), None)[1]
        self.assertEqual(reviewed['manual_prompt_review']['authored_by'], 'human')
        self.assertTrue(images.review_provenance(reviewed)['current'])
        legacy = {k:v for k,v in reviewed.items() if k != 'manual_prompt_review'}
        self.assertEqual(images.review_provenance(legacy)['authored_by'], 'human')

    def test_legacy_branches_need_review_and_preserve_media(self):
        job=self.job();legacy=self.app.images.create({'title':'Delivery refinement','settings':{'base':{'asset_id':job['outputs'][0]['id']}}});self.call('GET',self.p['production']['id'])
        branch=next(s for s in self.app.productions.all('shot') if s['image_id']==legacy['id'])
        with self.app.productions.sql:branch['production_id']=self.p['production']['id'];self.app.productions.put('shot',branch)
        candidates=self.call('GET',self.p['production']['id']+'/image-branches');self.assertEqual(len(candidates),1);before=copy.deepcopy(self.app.images.db);c=candidates[0]
        # A real edit or separate shot direction must prevent automatic eligibility.
        with self.app.productions.sql:timeline=self.app.productions.new('timeline',production_id=self.p['production']['id'],clips=[{'shot_id':branch['id']}])
        self.assertEqual(self.call('GET',self.p['production']['id']+'/image-branches'),[])
        with self.app.productions.sql:self.app.productions.sql.execute('DELETE FROM records WHERE id=?',(timeline['id'],))
        with self.app.productions.sql:direction=self.app.productions.new('direction',shot_id=branch['id'],staging={'notes':'Keep this independent shot.'})
        self.assertEqual(self.call('GET',self.p['production']['id']+'/image-branches'),[])
        with self.app.productions.sql:self.app.productions.sql.execute('DELETE FROM records WHERE id=?',(direction['id'],))
        shot=self.call('POST','shots/'+c['shot_id']+'/merge-image-branch',{'expected_revision':c['shot_revision'],'branch_id':branch['id'],'expected_branch_revision':c['branch_revision']})
        self.assertIn(legacy['id'],[d['id'] for d in shot['image_versions']]);self.assertEqual(self.app.images.db,before);self.assertEqual(len(self.call('GET',self.p['production']['id'])['shots']),1)
    def test_explicit_duplicate_and_reversible_trash_keep_versions(self):
        version=self.refine(self.job());self.call('GET',self.p['production']['id']);shot=self.call('GET','shots/'+self.shot['id'])
        duplicate=self.call('POST','shots/'+shot['id']+'/duplicate',{'expected_revision':shot['revision']});self.assertNotEqual(duplicate['image_id'],shot['image_id'])
        archived=self.call('PUT','shots/'+shot['id'],{'expected_revision':shot['revision'],'archived':True});self.assertEqual(len(self.call('GET',self.p['production']['id']+'/shot-trash')),1)
        restored=self.call('PUT','shots/'+shot['id'],{'expected_revision':archived['revision'],'archived':False})
        self.assertIn(version['id'],self.app.productions.image_ids(restored));self.assertEqual(len(self.call('GET',self.p['production']['id'])['shots']),2)

if __name__=='__main__':unittest.main()
