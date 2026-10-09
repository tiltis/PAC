"""Browser-independent checks for proof matching and path display validation."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_pick_path_ui_requires_matching_preview_and_valid_coordinates():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the UI helper test")
    page = (Path(__file__).resolve().parents[1] / "web/pick_path.html").read_text(encoding="utf-8")
    helpers = page.split("// PAC_PICK_PATH_HELPERS_START", 1)[1].split("// PAC_PICK_PATH_HELPERS_END", 1)[0]
    checks = r"""
const assert = require('node:assert/strict'), H=PacPickPath;
const settings={busy:false,home:{valid:true,tcp_mm:[100,20,140]}},value=H.form('home_descend_forward',5);
const proof={ok:true,preview_id:'verified-id',formKey:H.formKey(value),homeKey:H.homeKey(settings.home)};
assert.equal(H.canApply(settings,value,proof),true);
assert.equal(H.canApply(settings,value,null),false);
assert.equal(H.canApply(settings,value,{...proof,preview_id:''}),false);
assert.equal(H.canApply({...settings,busy:true},value,proof),false);
assert.equal(H.canApply({...settings,home:{valid:false}},value,proof),false);
assert.equal(H.canApply(settings,H.form('home_descend_forward',6),proof),false);
assert.equal(H.canApply({...settings,home:{valid:true,tcp_mm:[100,20,150]}},value,proof),false);
assert.equal(H.canApply({...settings,home:{valid:false}},H.form('legacy',0),null),true);
for(const height of [NaN,Infinity,-11,31,'']) assert.equal(H.form('home_descend_forward',height),null);
assert.equal(H.form('unexpected',0),null);
assert.deepEqual(H.form('home_descend_forward','-10'),{mode:'home_descend_forward',height_offset_mm:-10});
const points=[[.1,.02,.14],[.1,.02,.08],[.2,.02,.08]];
assert.deepEqual(H.pathPoints({path_xyz_m:points}),points);
assert.deepEqual(H.pathPoints({path_xyz_m:{home:points[0],descend:[points[1]],forward:[points[2]]}}),points);
for(const invalid of [null,[],[[0,0,0]],[[0,0,0],[NaN,0,1]],[[0,0,0],[1,2]],[[0,0,0],['1',0,0]]])
  assert.deepEqual(H.pathPoints({path_xyz_m:invalid}),[]);
console.log('UI proof/height/path checks passed');
"""
    result = subprocess.run([node, "-e", helpers + checks], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "checks passed" in result.stdout


def test_preview_does_not_claim_settings_applied_and_edits_discard_proof():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the UI interaction test")
    page = (Path(__file__).resolve().parents[1] / "web/pick_path.html").read_text(encoding="utf-8")
    script = page.split("<script>", 1)[1].split("</script>", 1)[0]
    harness = r"""
const assert = require('node:assert/strict');
const elements=new Map(), calls=[];
function element(){return {value:'',textContent:'',disabled:false,hidden:false,events:{},
  addEventListener(name,fn){this.events[name]=fn},replaceChildren(){},setAttribute(){},append(){}};}
globalThis.document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},createElementNS:element};
globalThis.confirm=()=>false;
const installedHome={valid:true,tcp_mm:[100,20,140],reason:null};
let installed={mode:'legacy',height_offset_mm:0,home:installedHome,busy:false};
globalThis.fetch=async(url,options)=>{
  calls.push([url,options.method]);
  let value=installed;
  if(url.endsWith('/preview'))value={ok:true,preview_id:'proof',home:installedHome};
  if(options.method==='PUT')installed=value={...installed,...JSON.parse(options.body)};
  return {ok:true,json:async()=>value};
};
"""
    checks = r"""
(async()=>{
  await new Promise(setImmediate);
  const at=id=>elements.get(id), originalLabel=at('activeMode').textContent;
  at('mode').value='home_descend_forward';at('mode').events.input();
  assert.equal(at('apply').disabled,true);
  await at('preview').events.click();
  assert.equal(at('apply').disabled,false);
  assert.equal(at('activeMode').textContent,originalLabel);
  assert.equal(calls.filter(c=>c[1]==='PUT').length,0);
  at('height').value='4';at('height').events.input();
  assert.equal(at('apply').disabled,true);
  await at('preview').events.click();await at('apply').events.click();
  assert.equal(calls.filter(c=>c[1]==='PUT').length,1);
  assert.notEqual(at('activeMode').textContent,originalLabel);
  const before=calls.length;await at('saveHome').events.click();
  assert.equal(calls.length,before);
  assert.equal(calls.some(c=>c[0].includes('/api/start') || c[0].includes('/api/run')),false);
  console.log('UI interaction checks passed');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run([node], input=harness + script + checks, text=True,
                            encoding="utf-8", capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "interaction checks passed" in result.stdout
