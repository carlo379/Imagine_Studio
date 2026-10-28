"""Persistent file-version cache and bounded, optional media analysis."""
import copy
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading


class MediaInspection:
    def __init__(self, storage):
        self.path=Path(storage)/'cache'/'media-inspection.json'
        self.lock=threading.RLock();self.pending=set();self.revision=0
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='media-inspection')
        try:self.values=json.loads(self.path.read_text())
        except (OSError,ValueError):self.values={}

    def key(self,path):
        stat=path.stat()
        return hashlib.sha256(f'{path}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()

    def get(self,path):
        key=self.key(path)
        with self.lock:return copy.deepcopy(self.values.get(key,{}))

    def put(self,path,values):
        key=self.key(path)
        with self.lock:
            self.values[key]={**self.values.get(key,{}),**values}
            # Old file versions are disposable; keep the cache bounded.
            while len(self.values)>1000:self.values.pop(next(iter(self.values)))
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            temp=self.path.with_suffix('.tmp')
            with temp.open('w') as output:
                os.chmod(temp,0o600);json.dump(self.values,output)
            temp.replace(self.path);self.revision+=1

    def schedule(self,path,work):
        key=self.key(path)
        with self.lock:
            if key in self.pending:return True
            if len(self.pending)>=32:return False
            self.pending.add(key)
        def run():
            try:work()
            finally:
                with self.lock:self.pending.discard(key);self.revision+=1
        try:self.pool.submit(run)
        except RuntimeError:
            with self.lock:self.pending.discard(key)
            return False
        return True
