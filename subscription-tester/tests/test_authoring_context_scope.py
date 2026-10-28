import copy
import json
import unittest
from unittest.mock import Mock
from media_prompting import MediaPrompting

class ContextScopeTests(unittest.TestCase):
    def test_image_preparation_scopes_archives_and_keeps_current_scene_and_instruction(self):
        service=object.__new__(MediaPrompting)
        service.app=Mock()
        service.app.images.expanded_prompt.return_value=('Frame.',[])
        service.app.images.prompt_limit.return_value=10000
        record=dict(id='image',title='The Delivery',settings=dict(model='gpt-image-2',prompt='Original',base=None,bindings=[],extras=[],ratio='auto'))
        deps=dict(shot=dict(title='The Delivery',notes='Family waits outside driveway.',story_scene_id='scene',script_text='Old scene',series_context=dict(bible_revision=198,answers=dict(style='Stylized 3D',rules='Preserve identities'),assets=['archive '*40000])),script=dict(title='Episode',scenes=[dict(id='scene',title='Arrival',text='The family waits for the truck.'),dict(id='other',title='Kitchen',text='unrelated '*1000)]),story_context=dict(scene_id='scene',scene_text='Old scene',scenes=['duplicate '*10000]),book=dict(answers=dict(style='Warm'),guide=dict(script='old script '*20000)))
        self.assertGreater(len(json.dumps(deps)),240000)
        original=copy.deepcopy(deps)
        service.dependencies=lambda kind,r:copy.deepcopy(deps)
        # No guide supplement / provider request for this fixture.
        del service.app.video_learning
        result=service.context('image',record,dict(instruction='Keep the family clear of the driveway.'))
        creative=result['creative_context']
        self.assertEqual(result['user_instruction'],'Keep the family clear of the driveway.')
        self.assertEqual(creative['current_scene']['text'],'The family waits for the truck.')
        self.assertEqual(creative['series_direction']['answers']['rules'],'Preserve identities')
        self.assertEqual(creative['shot']['notes'],'Family waits outside driveway.')
        self.assertLess(len(json.dumps(creative)),20000)
        self.assertEqual(deps,original)
        self.assertEqual(record['settings']['prompt'],'Original')
        self.assertEqual(service.basis('image',record)['dependencies'],original)

    def test_standalone_linked_script_and_workshop_are_retained(self):
        service=object.__new__(MediaPrompting)
        deps=dict(linked_script=[dict(id='one',title='Scene',text='Full text')],workshop=dict(entity=dict(description='Exact approved identity')),style='Warm')
        service.dependencies=lambda *args:copy.deepcopy(deps)
        result=service.authoring_dependencies('image',{})
        self.assertEqual(result,deps)
