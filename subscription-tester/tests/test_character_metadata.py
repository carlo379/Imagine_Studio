import copy
import unittest
from types import SimpleNamespace

from character_metadata import character_context, library_description, profile_description, video_assets


class CharacterMetadataTests(unittest.TestCase):
    def entity(self, **overrides):
        return dict(id='entity-foundation', reference_id='named-foundation', category='Character',
                    production_id='production', episode_id=None, revision=7,
                    name='SampleHero', profile=dict(description='', personality='Robot biography. ', clothing='Approved hat.'),
                    source_card_snapshot=dict(description='Gold thighs, black lower legs and boots.', clothing='Older outfit.'),
                    **overrides)

    def test_blank_visual_fields_recover_original_without_replacing_refinement_or_mutating(self):
        entity = self.entity()
        before = copy.deepcopy(entity)
        context = character_context(entity)
        self.assertEqual(context['appearance']['description'], 'Gold thighs, black lower legs and boots.')
        self.assertEqual(context['appearance']['clothing'], 'Approved hat.')
        self.assertEqual(context['appearance_provenance']['description'], 'original_source_card')
        self.assertEqual(context['appearance_provenance']['clothing'], 'current_profile')
        self.assertNotIn('personality', context['appearance'])
        self.assertEqual(context['biography']['personality'], entity['profile']['personality'])
        self.assertEqual(entity, before)

    def test_current_appearance_always_wins(self):
        entity = self.entity()
        entity['profile']['description'] = 'Approved newer design.'
        self.assertEqual(character_context(entity)['appearance']['description'], 'Approved newer design.')

    def test_authoring_context_retains_complete_fields_beyond_display_limit(self):
        entity = self.entity()
        entity['profile']['description'] = 'Physical detail. ' * 500 + 'Distinctive feet.'
        entity['profile']['personality'] = 'Biography. ' * 900
        context = character_context(entity)
        self.assertEqual(context['appearance']['description'], entity['profile']['description'])
        self.assertEqual(context['biography']['personality'], entity['profile']['personality'])
        summary = library_description(entity, 1500)
        self.assertLessEqual(len(summary), 1500)
        self.assertIn('Additional complete fields', summary)
        self.assertNotIn('Physical detail', summary)

    def test_display_summary_prioritizes_visuals_and_never_cuts_fields(self):
        profile = dict(personality='Biography. ' * 900, motivation='Another biography. ' * 700,
                       description='Black boots and lower legs.', eyes='White illuminated eyes.')
        summary = profile_description(profile, 1500)
        self.assertLessEqual(len(summary), 1500)
        self.assertIn('Description: Black boots and lower legs.', summary)
        self.assertIn('Eyes: White illuminated eyes.', summary)
        self.assertNotIn('Biography.', summary)
        self.assertIn('Additional complete fields', summary)

    def test_exact_reference_match_scope_and_episode_precedence(self):
        series = self.entity()
        episode = copy.deepcopy(series)
        episode.update(id='episode-entity', episode_id='episode')
        episode['profile']['description'] = 'Episode costume.'
        other = copy.deepcopy(episode)
        other.update(id='wrong-production', production_id='elsewhere', revision=100)
        lookalike = copy.deepcopy(series)
        lookalike.update(id='wrong-reference', reference_id='another-reference', revision=100)
        other_episode = copy.deepcopy(episode)
        other_episode.update(id='other-episode', episode_id='other-episode', revision=100)
        entities = [series, episode, other, lookalike, other_episode]
        app = SimpleNamespace(productions=SimpleNamespace(all=lambda kind: entities))
        scene = dict(named=[dict(id='named-foundation', title='SampleHero', handle='SampleHero2', category='Character', description='Truncated old text.')])
        output = video_assets(app, scene, dict(production_id='production', episode_id='episode'))[0]
        self.assertEqual(output['entity_id'], 'episode-entity')
        self.assertEqual(output['appearance']['description'], 'Episode costume.')
        self.assertEqual(output['handle'], 'SampleHero2')
        self.assertNotIn('description', output)

    def test_legacy_metadata_is_complete_and_explicitly_unstructured(self):
        app = SimpleNamespace(productions=SimpleNamespace(all=lambda kind: []))
        raw = 'Legacy library description. ' * 100
        scene = dict(named=[dict(id='named-foundation', title='SampleHero', handle='SampleHero2', category='Character', description=raw)])
        output = video_assets(app, scene)[0]
        self.assertEqual(output['supporting_metadata'], raw)
        self.assertEqual(output['metadata_kind'], 'unstructured_library_description')

    def test_freeform_entity_metadata_is_not_lost(self):
        entity = dict(category='Character', profile={}, description='A complete freeform appearance.')
        self.assertEqual(library_description(entity), entity['description'])

    def test_image_and_voice_tags_follow_exact_bound_ids_and_current_request_order(self):
        app = SimpleNamespace(productions=SimpleNamespace(all=lambda kind: []))
        scene = dict(first={'id':'first'}, audio=True,
                     refs=[{'id':'other'}, {'id':'side'}, {'id':'front'}],
                     voices=[{'id':'other-voice'}, {'id':'foundation-voice'}],
                     named=[dict(id='named-foundation', title='SampleHero', handle='SampleHero2', category='Character',
                                 refIds=['front','side','missing'], voiceId='foundation-voice')])
        item = video_assets(app, scene)[0]
        self.assertEqual(item['image_tags'], ['<IMAGE_2>', '<IMAGE_3>'])
        self.assertTrue(item['image_backed'])
        self.assertEqual(item['voice_tag'], '<AUDIO_1>')
        scene['refs'].reverse()
        scene['first'] = None
        scene['audio'] = False
        item = video_assets(app, scene)[0]
        self.assertEqual(item['image_tags'], ['<IMAGE_0>', '<IMAGE_1>'])
        self.assertIsNone(item['voice_tag'])
        scene['named'][0]['refIds'] = ['missing']
        item = video_assets(app, scene)[0]
        self.assertFalse(item['image_backed'])
        self.assertEqual(item['image_tags'], [])


if __name__ == '__main__':
    unittest.main()
