const assert=require('node:assert/strict');
const {view}=require('../static/account-flow.js');
assert.equal(view({}).canLogin,true);
for(const auth_status of ['connecting','waiting']){
  const state=view({signed_in:false,auth_status});
  assert.equal(state.pending,true);
  assert.equal(state.canLogin,false);
  assert.equal(state.canContinue,false);
}
const connected=view({signed_in:true,auth_status:'connected',phase:'error'});
assert.equal(connected.title,'Grok sign-in saved');
assert.match(connected.message,/does not verify image generation/);
assert.equal(connected.canContinue,true);
assert.equal(connected.pending,false);
const failed=view({signed_in:false,auth_status:'error',auth_error:'Approval expired.'});
assert.equal(failed.message,'Approval expired.');
assert.equal(failed.canLogin,true);
const offline=view({signed_in:true},true);
assert.equal(offline.canContinue,false);
assert.equal(offline.canLogin,false);
assert.equal(view({signed_in:true,mock:true}).title,'Mock account connected');
