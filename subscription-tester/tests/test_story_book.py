import base64
import copy
import io
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from story_book import preview
from studio_server import Studio
from agent_api import APIError

SCRIPT='''# The Signal
Genre: Sci-Fi, Adventure
Tone: Hopeful
Character: Eli: Curious explorer
Location: Radio tower: An abandoned tower
ACT 1 — Discovery
INT. RADIO TOWER - NIGHT
ELI
I can hear you.
ACT 2 — The choice
EXT. ROOFTOP - DAWN
ELI
I am coming.
'''
class ImportTests(unittest.TestCase):
    def test_screenplay_populates_reviewable_book_and_keeps_original(self):
        r=preview(dict(text=SCRIPT,name='signal.md'))
        self.assertEqual(r['answers']['title'],'The Signal')
        self.assertEqual(r['answers']['genre'],'Sci-Fi, Adventure')
        self.assertEqual(r['guide']['script'],SCRIPT)
        self.assertEqual(r['guide']['cast'][0]['name'],'Eli')
        self.assertEqual(len(r['guide']['acts']),2)
        self.assertIn('Rooftop',[p['name'].title() for p in r['guide']['places']])
        self.assertTrue(r['review_required'])
    def test_prose_is_preserved_without_inventing_people(self):
        r=preview(dict(text='A quiet robot wakes in a garden. He hears a song.',name='Garden.txt'))
        self.assertEqual(r['answers']['title'],'Garden')
        self.assertEqual(r['guide']['cast'],[])
        self.assertEqual(r['guide']['places'],[])
        self.assertIn('quiet robot',r['answers']['idea'])
    def test_fountain_and_docx(self):
        self.assertEqual(preview(dict(name='Story.fountain',base64=base64.b64encode(SCRIPT.encode()).decode()))['answers']['title'],'The Signal')
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Title: My Film</w:t></w:r></w:p><w:p><w:r><w:t>A robot finds a friend.</w:t></w:r></w:p></w:body></w:document>')
        r=preview(dict(name='Story.docx',base64=base64.b64encode(buf.getvalue()).decode()))
        self.assertEqual(r['answers']['title'],'My Film')
        self.assertIn('robot finds',r['guide']['script'])
    def test_empty_or_oversize_story_rejected(self):
        for value in ('','x'*60001):
            with self.assertRaises(APIError):preview(dict(text=value))

