"""Workspace-wide canonical assets, version history and visual development drafts."""
import copy
import json
from agent_api import APIError

class AssetStudio:
    def __init__(self,app):
        self.app=app
        with app.productions.sql:
            for r in app.named_library():
                if not any(a['id']==r['id'] for a in app.productions.all('asset')):
                    app.productions.put('asset',{**r,'revision':r.get('revision',1)})
    def get(self,identity):
        r=next((r for r in self.app.named_library() if r['id']==identity),None)
        if not r:raise APIError('not_found','Asset not found.',404)
        return {**r,'revision':r.get('revision',1)}
    def dispatch(self,method,parts,data,key):
        p=self.app.productions
        if parts==['development','lookup'] and method=='POST':
            link=next((r for r in reversed(p.all('asset-development')) if r['draft_id']==data.get('draft_id')),None)
            return 200,self.get(link['reference_id']) if link else None
        if parts==['schema'] and method=='GET':return 200,dict(categories=['Character','Location','Prop'],max_views=7,versions=True,snapshot_policy='Existing scenes retain their saved asset versions; adoption is explicit.',actions=['create','edit','archive','restore version','develop image','adopt approved image'])
        if not parts:
            if method=='GET':return 200,[{**r,'revision':r.get('revision',1)} for r in self.app.named_library()]
            if method=='POST':return 201,self.app.save_reference(data)
        if len(parts)==1:
            r=self.get(parts[0])
            if method=='GET':return 200,r
            if method=='PUT':
                if data.get('expected_revision')!=r['revision']:raise APIError('revision_conflict','The asset changed. Reload before saving.',409)
                return 200,self.app.save_reference({**r,**data,'id':r['id']})
        if len(parts)==2:
            r=self.get(parts[0]);action=parts[1]
            if action=='versions' and method=='GET':
                return 200,[json.loads(row[0]) for row in p.sql.execute('SELECT body FROM versions WHERE id=? AND owner=? ORDER BY revision DESC',(r['id'],'local-user'))]
            if method=='POST':
                if data.get('expected_revision')!=r['revision']:raise APIError('revision_conflict','The asset changed. Review its latest version.',409)
                if action=='restore':
                    v=next((json.loads(row[0]) for row in p.sql.execute('SELECT body FROM versions WHERE id=? AND revision=? AND owner=?',(r['id'],data.get('revision'),'local-user'))),None)
                    if not v:raise APIError('not_found','Asset version not found.',404)
                    return 200,self.app.save_reference({**v,'expected_revision':r['revision']})
                if action=='archive':return 200,self.app.archive_reference(r['id'],data.get('archived',True))
                if action=='develop':
                    prompt=data.get('prompt') or 'Create a canonical '+r['category'].lower()+' reference for '+r['title']+'. '+r['description']+' Plain uncluttered presentation. Preserve the existing identity when references are supplied.'
                    draft=self.app.images.create({'title':('Asset · '+r['title'])[:120],'settings':{'prompt':prompt},'named_references':[r['handle']] if r['images'] else []})
                    with p.sql:p.new('asset-development',reference_id=r['id'],reference_revision=r['revision'],draft_id=draft['id'])
                    return 201,draft
                if action=='adopt':
                    a,_=self.app.asset(data.get('asset_id'))
                    if a.get('generated') and (not a.get('approved') or a.get('mock')!=self.app.mock):raise APIError('review_required','Review and approve this image in the current mode first.',403)
                    images=copy.deepcopy(r['images']);source={'asset_id':a['id']}
                    if source not in images:
                        if data.get('replace_index') is not None:
                            i=data['replace_index']
                            if type(i) is not int or not 0<=i<len(images):raise APIError('invalid_view','Choose an existing view to replace.')
                            images[i]=source
                        else:images.append(source)
                    return 200,self.app.save_reference({**r,'images':images,'expected_revision':r['revision']})
        raise APIError('not_found','Asset Studio route not found.',404)
