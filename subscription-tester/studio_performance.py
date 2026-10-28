"""Small owner-scoped change signals. Never inspect credential files."""
import hashlib
import json


def workspace_status(app):
    def stamp(names):
        result=[]
        for name in names:
            path=app.storage/name
            try:
                s=path.stat();result.append((name,s.st_mtime_ns,s.st_size))
            except FileNotFoundError:result.append((name,None))
        return hashlib.sha256(repr(result).encode()).hexdigest()[:24]
    sql=app.productions.sql
    production=stamp(('productions.sqlite3','productions.sqlite3-wal'))+':'+str(sql.total_changes)
    areas=dict(productions=production,editing=production,
        video=stamp(('scenes.json','history.json','mock-history.json')),
        image=stamp(('image-studio.json','assets.json','references.json')),
        stories=stamp(('stories.json',)))
    with app.lock:
        state=tuple(app.state.get(k) for k in ('phase','job_id','progress','auth_status','signed_in'))
    areas['account']=hashlib.sha256(repr(state).encode()).hexdigest()[:24]
    areas['inspection']=str(getattr(app.editing,'inspection_revision',0))
    return dict(revision=hashlib.sha256(json.dumps(areas,sort_keys=True).encode()).hexdigest(),areas=areas)
