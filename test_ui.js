// Pure component tests with an in-memory DOM double. No browser, network or playback.
// These checks do not substitute for the blocked live visual/playback QA.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const path = require('node:path');
const root = __dirname;
const reports = JSON.parse(execFileSync('python', ['-c',
  "import editorial,json; print(json.dumps({'real':editorial.empty_report(), **{k:editorial.fixture_report(k) for k in ('candidates','reject_all','uncertain')}}))"], {cwd:root,encoding:'utf8'}));
class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.attrs={}; this.events={}; this._text=''; this._value=''; this.disabled=false; this.hidden=false; this.paused=true; this.currentTime=0; this.readyState=0; this.playCount=0; this.classList={toggle(){}}; }
  set textContent(value) { this._text=String(value); this.children=[]; }
  get textContent() { return this._text+this.children.map(c=>c.textContent).join(' '); }
  set value(value) { this._value=String(value); }
  get value() { return this._value; }
  set src(value) { this.attrs.src=value; }
  get src() { return this.attrs.src; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children=children; this._text=''; }
  setAttribute(k,v) { this.attrs[k]=v; }
  getAttribute(k) { return this.attrs[k]??null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(k,f) { (this.events[k]??=[]).push(f); }
  async fire(k) { for (const f of this.events[k]??[]) await f({preventDefault(){}}); }
  pause() { this.paused=true; }
  play() { this.paused=false; this.playCount++; return Promise.resolve(); }
  load() {}
}
const html=fs.readFileSync(path.join(root,'index.html'),'utf8'), elements={};
for(const match of html.matchAll(/<([a-z][a-z0-9-]*)\b[^>]*\bid="([^"]+)"[^>]*>/gi)) {
  assert(!elements[match[2]],'duplicate HTML id'); elements[match[2]]=new Element(match[1]);
}
elements.mode.value='real'; elements.track.value='0'; elements['review-volume'].value='0.6';
const requests=[], context=vm.createContext({
  document:{getElementById:id=>{assert(elements[id],`Missing HTML id ${id}`);return elements[id];},
    createElement:tag=>new Element(tag),createTextNode:text=>{const e=new Element('#text');e.textContent=text;return e;}},
  console,setInterval:()=>0,
  fetch:async (url,options)=>{
    requests.push({url,options});
    if(options?.method==='POST') return {ok:false,json:async()=>({error:'Synthetic missing-key response; no network used'})};
    const mode=new URL(url,'http://unit.test').searchParams.get('mode')||'real';
    return {ok:true,json:async()=>({report:JSON.parse(JSON.stringify(reports[mode])),
      budget:{counted_usd:'0',uncertain_requests:0},job:{running:false,stage:'Unit fixture'},
      environment_key_present:false,source_available:true,outputs:[]})};
  }
});
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const walk=el=>[el,...el.children.flatMap(walk)];
let checks=0;
function check(value,reason) { assert(value,reason); checks++; }
(async()=>{
  vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),context);
  await settle();
  check(elements['verdict-title'].textContent.includes('Awaiting real'),'empty real state is honest');
  check(elements.timeline.children.length===12,'twelve real timeline chunks');
  check(elements['source-video'].getAttribute('src')===null,'source not loaded automatically');
  check(elements['source-video'].playCount===0 && elements['source-audio'].playCount===0,'no autoplay');
  elements.mode.value='candidates'; await elements.mode.fire('change'); await settle();
  check(elements['fixture-banner'].hidden===false,'fixture label visible');
  check(elements['analysis-panel'].hidden && elements['load-source'].disabled,'fixture cannot launch analysis or source');
  check(elements.candidates.textContent.includes('circular trip'),'synthetic candidate rendered');
  check(walk(elements.candidates).filter(e=>e.tag==='button').every(e=>e.disabled),'fixture decisions disabled');
  elements.mode.value='reject_all'; await elements.mode.fire('change'); await settle();
  check(elements['verdict-title'].textContent.includes('No worthy moment'),'reject-all title');
  check(elements.candidates.textContent.includes('No range is proposed'),'reject-all has no queued cut');
  elements.mode.value='uncertain'; await elements.mode.fire('change'); await settle();
  check(elements['verdict-title'].textContent.includes('Not enough evidence'),'uncertainty displayed');
  elements.mode.value='real'; await elements.mode.fire('change'); await settle();
  await elements['load-source'].fire('click'); await elements['source-video'].fire('loadedmetadata');
  check(elements['source-video'].src==='/source-video' && elements['source-video'].currentTime===120,'source load seeks to absolute 02:00');
  check(elements['source-video'].playCount===0,'source load does not start playback');
  elements['api-key'].value=''; await elements.analyze.fire('click'); await settle();
  check(elements['api-key'].value==='','password field cleared on submission');
  check(elements.message.textContent.includes('Synthetic missing-key'),'local failure surfaced');
  check(requests.filter(r=>r.options?.method==='POST').length===1,'only explicitly requested mocked POST');
  check(vm.runInContext('time(12.1)',context)==='00:12.1','decimal playhead formatting');
  fs.writeFileSync(path.join(root,'ui-component-validation.json'),JSON.stringify({checks,passed:true,
    scope:'In-memory DOM unit tests only. No browser, network, API or playback; live visual QA remains blocked.'},null,2));
  console.log(`${checks} UI component checks passed; no browser or network used.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
