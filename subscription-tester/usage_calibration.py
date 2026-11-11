"""Learn what a Grok video costs from the human's own Settings → Usage readings.

Studio cannot read the Grok subscription balance. While the cost of a resolution is
unknown, the human reads the weekly usage percentage before and after each generation.
Each clean pair becomes a sample of percentage points per second of video; once the
samples for a resolution agree, the pattern is established and readings stop being
required for it. Readings are reported observations, never a balance.
"""
import copy
import statistics
import time

RESOLUTIONS=('480p','720p','1080p')
MIN_SAMPLES=3          # agreeing clean samples that establish a pattern
MAX_SAMPLES=6          # clean samples after which the median is used even if they disagree
AGREEMENT=0.5          # (max rate - min rate) must be within this share of the median rate


def reading(value, field):
    if value is None:return None
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not 0<=value<=100:
        raise ValueError(f'{field} must be a number from 0 to 100 (Grok Settings → Usage).')
    return float(value)


def samples(jobs):
    """Clean before/after samples, oldest first. A pair is discarded when the meter went down
    (a weekly reset) or when another video generation started between the two readings."""
    ordered=sorted(jobs,key=lambda j:j.get('created_at',0))
    rows=[]
    for job in ordered:
        usage=job.get('usage') or {}
        before,after=usage.get('before'),usage.get('after')
        settings=job.get('settings') or {}
        resolution,duration=settings.get('resolution'),settings.get('duration')
        if job.get('mock') or job.get('status')!='done' or before is None or after is None:continue
        if resolution not in RESOLUTIONS or not isinstance(duration,(int,float)) or duration<=0:continue
        reason=None
        if after<before:reason='usage went down (weekly reset?)'
        else:
            start,end=job.get('created_at',0),usage.get('after_at') or time.time()
            def span(other):
                begun=other.get('created_at',0)
                return begun,(other.get('usage') or {}).get('after_at') or begun
            if any(other is not job and span(other)[0]<end and span(other)[1]>start for other in ordered):
                reason='another generation ran between the readings'
        rows.append(dict(job_id=job['id'],resolution=resolution,duration=duration,before=before,after=after,
                         delta=round(after-before,3),percent_per_second=None if reason else round((after-before)/duration,4),
                         clean=reason is None,discarded=reason))
    return rows


def calibration(jobs):
    rows=samples(jobs)
    out={}
    for resolution in RESOLUTIONS:
        clean=[r for r in rows if r['resolution']==resolution and r['clean']]
        rates=[r['percent_per_second'] for r in clean]
        median=statistics.median(rates) if rates else None
        agree=bool(rates) and (max(rates)-min(rates))<=AGREEMENT*median if median else bool(rates) and max(rates)==0
        established=len(rates)>=MAX_SAMPLES or (len(rates)>=MIN_SAMPLES and agree)
        out[resolution]=dict(
            established=established,clean_samples=len(clean),
            discarded_samples=sum(1 for r in rows if r['resolution']==resolution and not r['clean']),
            samples_needed=0 if established else max(MIN_SAMPLES-len(rates),1),
            percent_per_second=None if median is None else round(median,4),
            min_percent_per_second=min(rates) if rates else None,max_percent_per_second=max(rates) if rates else None,
            estimate_percent={str(s):round(median*s,2) for s in (3,5,10,15)} if median is not None else None,
            note=('Below the meter\'s resolution: each take moved Usage by less than one step.' if established and median==0 else
                  'Samples disagree; using the median after %d samples.'%MAX_SAMPLES if established and not agree else None))
    return dict(resolutions=out,samples=copy.deepcopy(rows),
        rule=f'A resolution is established after {MIN_SAMPLES} clean samples whose rates agree within '
             f'{int(AGREEMENT*100)}% of the median, or after {MAX_SAMPLES} clean samples.',
        source='Human-reported Grok Settings → Usage percentages; not a subscription balance.')


def required(jobs, resolution):
    """Whether a new generation at this resolution still needs before/after readings."""
    return resolution in RESOLUTIONS and not calibration(jobs)['resolutions'][resolution]['established']
