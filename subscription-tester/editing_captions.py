"""Literal SRT interchange. Local transcription is an explicit editor operation."""
import re
import textwrap

CAPTION_STYLE=dict(mode='off',position='bottom',size=48,color='#ffffff',max_chars_per_line=32)

def clock(value):
    ms=round(value*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def to_srt(cues):
    return '\n\n'.join(f'{i}\n{clock(c["start"])} --> {clock(c["end"])}\n'+(f'[{c["speaker"]}] ' if c.get('speaker') else '')+c['text'] for i,c in enumerate(cues,1))+'\n' if cues else ''

def from_srt(value):
    if not isinstance(value,str) or len(value)>2000000:raise ValueError('SRT must be text up to 2 MB.')
    result=[]
    for block in re.split(r'\n\s*\n',value.replace('\r','').strip()):
        if not block:continue
        lines=block.splitlines()
        if lines[0].strip().isdigit():lines=lines[1:]
        match=re.fullmatch(r'(\d{2,}):(\d{2}):(\d{2})[,.](\d{3}) --> (\d{2,}):(\d{2}):(\d{2})[,.](\d{3})',lines[0]) if lines else None
        if not match or len(lines)<2:raise ValueError('Use SRT cue numbers, HH:MM:SS,mmm --> HH:MM:SS,mmm and text.')
        nums=list(map(int,match.groups()))
        if any(nums[i]>=60 for i in (1,2,5,6)):raise ValueError('SRT minutes and seconds must be below 60.')
        at=lambda i:nums[i]*3600+nums[i+1]*60+nums[i+2]+nums[i+3]/1000
        text='\n'.join(lines[1:]);speaker=re.match(r'^\[([^]\n]{1,80})\] ',text)
        cue=dict(id='caption-'+str(len(result)+1),start=at(0),end=at(4),text=text[speaker.end():] if speaker else text)
        if speaker:cue['speaker']=speaker[1]
        result.append(cue)
    return result

def wrapped(cue,style):
    text=(cue.get('speaker','')+': ' if cue.get('speaker') else '')+cue['text']
    return '\n'.join('\n'.join(textwrap.wrap(line,width=style['max_chars_per_line'])) for line in text.splitlines())
