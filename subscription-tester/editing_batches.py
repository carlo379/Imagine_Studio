"""Bounded, lossless execution of the editor's filter DAG (no provider access).

At most four input files and eight filter outputs per FFmpeg process; one process
at a time. NUT/FFV1 and float PCM preserve frames/samples between stages. This is
an input/graph bound, not an OS RSS reservation. See the scale report for RSS.
"""
import re
import tempfile
from pathlib import Path

BATCH_INPUTS=4
BATCH_NODES=8
LABEL=re.compile(r'\[([^\]]+)\]')


def bounded_export(editor, identity, args, folder, duration, fps):
    split=args.index('-filter_complex');raw=args[:split];nodes=args[split+1].split(';');tail=args[split+2:]
    specs=[];start=0
    for i,word in enumerate(raw):
        if word=='-i':specs.append(raw[start:i+2]);start=i+2
    def parts(node):
        leading=re.match(r'^(?:\[[^\]]+\])*',node).group()
        trailing=re.search(r'(?:\[[^\]]+\])+$',node).group()
        return LABEL.findall(leading),node[len(leading):-len(trailing)],LABEL.findall(trailing)
    # Sum large audio lanes in bounded trees. normalize=0 makes grouping exact
    # apart from float rounding. Keep normalization/limiting on the final node.
    expanded=[];serial=0
    for node in nodes:
        inputs,body,outputs=parts(node)
        if body.startswith('amix='):
            while len(inputs)>BATCH_INPUTS:
                next_inputs=[]
                for at in range(0,len(inputs),BATCH_INPUTS):
                    group=inputs[at:at+BATCH_INPUTS];label=f'batchmix{serial}';serial+=1
                    expanded.append(''.join(f'[{x}]' for x in group)+f'amix=inputs={len(group)}:normalize=0[{label}]');next_inputs.append(label)
                inputs=next_inputs
            body=re.sub(r'^amix=inputs=\d+',f'amix=inputs={len(inputs)}',body)
            node=''.join(f'[{x}]' for x in inputs)+body+''.join(f'[{x}]' for x in outputs)
        expanded.append(node)
    nodes=expanded;finals=[tail[i+1][1:-1] for i,x in enumerate(tail) if x=='-map'];files={};kinds={};count=0;peak=0
    with tempfile.TemporaryDirectory(prefix='batch-',dir=folder) as tmp:
        root=Path(tmp).resolve();stage_count=0
        while nodes:
            batch=[];external=[];produced=set()
            for node in nodes:
                inputs,_,outputs=parts(node);needed=[x for x in inputs if x not in produced and x not in external]
                if batch and (len(set(external+needed))>BATCH_INPUTS or len(batch)>=BATCH_NODES):break
                external+=needed;batch.append(node);produced.update(outputs)
            if len(external)>BATCH_INPUTS:raise ValueError('Editor filter exceeds the four-input batch limit.')
            nodes=nodes[len(batch):];live=set(finals)
            for node in nodes:live.update(parts(node)[0])
            exports=[x for node in batch for x in parts(node)[2] if x in live]
            stage=[];aliases={};prefix=[]
            for i,label in enumerate(external):
                if ':' in label:
                    source,kind=label.split(':');stage+=['-threads','2',*specs[int(source)]];aliases[label]=f'{i}:{kind}'
                else:
                    kind=kinds[label];stage+=['-threads','2','-i',str(files[label])];aliases[label]=f'loaded{i}'
                    # NUT retains sample timestamps; video joins require an
                    # explicit fps/time base on FFmpeg 7 as well as 9.
                    clock=f'settb=AVTB,setpts=PTS-STARTPTS,fps={fps}' if kind=='v' else 'anull'
                    prefix.append(f'[{i}:{kind}]{clock}[loaded{i}]')
            rendered=[]
            for node in batch:
                inputs,body,outputs=parts(node)
                kind=('v' if body.startswith('color=') else 'a') if not inputs else (inputs[0].split(':')[-1] if ':' in inputs[0] else kinds[inputs[0]])
                for label in outputs:kinds[label]=kind
                rendered.append(''.join(f'[{aliases.get(x,x)}]' for x in inputs)+body+''.join(f'[{x}]' for x in outputs))
            stage+=['-filter_complex',';'.join(prefix+rendered)]
            for label in exports:
                path=root/f'{count}.nut';count+=1;files[label]=path
                stage+=['-map',f'[{label}]','-c:v','ffv1','-threads','2','-level','3','-c:a','pcm_f32le','-f','nut',str(path)]
            peak=max(peak,len(external));stage_count+=1;editor.run(identity,stage,folder,0,.9,duration)
            for label,path in list(files.items()):
                if label not in live:path.unlink(missing_ok=True);del files[label]
        final=[]
        for label in finals:final+=['-i',str(files[label])]
        for i,word in enumerate(tail):
            if i and tail[i-1]=='-map':final.append(f'{finals.index(word[1:-1])}:{kinds[word[1:-1]]}')
            else:final.append(word)
        final[-1:-1]=['-threads','2']
        editor.run(identity,final,folder,.9,.1,duration)
        editor.update(identity,batch_input_limit=BATCH_INPUTS,batch_peak_inputs=peak,batch_stages=stage_count,batch_intermediates=count)
