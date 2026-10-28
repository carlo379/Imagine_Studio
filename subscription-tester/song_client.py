"""Typed SDK helpers. All calls use the existing authenticated StudioClient transport."""
from typing import Literal, TypedDict, NotRequired

class SongSource(TypedDict):
    kind: Literal['upload','take']
    id: str

class SongCue(TypedDict):
    kind: Literal['word','phrase','beat','bar','section','vocal_activity','music_activity','instrumental_gap']
    start: float
    end: float
    id: NotRequired[str]
    text: NotRequired[str]
    source: NotRequired[str]
    method: NotRequired[str]
    review_state: NotRequired[Literal['suggested','reviewed','rejected']]

class SongSelection(TypedDict):
    review_id: str
    expected_review_revision: int
    song_start: float
    song_end: float

class SongClient:
    def song_schema(self) -> dict:
        return self.request('song-performance/schema')

    def song_projects(self) -> list[dict]:
        return self.request('song-performance/projects')

    def song_project(self,identity: str) -> dict:
        return self.request('song-performance/projects/'+identity)

    def create_song_project(self,title: str,production_id: str,master: SongSource,*,episode_id: str|None=None,
                            story_scene_id: str|None=None,lyrics: str='',stems: dict[str,SongSource]|None=None) -> dict:
        return self.request('song-performance/projects','POST',dict(title=title,production_id=production_id,
            episode_id=episode_id,story_scene_id=story_scene_id,master=master,lyrics=lyrics,stems=stems or {}))

    def edit_song_project(self,project: dict,**changes) -> dict:
        return self.request('song-performance/projects/'+project['id'],'PATCH',dict(expected_revision=project['revision'],**changes))

    def analyze_song(self,project: dict,*,idempotency_key: str) -> dict:
        return self.request('song-performance/projects/'+project['id']+'/analyze','POST',dict(expected_revision=project['revision']),idempotency_key)

    def song_analysis_job(self,identity: str) -> dict:
        return self.request('song-performance/analysis-jobs/'+identity)

    def cancel_song_analysis(self,job: dict) -> dict:
        return self.request('song-performance/analysis-jobs/'+job['id']+'/cancel','POST',dict(expected_revision=job['revision']))

    def apply_song_analysis(self,job: dict,project: dict) -> dict:
        return self.request('song-performance/analysis-jobs/'+job['id']+'/apply','POST',dict(expected_revision=job['revision'],expected_project_revision=project['revision']))

    def song_shots(self,project_id: str) -> list[dict]:
        return self.request('song-performance/projects/'+project_id+'/shots')

    def song_shot(self,identity: str) -> dict:
        return self.request('song-performance/shots/'+identity)

    def create_song_shot(self,project: dict,**shot) -> dict:
        return self.request('song-performance/projects/'+project['id']+'/shots','POST',dict(expected_revision=project['revision'],shot=shot))

    def edit_song_shot(self,shot: dict,project: dict,**changes) -> dict:
        return self.request('song-performance/shots/'+shot['id'],'PATCH',dict(expected_revision=shot['revision'],expected_project_revision=project['revision'],changes=changes))

    def prepare_song_shot(self,shot: dict,project: dict,*,draft: dict|None=None) -> dict:
        return self.request('song-performance/shots/'+shot['id']+'/prepare','POST',dict(expected_revision=shot['revision'],
            expected_project_revision=project['revision'],**(dict(expected_draft_revision=draft['revision']) if draft else {})))

    def apply_song_draft(self,shot: dict,project: dict,preparation: dict) -> dict:
        return self.request('song-performance/shots/'+shot['id']+'/apply-draft','POST',dict(expected_revision=shot['revision'],
            expected_project_revision=project['revision'],preparation=preparation,
            **(dict(expected_draft_revision=preparation['draft_revision']) if preparation['draft_revision'] is not None else {})))

    def song_take_reviews(self,shot_id: str) -> list[dict]:
        return self.request('song-performance/shots/'+shot_id+'/take-reviews')

    def create_song_take_review(self,shot: dict,source: SongSource) -> dict:
        return self.request('song-performance/shots/'+shot['id']+'/take-reviews','POST',dict(expected_revision=shot['revision'],source=source))

    def song_take_review(self,shot_id: str,review_id: str) -> dict:
        return self.request('song-performance/shots/'+shot_id+'/take-reviews/'+review_id)

    def edit_song_take_review(self,review: dict,**changes) -> dict:
        return self.request('song-performance/shots/'+review['song_shot_id']+'/take-reviews/'+review['id'],'PATCH',dict(expected_revision=review['revision'],**changes))

    def compare_song_take(self,shot: dict,review: dict,*,idempotency_key: str,fps: int=24) -> dict:
        return self.request('song-performance/shots/'+shot['id']+'/comparisons','POST',dict(expected_revision=shot['revision'],
            review_id=review['id'],expected_review_revision=review['revision'],fps=fps),idempotency_key)

    def song_comparison(self,identity: str) -> dict:
        return self.request('song-performance/comparisons/'+identity)

    def assemble_song(self,project: dict,selections: list[SongSelection],*,apply: bool=False,fps: int=24,
                      expected_timeline_revision: int|None=None,idempotency_key: str) -> dict:
        return self.request('song-performance/projects/'+project['id']+'/assemble','POST',dict(expected_revision=project['revision'],
            selections=selections,apply=apply,fps=fps,
            **(dict(expected_timeline_revision=expected_timeline_revision) if expected_timeline_revision is not None else {})),idempotency_key)
