"""Read routing predicates from dispatchers, without executing services or providers.

This deliberately derives routes from source, rather than keeping a second route
list. Unsupported routing expressions fail loudly so a new syntax cannot hide drift.
"""
import ast
import itertools
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
METHODS=('GET','POST','PUT','PATCH','DELETE')
DISPATCHERS={
    'agent_api.py':('', '_dispatch'), 'production_studio.py':('productions','dispatch'),
    'editing_studio.py':('editing','dispatch'), 'filmmaking_studio.py':('filmmaking','dispatch'),
    'series_builder.py':('filmmaking','dispatch'), 'world_workshop.py':('filmmaking','dispatch'),
    'creative_studio.py':('creative','dispatch'), 'asset_studio.py':('asset-studio','dispatch'),
    'precision_studio.py':('precision','dispatch'), 'story_studio.py':('stories','dispatch'),
    'image_studio.py':('image-studio','dispatch'),
    'opening_frame.py':('filmmaking','dispatch'), 'video_direction.py':('filmmaking','dispatch'), 'workspace_accounts.py':('studio-account','dispatch'),
    'media_prompting.py':('prompting','dispatch'),
    'browser_handoff.py':('handoff','dispatch'),
    'browser_controls.py':('handoff','dispatch'),
    'document_exports.py':('documents','dispatch'),
    'video_review.py':('video-review','dispatch'),
    'song_performance.py':('song-performance','dispatch'),
}

def route_expr(node, aliases):
    if isinstance(node,ast.Name):
        if node.id in ('parts','method'):return node
        return aliases.get(node.id)
    if isinstance(node,ast.Constant):return node
    if isinstance(node,(ast.List,ast.Tuple)):
        values=[route_expr(v,aliases) for v in node.elts]
        return type(node)(elts=values,ctx=ast.Load()) if all(v is not None for v in values) else None
    if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name) and node.value.id=='parts':return node
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='len' and len(node.args)==1 and isinstance(node.args[0],ast.Name) and node.args[0].id=='parts':return node
    if isinstance(node,ast.Compare):
        left=route_expr(node.left,aliases);values=[route_expr(v,aliases) for v in node.comparators]
        if left is None or any(v is None for v in values):return None
        if not any(isinstance(n,ast.Name) and n.id in ('parts','method') for n in ast.walk(left)):return None
        return ast.Compare(left=left,ops=node.ops,comparators=values)
    if isinstance(node,ast.BoolOp):
        values=[v for item in node.values if (v:=route_expr(item,aliases)) is not None]
        if not values:return None
        return ast.BoolOp(op=node.op,values=values) if len(values)>1 else values[0]
    if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.Not):
        value=route_expr(node.operand,aliases)
        return ast.UnaryOp(op=ast.Not(),operand=value) if value is not None else None
    return None

def literal(value):
    try:return ast.literal_eval(value)
    except (ValueError,TypeError):return None

def choices(conditions):
    """Fixed literal slots are distinct from unconstrained resource IDs."""
    slots={};lengths=set();largest=-1
    for condition in conditions:
        for n in ast.walk(condition):
            if isinstance(n,ast.Subscript) and isinstance(n.slice,ast.Constant) and isinstance(n.slice.value,int):largest=max(largest,n.slice.value)
            if not isinstance(n,ast.Compare) or len(n.ops)!=1:continue
            left=n.left;right=literal(n.comparators[0]);op=n.ops[0]
            if isinstance(left,ast.Call) and isinstance(right,int):lengths.add(right)
            if isinstance(left,ast.Name) and left.id=='parts' and isinstance(op,ast.Eq) and isinstance(right,(list,tuple)):
                lengths.add(len(right))
                for i,v in enumerate(right):slots.setdefault(i,set()).add(v)
            if isinstance(left,ast.Subscript) and isinstance(left.value,ast.Name) and left.value.id=='parts':
                if isinstance(left.slice,ast.Constant) and isinstance(left.slice.value,int):
                    if isinstance(op,ast.Eq) and isinstance(right,str):slots.setdefault(left.slice.value,set()).add(right)
                    if isinstance(op,ast.In) and isinstance(right,(list,tuple)) and all(isinstance(v,str) for v in right):slots.setdefault(left.slice.value,set()).update(right)
                elif isinstance(left.slice,ast.Slice) and isinstance(op,ast.Eq) and isinstance(right,(list,tuple)):
                    start=literal(left.slice.lower) or 0
                    for i,v in enumerate(right,start):slots.setdefault(i,set()).add(v)
                    if left.slice.upper is None:lengths.add(start+len(right))
    # Enumerating a few extra lengths catches unconstrained trailing segments too.
    maximum=max([largest+1,*lengths,0])+1
    return slots,range(maximum+1)

