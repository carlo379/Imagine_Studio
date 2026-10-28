// Dropdown menus are transient; ordinary details/accordion sections stay open.
export function installMenuDismissal(doc:Document){
 const selector='details.p-shot-menu, .library-card-actions > details, details[data-dismiss-menu]';
 const menus=()=>Array.from(doc.querySelectorAll<HTMLDetailsElement>(selector));
 const dismissOutside=(event:Event)=>{if(!(event.target instanceof doc.defaultView!.Node))return;for(const menu of menus())if(menu.open&&!menu.contains(event.target))menu.open=false;};
 const click=(event:MouseEvent)=>{
  dismissOutside(event);
  const target=event.target as Element|null;
  const menu=target?.closest<HTMLDetailsElement>(selector);
  if(menu&&target?.closest('button,a')&&!target.closest('summary'))menu.open=false;
 };
 const toggle=(event:Event)=>{const menu=event.target as HTMLDetailsElement;if(menu.matches?.(selector)&&menu.open)for(const other of menus())if(other!==menu)other.open=false;};
 const key=(event:KeyboardEvent)=>{if(event.key!=='Escape')return;const open=menus().filter(menu=>menu.open);if(!open.length)return;event.preventDefault();event.stopImmediatePropagation();for(const menu of open)menu.open=false;open.at(-1)?.querySelector<HTMLElement>('summary')?.focus();};
 const focus=(event:FocusEvent)=>dismissOutside(event);
 doc.addEventListener('pointerdown',dismissOutside,true);
 doc.addEventListener('click',click);
 doc.addEventListener('toggle',toggle,true);
 doc.addEventListener('keydown',key,true);
 doc.addEventListener('focusin',focus);
 return ()=>{doc.removeEventListener('pointerdown',dismissOutside,true);doc.removeEventListener('click',click);doc.removeEventListener('toggle',toggle,true);doc.removeEventListener('keydown',key,true);doc.removeEventListener('focusin',focus);};
}
