import copy
try:
    import test_workshop_controls as controls
except ImportError:
    from tests import test_workshop_controls as controls
from agent_api import APIError

class OptionalViewTests(controls.WorkshopControlTests):
    def angle(self,category='Location'):
        e,v=self.item(category);a=self.upload();self.w.upload_identity(e['id'],dict(expected_revision=e['revision'],asset_id=a['id']))
        e,v=self.item(category)
        views=self.w.add_views(e['id'],dict(expected_revision=e['revision'],model='gpt-image-2',views=[dict(label='Custom shot',details='Back of the room')]))
        v=self.p.get(views[0]['id'],'world-asset');out=self.generate_candidate(v,'angle-'+category)
        self.w.confirm(v['id'],dict(expected_revision=v['revision'],asset_id=out['id'],approved=True))
        return self.item(category)[0],self.p.get(v['id'],'world-asset'),out

    def test_approved_angle_reject_restore_and_clear_preserve_saved_media(self):
        for category in ('Location','Character','Prop'):
            e,v,out=self.angle(category)
            before=copy.deepcopy((self.app.images.db,self.app.assets,self.app.references,self.app.stories.db))
            from candidate_review import review
            candidate=self.w.view(v)['outputs'][0]
            review(self.w,v['id'],dict(expected_revision=v['revision'],expected_review_revision=candidate['review_revision'],asset_id=out['id'],action='reject',reason='Wrong angle'))
            v=self.p.get(v['id'],'world-asset');self.assertIsNone(v['selected_asset_id']);self.assertEqual(self.w.view(v)['outputs'][0]['review_state'],'rejected')
            self.assertEqual(self.item(category)[0],e)
            self.assertEqual(before,(self.app.images.db,self.app.assets,self.app.references,self.app.stories.db))
            with self.assertRaises(APIError):self.w.confirm(v['id'],dict(expected_revision=v['revision'],asset_id=out['id'],approved=True))
            review(self.w,v['id'],dict(expected_revision=v['revision'],expected_review_revision=self.w.view(v)['outputs'][0]['review_revision'],asset_id=out['id'],action='restore'))
            v=self.p.get(v['id'],'world-asset');self.assertIsNone(v['selected_asset_id'])
            self.w.confirm(v['id'],dict(expected_revision=v['revision'],asset_id=out['id'],approved=True));v=self.p.get(v['id'],'world-asset')
            self.w.clear_view_approval(v['id'],dict(expected_revision=v['revision']))
            self.assertIsNone(self.p.get(v['id'],'world-asset')['selected_asset_id']);self.assertEqual(self.item(category)[0]['identity_asset_id'],e['identity_asset_id'])

    def test_rename_is_explicit_revision_checked_and_does_not_change_direction(self):
        e,v,out=self.angle();draft=copy.deepcopy(self.app.images.draft(v['draft_id']))
        self.app.agent.dispatch('PUT','/agent/v1/filmmaking/assets/'+v['id'],dict(expected_revision=v['revision'],title='Back'),None)
        renamed=self.p.get(v['id'],'world-asset');self.assertEqual(renamed['view'],'Back');self.assertEqual(renamed['selected_asset_id'],out['id']);self.assertEqual(self.app.images.draft(v['draft_id']),draft)
        with self.assertRaises(APIError):self.w.edit_view(v['id'],dict(expected_revision=v['revision'],title='Front'))
        with self.assertRaises(APIError):self.w.edit_view(v['id'],dict(expected_revision=renamed['revision'],title='   '))