class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name);self.p=self.app.productions;self.f=self.app.filmmaking
        self.pid=self.p.dispatch('POST',[],dict(kind='story',title='Test story'))[1]['production']['id']
        self.world=self.f.save_world(self.pid,dict(expected_revision=0,answers=dict(title='The Signal',idea='A robot finds a signal.'),guide=dict(cast=[dict(id='c',name='')],places=[dict(id='p',name='')],acts=[],script='')))
        with patch.object(self.app,'spawn',lambda fn,*args:fn(*args)):self.j=self.f.plan(self.pid,dict(expected_revision=self.world['revision'],approved=True),'storybook-original')
        self.j=self.p.get(self.j['id'],'world-job')
    def tearDown(self):self.p.sql.close();self.tmp.cleanup()
    def test_blank_optional_cards_allow_generated_cast_and_setting(self):
        self.assertEqual(self.j['status'],'done')
        self.assertEqual(len(self.j['result']['assets']),2)
        self.assertEqual(self.f.world(self.pid)['answers']['title'],'The Signal')
    def test_fork_preserves_original_and_connected_visuals(self):
        workshop=self.f.workshop.start(self.pid,dict(job_id=self.j['id'],expected_revision=self.j['revision']))
        old=copy.deepcopy(self.p.get(self.j['id'],'world-job'));views=copy.deepcopy(workshop['views']);media=copy.deepcopy(self.app.images.db)
        with self.assertRaises(APIError):self.f.edit_plan(old,dict(expected_revision=old['revision'],result=old['result']))
        new=self.f.fork_plan(old,dict(expected_revision=old['revision']))
        draft=copy.deepcopy(new['result']);draft['scenes'][0]['text']='An edited opening.'
        self.f.edit_plan(new,dict(expected_revision=new['revision'],result=draft))
        self.assertEqual(self.p.get(old['id'],'world-job'),old)
        self.assertEqual(self.f.workshop.snapshot(self.pid,old['id'])['views'],views)
        self.assertEqual(self.app.images.db,media)
        self.assertFalse(new.get('workshop_started',False))
    def test_targeted_revision_keeps_other_scenes_assets_and_original(self):
        original=copy.deepcopy(self.j)
        data=dict(expected_revision=self.world['revision'],approved=True,revision_of=self.j['id'],expected_job_revision=self.j['revision'],scene_index=1,instruction='Make this scene tenser.')
        with patch.object(self.app,'spawn',lambda fn,*args:fn(*args)):j=self.f.plan(self.pid,data,'storybook-revision')
        result=self.p.get(j['id'],'world-job')['result']
        self.assertEqual(result['scenes'][0],original['result']['scenes'][0])
        self.assertEqual(result['assets'],original['result']['assets'])
        self.assertIn('tenser',result['scenes'][1]['text'])
        self.assertEqual(self.p.get(original['id'],'world-job'),original)
        again=self.f.plan(self.pid,data,'storybook-revision');self.assertEqual(j['id'],again['id'])
    def test_revision_rejects_cross_production_and_invalid_scope(self):
        other=self.p.dispatch('POST',[],dict(kind='quick',title='Other'))[1]['production']['id']
        w=self.f.save_world(other,dict(expected_revision=0,answers=dict(idea='Other story')))
        with self.assertRaises(APIError):self.f.plan(other,dict(expected_revision=w['revision'],approved=True,revision_of=self.j['id'],expected_job_revision=self.j['revision'],scene_index=0,instruction='Change it'),'storybook-cross-owner')
        with self.assertRaises(APIError):self.f.plan(self.pid,dict(expected_revision=self.world['revision'],approved=True,revision_of=self.j['id'],expected_job_revision=self.j['revision'],scene_index=99,instruction='Change it'),'storybook-bad-scope')
    def test_import_preview_has_no_saved_side_effects(self):
        before=copy.deepcopy(self.p.all('world'));jobs=copy.deepcopy(self.p.all('world-job'))
        r=self.f.dispatch('POST',['worlds',self.pid,'import-preview'],dict(text=SCRIPT),None)[1]
        self.f.workshop.normalize_guide(r['guide'])
        self.assertEqual(self.p.all('world'),before);self.assertEqual(self.p.all('world-job'),jobs)

    def test_handoff_populates_blank_book_and_updates_revision_atomically(self):
        s=self.f.workshop.start(self.pid,dict(job_id=self.j['id'],expected_revision=self.j['revision']))
        world=self.f.world(self.pid)
        self.assertEqual(world['guide']['cast'][0]['name'],'Story hero')
        self.assertEqual(world['guide']['places'][0]['name'],'Story world')
        self.assertEqual(len(world['guide']['acts']),2)
        self.assertEqual(world['revision'],s['job']['world_revision'])
        self.assertEqual(self.app.images.db['jobs'],[])
        applied=self.f.apply(s['job'],dict(expected_revision=s['job']['revision']))
        self.assertTrue(applied['applied'])
        self.assertEqual(self.app.stories.record('episodes',applied['episode_id'])['title'],'The Signal')
    def test_provider_revision_cannot_overwrite_other_scenes_or_assets(self):
        base=copy.deepcopy(self.j['result']);malicious=copy.deepcopy(base)
        malicious['scenes'][0]['text']='Unexpected unrelated rewrite'
        malicious['assets'][0]['description']='Unexpected new identity'
        malicious['scenes'][1]['text']='A better ending.'
        j=self.p.new('world-job',production_id=self.pid,world_revision=self.world['revision'],production_revision=self.p.get(self.pid,'production')['revision'],provider='codex',mock=False,status='pending',context=dict(questionnaire=self.world['answers'],guide={},revision_request=dict(instruction='Improve ending',scene_index=1,base_plan=base)),result=None)
        with patch('filmmaking_studio.writing_reply',return_value=malicious):self.f.worker(j)
        saved=self.p.get(j['id'],'world-job');self.assertEqual(saved['status'],'done')
        self.assertEqual(saved['result']['assets'],base['assets'])
        self.assertEqual(saved['result']['scenes'][0],base['scenes'][0])
        self.assertEqual(saved['result']['scenes'][1]['text'],'A better ending.')

    def test_handoff_fills_inferred_profile_without_overwriting_user_details(self):
        world=self.f.world(self.pid)
        guide=copy.deepcopy(world['guide']);guide['cast'][0].update(name='Story hero',role='Mentor')
        world=self.f.save_world(self.pid,dict(expected_revision=world['revision'],answers=world['answers'],guide=guide))
        j=self.p.get(self.j['id'],'world-job');j['world_revision']=world['revision'];j['result']['assets'][0]['profile']=dict(role='Hero',gender='Female',hair='Brown')
        with self.p.sql:self.p.put('world-job',j)
        s=self.f.workshop.start(self.pid,dict(job_id=j['id'],expected_revision=j['revision']))
        hero=s['entities'][0]
        self.assertEqual(hero['profile']['role'],'Mentor')
        self.assertEqual(hero['profile']['gender'],'Female')
        self.assertEqual(hero['profile']['hair'],'Brown')
        self.assertEqual(self.f.world(self.pid)['guide']['cast'][0]['gender'],'Female')
