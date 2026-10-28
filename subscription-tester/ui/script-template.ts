/** Starts with a scene heading so production notes cannot become an extra scene. */
export const SCRIPT_TEMPLATE = `SCENE 1 — INT. [LOCATION NAME] — DAY

[Describe the opening setting, the characters present, and the visible action. Use the same character and location names as your Series Bible.]

[CHARACTER NAME]
[Write the character's spoken dialogue here.]

[Describe the next action or reaction.]

[OTHER CHARACTER NAME]
[Write the reply here.]

SCENE 2 — EXT. [LOCATION NAME] — DAY

[Describe what changes in this scene and what the audience sees. Keep action separate from spoken dialogue.]

[CHARACTER NAME]
[Write the character's spoken dialogue here.]

[Describe the action that leads into the next scene.]

SCENE 3 — INT. [LOCATION NAME] — NIGHT

[Describe the final scene, its action, and the ending.]

[CHARACTER NAME]
[Write the final spoken dialogue here.]

[Describe the final image or reaction.]
`;

export function downloadScriptTemplate(){
 const url=URL.createObjectURL(new Blob([SCRIPT_TEMPLATE],{type:'text/plain;charset=utf-8'}));
 const link=document.createElement('a');link.href=url;link.download='Imagine Studio - Script Template.txt';link.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
}
