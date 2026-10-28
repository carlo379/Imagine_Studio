import copy
import re
import unittest
from agent_openapi import specification
from dispatcher_inventory import dispatcher_routes,extract

def contract_routes(spec):
    return {(method.upper(),re.sub(r'\{[^}]+\}', '{id}', path)) for path,ops in spec['paths'].items() for method in ops if method in ('get','post','put','patch','delete')}

class ContractDriftTests(unittest.TestCase):
    def test_camera_saved_revision_binary_response_and_typed_catalog(self):
        spec=specification();paths=spec['paths'];schemas=spec['components']['schemas']
        png=paths['/filmmaking/shots/{id}/reference.png']['post']
        body=png['requestBody']['content']['application/json']['schema']
        self.assertFalse(body['additionalProperties']);self.assertEqual(body['required'],['expected_revision'])
        self.assertEqual(set(body['properties']),{'expected_revision'})
        self.assertIn('staging revision',body['properties']['expected_revision']['description'])
        self.assertIn('image/png',png['responses']['200']['content']);self.assertIn('503',png['responses'])
        self.assertFalse(any(p.get('name')=='Idempotency-Key' for p in png.get('parameters',[])))
        catalog=paths['/filmmaking/presets']['get']['responses']['200']['content']['application/json']['schema']
        self.assertEqual(catalog,{'$ref':'#/components/schemas/CameraPresetCatalog'})
        self.assertEqual(set(schemas['CameraPresetCatalog']['properties']),{'version','defaults','frame_sizes','camera','movements','renderer'})
        staging=paths['/filmmaking/shots/{id}']['put']['requestBody']['content']['application/json']['schema']
        self.assertFalse(staging['additionalProperties']);self.assertEqual(staging['properties']['staging'],{'$ref':'#/components/schemas/ShotStaging'})
        self.assertEqual(schemas['ShotStaging']['properties']['subjects']['maxItems'],4)
        self.assertEqual(schemas['ShotStaging']['properties']['ratio']['enum'],['16:9','9:16','1:1'])
        self.assertIn('updated_at',schemas['ShotDirection']['properties'])

    def test_codex_reconnect_contract_has_no_verification_secrets_or_selectors(self):
        spec=specification();route=spec['paths']['/studio-account/codex']
        self.assertEqual(set(route),{'get','post'})
        body=route['post']['requestBody']['content']['application/json']['schema']
        self.assertFalse(body['additionalProperties']);self.assertEqual(body['maxProperties'],0)
        response=spec['components']['schemas']['CodexReconnectStatus']
        self.assertEqual(set(response['properties']),{'id','status','step','human_action_required','error','requested_at','updated_at'})
        self.assertFalse(response['additionalProperties'])
        auth=spec['components']['schemas']['WorkspaceAccountStatus']['properties']['auth']
        self.assertFalse(auth['additionalProperties']);self.assertEqual(set(auth['properties']),{'id','status','kind'})

    def test_handoff_contract_is_read_only_and_uses_flow_revision(self):
        spec=specification();paths=spec['paths'];schemas=spec['components']['schemas']
        for path,method in (('/handoff','get'),('/handoff/flows','get'),('/handoff/flows/{id}','get'),
                ('/handoff/flows/{id}/request','post'),('/handoff/flows/{id}/finish','post'),
                ('/handoff/drafts','get'),('/handoff/drafts/{id}','get')):
            self.assertIn('schema',paths[path][method]['responses']['200']['content']['application/json'])
            if method=='post':
                body=paths[path][method]['requestBody']['content']['application/json']['schema']
                self.assertFalse(body['additionalProperties']);self.assertEqual(body['required'],['expected_revision'])
                self.assertEqual(set(body['properties']),{'expected_revision'})
                self.assertIn('metadata revision',body['properties']['expected_revision']['description'])
        for path in ('/handoff/drafts','/handoff/drafts/{id}'):
            self.assertEqual(set(paths[path]),{'get'})
        self.assertNotIn('/handoff/drafts/consent',paths);self.assertNotIn('/handoff/drafts/{id}/apply',paths)
        self.assertTrue(schemas['PendingBrowserDraft']['properties']['data']['readOnly'])
        self.assertEqual(schemas['BrowserDraftSnapshot']['properties']['read_only'],{'const':True})
        self.assertNotIn('owner',schemas['BrowserReturnFlow']['properties'])
        self.assertIn('superseded',schemas['BrowserReturnFlow']['properties']['status']['enum'])

    def test_dispatchers_and_openapi_match_both_directions(self):
        actual=dispatcher_routes();published=contract_routes(specification())
        self.assertEqual(actual-published,set(),'Working dispatcher routes missing from OpenAPI')
        self.assertEqual(published-actual,set(),'OpenAPI routes without a dispatcher')

    def test_inventory_detects_an_added_dispatcher_route(self):
        source="""def dispatch(self,method,parts,data,key):
    if parts==['new-action'] and method=='POST':return 200, self.new_action(data)
"""
        self.assertEqual(extract(source,'sample','dispatch'),{('POST','/sample/new-action')})

    def test_inventory_covers_conditional_responses_and_forwarded_actions(self):
        source="""def dispatch(self,method,parts,data,key):
    if len(parts)==3 and parts[0]=='exports' and parts[2] in ('download','manifest') and method=='GET':
        manifest=parts[2]=='manifest'
        return (200, {}) if manifest else (200, (b'', 'video/mp4'))
    if len(parts)==2 and parts[1]=='episodes' and method=='POST':
        return self.app.stories.dispatch('POST', ['episodes'], data, None)
"""
        self.assertEqual(extract(source,'sample','dispatch'),{
            ('GET','/sample/exports/{id}/download'),('GET','/sample/exports/{id}/manifest'),
            ('POST','/sample/{id}/episodes')})

    def test_inventory_detects_deleted_and_phantom_contracts(self):
        spec=copy.deepcopy(specification());actual=dispatcher_routes()
        del spec['paths']['/account/grok-check']
        self.assertIn(('POST','/account/grok-check'),actual-contract_routes(spec))
        spec['paths']['/phantom']={'get':{}}
        self.assertIn(('GET','/phantom'),contract_routes(spec)-actual)

    def test_workshop_contracts_have_response_and_revision_schemas(self):
        paths=specification()['paths']
        for path,method in [('/filmmaking/entities/{id}/workshop','get'),('/filmmaking/entities/{id}/clear-approval','post'),('/filmmaking/assets/{id}','put'),*[(f'/filmmaking/assets/{{id}}/{action}','post') for action in ('clear-approval','return-image','attempts','review')]]:
            op=paths[path][method]
            self.assertIn('schema',op['responses']['200']['content']['application/json'])
            if method!='get':self.assertIn('expected_revision',op['requestBody']['content']['application/json']['schema']['required'])
        review=paths['/filmmaking/assets/{id}/review']['post']['requestBody']['content']['application/json']['schema']
        self.assertIn('expected_review_revision',review['required'])
        for path in ('/filmmaking/worlds/{id}/generate','/image-test'):
            self.assertTrue(any(p['name']=='Idempotency-Key' and p['required'] for p in paths[path]['post']['parameters']))
        for kind in ('series','episodes'):
            self.assertIn('application/pdf',paths[f'/filmmaking/{kind}/{{id}}/book.pdf']['get']['responses']['200']['content'])

if __name__=='__main__':unittest.main()