def extract(source,prefix,function):
    tree=ast.parse(source)
    dispatch=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==function)
    aliases={}
    for n in ast.walk(dispatch):
        if isinstance(n,ast.Assign) and isinstance(n.value,ast.Subscript) and isinstance(n.value.value,ast.Name) and n.value.value.id=='parts' and isinstance(n.value.slice,ast.Constant):
            for target in n.targets:
                if isinstance(target,ast.Name):aliases[target.id]=n.value
    leaves=[];visited=set()
    def walk(statements,conditions):
        for node in statements:
            if isinstance(node,ast.If):
                expression=route_expr(node.test,aliases)
                walk(node.body,conditions+([expression] if expression is not None else []))
                walk(node.orelse,conditions+([ast.UnaryOp(op=ast.Not(),operand=expression)] if expression is not None else []))
            elif isinstance(node,(ast.With,ast.Try)):
                walk(node.body,conditions)
            elif isinstance(node,ast.Return):
                visited.add(id(node))
                value=node.value
                def success_response(expression):
                    if isinstance(expression,ast.IfExp):return success_response(expression.body) and success_response(expression.orelse)
                    return isinstance(expression,ast.Tuple) and expression.elts and isinstance(expression.elts[0],ast.Constant) and isinstance(expression.elts[0].value,int) and 200<=expression.elts[0].value<300
                success=success_response(value)
                diagnostic=isinstance(value,ast.Call) and ast.unparse(value.func)=='self.app.diagnostics.start'
                forwarded=isinstance(value,ast.Call) and isinstance(value.func,ast.Attribute) and value.func.attr=='dispatch' and value.args and isinstance(value.args[0],ast.Constant)
                if success or diagnostic or forwarded:leaves.append((conditions,node.lineno))
                elif conditions and not isinstance(value,ast.Name) and not (isinstance(value,ast.Call) and isinstance(value.func,ast.Attribute) and value.func.attr=='dispatch'):
                    raise AssertionError(f'Unsupported dispatcher return at {prefix or "agent_api"}:{node.lineno}')
    walk(dispatch.body,[])
    if any(isinstance(n,ast.Return) and id(n) not in visited for n in ast.walk(dispatch)):
        raise AssertionError(f'Unsupported dispatcher control flow in {prefix or "agent_api"}; update routing parser.')
    routes=set()
    for conditions,line in leaves:
        slots,lengths=choices(conditions)
        expressions=[compile(ast.fix_missing_locations(ast.Expression(c)),'<routing predicate>','eval') for c in conditions]
        found=False
        for length in lengths:
            for parts in itertools.product(*(sorted(slots.get(i,{'audit-resource-id'})) for i in range(length))):
                for method in METHODS:
                    try:matched=all(eval(expr,{'__builtins__':{},'len':len},{'parts':list(parts),'method':method}) for expr in expressions)
                    except IndexError:matched=False
                    if not matched:continue
                    found=True
                    path='/'+('/'.join([prefix] if prefix else []) + ('/' if prefix and parts else '') + '/'.join(v if i in slots else '{id}' for i,v in enumerate(parts))).strip('/')
                    routes.add((method,path))
        if not found:raise AssertionError(f'Cannot inventory route at {prefix or "agent_api"}:{line}; update routing parser.')
    return routes

def dispatcher_routes():
    routes=set()
    for filename,(prefix,function) in DISPATCHERS.items():routes.update(extract((ROOT/filename).read_text(),prefix,function))
    # Adding a delegation in AgentAPI must also make its dispatcher auditable.
    root=ast.parse((ROOT/'agent_api.py').read_text())
    known={prefix for prefix,_ in DISPATCHERS.values()}
    dispatch=next(n for n in ast.walk(root) if isinstance(n,ast.FunctionDef) and n.name=='_dispatch')
    for n in ast.walk(dispatch):
        if isinstance(n,ast.If) and any(isinstance(r,ast.Return) and isinstance(r.value,ast.Call) and isinstance(r.value.func,ast.Attribute) and r.value.func.attr=='dispatch' for r in n.body):
            for comparison in ast.walk(n.test):
                if isinstance(comparison,ast.Compare) and isinstance(comparison.left,ast.Subscript) and ast.unparse(comparison.left)=='parts[0]':
                    namespace=literal(comparison.comparators[0])
                    if namespace not in known:raise AssertionError(f'New dispatcher {namespace!r} needs source inventory coverage.')
    # The account bridge explicitly rejects browser-only identity switching.
    # Read that restriction too, instead of treating forbidden methods as routes.
    tree=ast.parse((ROOT/'studio_server.py').read_text())
    bridge=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='accounts_route')
    for n in ast.walk(bridge):
        if isinstance(n,ast.If) and 'browser_session_required' in ast.unparse(n):
            for comparison in ast.walk(n.test):
                if isinstance(comparison,ast.Compare) and isinstance(comparison.left,ast.Name) and comparison.left.id=='parts' and isinstance(comparison.ops[0],ast.In):
                    for parts in ast.literal_eval(comparison.comparators[0]):routes.discard(('POST','/studio-account/'+'/'.join(parts)))
    return routes
