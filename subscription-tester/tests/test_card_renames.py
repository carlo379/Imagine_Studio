"""Stable-ID rename propagation without rewriting creative snapshots."""
import base64
import copy
import tempfile
import unittest
from unittest.mock import patch
from studio_server import Studio
from image_studio import mock_png
from agent_api import APIError


class CardRenameTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=Studio(mock=True,storage=self.temp.name);self.p=self.app.productions
        self.addCleanup(self.p.sql.close);self.s=self.app.filmmaking.series;self.w=self.app.filmmaking.workshop
        outline=self.p.dispatch('POST',[],dict(kind='story',title='Rename fixture'))[1]
        self.pid=outline['production']['id'];self.eid=outline['episodes'][0]['id']
        guide={key:[dict(id='same-id',name='Original')] for key in ('cast','places','props')}
        guide['cast'].append(dict(id='unrelated',name='Original'))
        self.bible=self.s.save_bible(self.pid,dict(expected_revision=0,guide=guide))
        self.snapshot=self.s.workshop('series-bible',self.pid,dict(expected_revision=self.bible['revision']))

    def rename(self):
        guide=copy.deepcopy(self.bible['guide'])
        for key in ('cast','places','props'):guide[key][0]['name']='New '+key
        return self.app.agent.dispatch('PUT','/agent/v1/filmmaking/series/'+self.pid+'/bible',dict(expected_revision=self.bible['revision'],guide=guide))[1]

    def test_rename_updates_all_categories_and_views_preserving_media_history_and_episode_snapshots(self):
        hero=self.snapshot['entities'][0]
        asset=self.app.upload(dict(name='identity.png',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))
        self.w.upload_identity(hero['id'],dict(expected_revision=hero['revision'],asset_id=asset['id']))
        hero=self.w.entity(hero['id']);ref=self.app.asset_studio.get(hero['reference_id'])
        extra=self.w.add_views(hero['id'],dict(expected_revision=hero['revision'],views=[dict(label='Weekend outfit',details='Blue coat')]))[0]
        book=self.s.save_book(self.eid,dict(expected_revision=0,selected_asset_ids=[hero['id']]))
        drafts=copy.deepcopy(self.app.images.db);stories=copy.deepcopy(self.app.stories.db)
        old_versions=list(self.p.sql.execute('SELECT revision,body FROM versions WHERE id=?',(ref['id'],)))
        saved=self.rename()
        for entity in self.snapshot['entities']:
            fresh=self.w.entity(entity['id'])
            expected='Original' if entity['source_card_id']=='unrelated' else {'Character':'New cast','Location':'New places','Prop':'New props'}[entity['category']]
            self.assertEqual(fresh['name'],expected);self.assertEqual(fresh['profile']['name'],expected)
            for view in self.p.all('world-asset'):
                if view.get('entity_id')==entity['id']:self.assertEqual(view['name'],expected)
            if entity['source_card_id']=='unrelated':self.assertEqual(fresh,entity)
        updated=self.app.asset_studio.get(ref['id'])
        self.assertEqual(updated['title'],'New cast');self.assertEqual(updated['handle'],ref['handle'])
        self.assertEqual(updated['images'],ref['images']);self.assertEqual(self.w.entity(hero['id'])['identity_asset_id'],asset['id'])
        self.assertEqual(self.p.get(extra['id'],'world-asset')['view'],'Weekend outfit')
        for revision,body in old_versions:
            self.assertEqual(self.p.sql.execute('SELECT body FROM versions WHERE id=? AND revision=?',(ref['id'],revision)).fetchone()[0],body)
        self.assertEqual(self.app.images.db,drafts);self.assertEqual(self.app.stories.db,stories)
        self.assertEqual(self.s.book(self.eid)['inheritance'],book['inheritance'])
        with self.assertRaises(APIError):self.rename()
        self.assertEqual(self.s.bible(self.pid)['revision'],saved['revision'])
        reopened=Studio(mock=True,storage=self.temp.name)
        try:self.assertEqual(reopened.productions.get(hero['id'],'world-entity')['name'],'New cast')
        finally:reopened.productions.sql.close()

    def test_episode_rename_does_not_cross_book_or_production_boundaries(self):
        episode=self.s.save_book(self.eid,dict(expected_revision=0,guide=dict(cast=[dict(id='same-id',name='Original')])))
        workshop=self.s.workshop('episode-book',self.eid,dict(expected_revision=episode['revision']))
        entity=workshop['entities'][0]
        other=self.p.dispatch('POST',[],dict(kind='story',title='Other series'))[1]['production']['id']
        bible=self.s.save_bible(other,dict(expected_revision=0,guide=dict(cast=[dict(id='same-id',name='Original')])))
        other_entity=self.s.workshop('series-bible',other,dict(expected_revision=bible['revision']))['entities'][0]
        self.rename()
        self.assertEqual(self.w.entity(entity['id']),entity);self.assertEqual(self.w.entity(other_entity['id']),other_entity)
        guide=copy.deepcopy(episode['guide']);guide['cast'][0]['name']='Episode hero'
        self.s.save_book(self.eid,dict(expected_revision=episode['revision'],guide=guide))
        self.assertEqual(self.w.entity(entity['id'])['name'],'Episode hero')
        self.assertEqual(self.w.entity(self.snapshot['entities'][0]['id'])['name'],'New cast')

    def test_independent_name_survives_save_and_workshop_reopen(self):
        hero=self.snapshot['entities'][0];hero.update(name='Independent');hero['profile']['name']='Independent'
        with self.p.sql:self.p.put('world-entity',hero)
        saved=self.rename();self.s.workshop('series-bible',self.pid,dict(expected_revision=saved['revision']))
        self.assertEqual(self.w.entity(hero['id'])['name'],'Independent')
        self.assertEqual(self.w.entity(hero['id'])['profile']['name'],'Independent')

    def test_reopening_repairs_legacy_sheet_labels_even_when_selected(self):
        view=self.p.get(self.snapshot['views'][0]['id'],'world-asset')
        asset=self.app.upload(dict(name='selected.png',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))
        view.update(name='Stale sheet label',selected_asset_id=asset['id'])
        with self.p.sql:self.p.put('world-asset',view)
        drafts=copy.deepcopy(self.app.images.db)
        self.s.workshop('series-bible',self.pid,dict(expected_revision=self.bible['revision']))
        fresh=self.p.get(view['id'],'world-asset')
        self.assertEqual(fresh['name'],'Original');self.assertEqual(fresh['selected_asset_id'],asset['id'])
        self.assertEqual(self.app.images.db,drafts)

    def test_failed_sheet_write_rolls_back_book_and_linked_records(self):
        hero=self.snapshot['entities'][0]
        asset=self.app.upload(dict(name='identity.png',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))
        self.w.upload_identity(hero['id'],dict(expected_revision=hero['revision'],asset_id=asset['id']))
        before=list(self.p.sql.execute('SELECT * FROM records'));references=copy.deepcopy(self.app.references)
        put=self.p.put
        def fail(kind,record):
            if kind=='world-asset' and record['category']=='Location':raise RuntimeError('Simulated sheet write failure')
            return put(kind,record)
        with patch.object(self.p,'put',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'Simulated'):self.rename()
        self.assertEqual(list(self.p.sql.execute('SELECT * FROM records')),before)
        self.assertEqual(self.app.references,references)
