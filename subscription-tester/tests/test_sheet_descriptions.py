"""Current sheet metadata must not rewrite saved image history."""
import copy
import tempfile
import unittest
from unittest.mock import patch
from studio_server import Studio


class SheetDescriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=Studio(mock=True,storage=self.temp.name);self.p=self.app.productions
        self.addCleanup(self.p.sql.close);self.s=self.app.filmmaking.series;self.w=self.app.filmmaking.workshop
        outline=self.p.dispatch('POST',[],dict(kind='story',title='Description fixture'))[1]
        self.pid=outline['production']['id'];self.eid=outline['episodes'][0]['id']
        self.guide=dict(cast=[dict(id='dad',name='Dad',description='Old look',clothing='Red plaid flannel')],
            places=[dict(id='home',name='House',description='Old room',lighting='Warm')],
            props=[dict(id='tool',name='Tool',description='Old scanner',details='Copper')])
        self.bible=self.s.save_bible(self.pid,dict(expected_revision=0,guide=self.guide))
        self.snapshot=self.s.workshop('series-bible',self.pid,dict(expected_revision=self.bible['revision']))

    def test_card_save_refreshes_all_sheet_descriptions_and_preserves_actual_image_history(self):
        hero=self.snapshot['entities'][0];view=self.snapshot['views'][0]
        with patch.object(self.app,'spawn',lambda fn,*args:fn(*args)):
            batch=self.w.generate(self.pid,dict(job_id=self.snapshot['job']['id'],approved=True,model='gpt-image-2',requests=[dict(view_id=view['id'],expected_revision=view['revision'])]),'description-render-once')
        self.assertEqual(self.p.get(batch['id'],'world-render')['status'],'done')
        rendered=self.w.snapshot(self.pid,self.snapshot['job']['id'])['views'][0]['outputs'][0]
        self.w.confirm(view['id'],dict(expected_revision=view['revision'],asset_id=rendered['id'],approved=True))
        hero=self.w.entity(hero['id'])
        extra=self.w.add_views(hero['id'],dict(expected_revision=hero['revision'],views=[dict(label='Formal outfit',details='Custom suit')]))[0]
        drafts=copy.deepcopy(self.app.images.db);before=self.p.get(extra['id'],'world-asset')
        guide=copy.deepcopy(self.bible['guide'])
        guide['cast'][0].update(name='Dad Carter',description='New face',clothing='Blue jacket')
        guide['places'][0].update(description='New room',lighting='Daylight')
        guide['props'][0].update(description='New scanner',details='Silver')
        self.app.agent.dispatch('PUT','/agent/v1/filmmaking/series/'+self.pid+'/bible',dict(expected_revision=self.bible['revision'],guide=guide))
        for entity in self.snapshot['entities']:
            fresh=self.w.entity(entity['id'])
            self.assertEqual(fresh['description'],self.w.description(fresh['profile']))
            for sheet in self.p.all('world-asset'):
                if sheet.get('entity_id')==entity['id']:
                    self.assertEqual(sheet['description'],fresh['description'])
                    self.assertEqual(sheet['name'],fresh['name'])
                    self.assertNotIn('Old',sheet['description']);self.assertNotIn('Red plaid',sheet['description'])
        after=self.p.get(extra['id'],'world-asset')
        self.assertEqual(after['details'],before['details']);self.assertEqual(after['view'],'Formal outfit')
        self.assertEqual(self.app.images.db,drafts)
        self.assertEqual(self.p.get(view['id'],'world-asset')['selected_asset_id'],rendered['id'])

    def test_name_only_save_refreshes_legacy_copies_without_overwriting_custom_profile(self):
        hero=self.snapshot['entities'][0]
        hero['profile']['clothing']='Independent green coat'
        hero['description']=self.w.description(hero['profile'])
        with self.p.sql:self.p.put('world-entity',hero)
        guide=copy.deepcopy(self.bible['guide']);guide['cast'][0]['name']='Dad Carter'
        saved=self.s.save_bible(self.pid,dict(expected_revision=self.bible['revision'],guide=guide))
        fresh=self.w.entity(hero['id'])
        self.assertIn('Independent green coat',fresh['description'])
        self.assertEqual(self.p.get(self.snapshot['views'][0]['id'],'world-asset')['description'],fresh['description'])
        # A later source description edit is still merged into the current copy.
        guide=copy.deepcopy(saved['guide']);guide['cast'][0]['description']='New appearance'
        self.s.save_bible(self.pid,dict(expected_revision=saved['revision'],guide=guide))
        fresh=self.w.entity(hero['id']);self.assertIn('New appearance',fresh['description'])
        self.assertIn('Independent green coat',fresh['description'])

    def test_unchanged_save_and_reopening_repair_already_stale_sheets(self):
        view=self.p.get(self.snapshot['views'][0]['id'],'world-asset')
        for reopen in (False,True):
            view.update(description='Obsolete copied description')
            with self.p.sql:self.p.put('world-asset',view)
            if reopen:self.s.workshop('series-bible',self.pid,dict(expected_revision=self.s.bible(self.pid)['revision']))
            else:self.s.save_bible(self.pid,dict(expected_revision=self.bible['revision']))
            fresh=self.p.get(view['id'],'world-asset')
            self.assertEqual(fresh['description'],self.w.entity(view['entity_id'])['description'])

    def test_episode_description_is_scoped_and_entity_api_refreshes_sheets(self):
        book=self.s.save_book(self.eid,dict(expected_revision=0,guide=self.guide))
        snapshot=self.s.workshop('episode-book',self.eid,dict(expected_revision=book['revision']))
        guide=copy.deepcopy(book['guide']);guide['places'][0]['description']='Episode-specific room'
        self.s.save_book(self.eid,dict(expected_revision=book['revision'],guide=guide))
        place=next(e for e in snapshot['entities'] if e['category']=='Location')
        sheet=next(v for v in self.p.all('world-asset') if v.get('entity_id')==place['id'])
        self.assertIn('Episode-specific room',sheet['description'])
        self.assertNotIn('Episode-specific room',self.w.entity(self.snapshot['entities'][1]['id'])['description'])
        fresh=self.w.entity(place['id'])
        self.w.edit(fresh['id'],dict(expected_revision=fresh['revision'],description='Explicit workshop description'))
        self.assertEqual(self.p.get(sheet['id'],'world-asset')['description'],'Explicit workshop description')
