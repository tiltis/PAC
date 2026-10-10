const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const script = '// 실시간 카메라:' + html.split('// 실시간 카메라:')[1].split("$('resume').onclick")[0];

function camera() {
  const elements = {live:{},liveHint:{hidden:true},liveBtn:{},specimen:{value:'S01'}};
  const timers = new Map(), listeners = {};
  let id = 0;
  const context = vm.createContext({
    $:name=>elements[name], performance:{now:()=>0}, Date,
    setTimeout:(fn,delay)=>{timers.set(++id,{fn,delay});return id},
    clearTimeout:id=>timers.delete(id),
    document:{hidden:false,addEventListener:(name,fn)=>listeners[name]=fn},
    refreshZoneFrame:()=>{},clearZones:()=>{},zoneLastAt:0,
  });
  vm.runInContext(script, context);
  // The page starts the camera after defining the other UI handlers.
  vm.runInContext('liveNext()', context);
  function fire(delay) {
    const timer = [...timers].find(([,t])=>t.delay===delay);
    assert.ok(timer, `expected timer ${delay}`);
    timers.delete(timer[0]);timer[1].fn();
  }
  return {elements,timers,listeners,context,fire};
}

test('camera uses station origin for local and remote clients',()=>{
  const c=camera();
  assert.match(c.elements.live.src,/^\/sensor-live\?boxes=1&specimen_id=S01&/);
  assert.equal(c.timers.size,1);
});

test('a stalled frame retries the raw camera after six seconds',()=>{
  const c=camera();c.fire(6000);c.fire(0);
  assert.match(c.elements.live.src,/^\/sensor-live\?boxes=0&/);
  assert.equal(c.elements.liveHint.hidden,false);
});

test('successful load clears the watchdog and hides connection hint',()=>{
  const c=camera();c.elements.liveHint.hidden=false;c.elements.live.onload();
  assert.equal(c.elements.liveHint.hidden,true);
  assert.equal([...c.timers.values()].some(t=>t.delay===6000),false);
  assert.equal(c.timers.size,1);
});

test('camera error retries raw display rather than another localhost port',()=>{
  const c=camera();c.elements.live.onerror();c.fire(1500);
  assert.match(c.elements.live.src,/^\/sensor-live\?boxes=0&/);
});

test('hiding or stopping the camera cancels the watchdog',()=>{
  const c=camera();c.context.document.hidden=true;c.listeners.visibilitychange();
  assert.equal(c.timers.size,0);
  c.context.document.hidden=false;c.listeners.visibilitychange();
  c.elements.liveBtn.onclick();
  assert.equal(c.timers.size,0);
  assert.equal(c.elements.live.hidden,true);
});
