'use strict';
const $ = id => document.getElementById(id);
let current = null, signature = '', requestVersion = 0, playingRange = null;
const video = $('source-video'), companion = $('source-audio');
companion.volume = Number($('review-volume').value);
$('review-volume').addEventListener('input', () => { companion.volume = Number($('review-volume').value); });
function node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; }
function time(seconds) { const ticks = Math.round(Math.max(0, Number(seconds) || 0)*10), m = Math.floor(ticks/600), s = Math.floor(ticks/10)%60; return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}${ticks%10 ? '.'+ticks%10 : ''}`; }
function range(a, b) { return `${time(a)} - ${time(b)}`; }
function media(path) { return '/media/' + path.split('/').map(encodeURIComponent).join('/'); }
function message(text, error = false) { $('message').textContent = text; $('message').hidden = !text; $('message').classList.toggle('error', error); }
async function post(path, data) {
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json','X-Local-Trial':'1'}, body:JSON.stringify(data)});
  const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Local request failed'); return result;
}
function button(text, action, disabled = false) { const el = node('button', text); el.type = 'button'; el.disabled = disabled; el.addEventListener('click', action); return el; }
function list(values) { const ul = node('ul'); for (const value of values) ul.append(node('li', value)); return ul; }
function activeTrack() { return current?.report.audio_track ?? Number($('track').value); }
function audioPath(track) { return media(`DERIVED_sample_source_02m00s-08m00s_audio${track + 1}_mono16k.mp3`); }
function configureAudio() {
  const url = audioPath(activeTrack());
  if ($('track-preview').getAttribute('src') !== url) $('track-preview').src = url;
  if (companion.getAttribute('src') !== url) { companion.pause(); companion.src = url; }
  $('audio-status').textContent = `Source video stays muted. Source audio ${activeTrack()+1} from the prepared sample synchronizes during playback. Track role ${current?.report.audio_role_verified ? 'checked by you' : 'unverified'}.`;
}
function syncAudio(play = false) {
  if (!current || current.report.mode !== 'real') return;
  const offset = video.currentTime - 120;
  if (offset < 0 || offset >= 360) { companion.pause(); return; }
  try { if (Math.abs(companion.currentTime - offset) > 0.35) companion.currentTime = offset; } catch (_) { /* metadata is pending */ }
  companion.playbackRate = video.playbackRate;
  if (play && !video.paused) companion.play().catch(() => message('Audio playback was blocked. Pause and press Play again, or use the audio preview below.', true));
}
function seekSource(start, end) {
  if (!current || current.report.mode !== 'real') return;
  $('track-preview').pause(); video.pause(); companion.pause();
  playingRange = {start, end}; $('play-range').textContent = `Review context ${range(start,end)}. Playback pauses at the end unless loop is checked.`;
  $('source-empty').hidden = true; configureAudio();
  const seek = () => { video.currentTime = start; $('clock').textContent = time(start); syncAudio(); };
  if (!video.getAttribute('src')) { video.addEventListener('loadedmetadata', seek, {once:true}); video.src = '/source-video'; video.load(); }
  else if (video.readyState >= 1) seek();
  else video.addEventListener('loadedmetadata', seek, {once:true});
}
video.addEventListener('playing', () => { video.muted = true; $('track-preview').pause(); syncAudio(true); });
for (const event of ['pause','waiting','seeking','ended']) video.addEventListener(event, () => companion.pause());
video.addEventListener('seeked', () => syncAudio(!video.paused));
video.addEventListener('ratechange', () => syncAudio());
video.addEventListener('volumechange', () => { if (!video.muted) video.muted = true; });
video.addEventListener('error', () => message('The browser could not decode or seek the original. The source is unchanged; review the local file in your usual player.', true));
video.addEventListener('timeupdate', () => {
  $('clock').textContent = time(video.currentTime); syncAudio();
  if (playingRange && !video.paused && video.currentTime >= playingRange.end) {
    video.pause();
    if ($('loop-context').checked) { video.currentTime = playingRange.start; video.play().catch(() => {}); }
  }
});
$('track-preview').addEventListener('play', () => { video.pause(); companion.pause(); });
function frameView(frame, disabled) {
  if (frame.available === false) { const placeholder = node('figure'); placeholder.append(node('div', 'Prepare the recording to see this still.', 'empty'), node('figcaption', time(frame.timestamp))); return placeholder; }
  const wrap = node('figure'), image = node('img'); image.src = media(frame.path); image.alt = `${frame.tier} frame at ${time(frame.timestamp)}`; image.loading = 'lazy'; image.width = frame.width; image.height = frame.height;
  const target = button('', () => seekSource(frame.timestamp, Math.min(current.report.window.end, frame.timestamp + 30)), disabled); target.className = 'frame-button'; target.setAttribute('aria-label', `Review source at ${time(frame.timestamp)}`); target.append(image);
  wrap.append(target, node('figcaption', `${frame.id} / ${time(frame.timestamp)} / ${frame.tier}`)); return wrap;
}
function candidateCard(candidate, report) {
  const fixture = report.mode === 'fixture', editable = !fixture && report.status === 'complete';
  const saved = report.review_decisions[candidate.id];
  const card = node('article', undefined, 'candidate');
  card.append(node('span', `${candidate.kind} / ${candidate.confidence} confidence / ${range(candidate.start,candidate.end)}`, 'eyebrow'), node('h3', candidate.title), node('p', candidate.rationale));
  for (const label of ['setup','change','payoff']) { const p = node('p'); p.append(node('strong', label[0].toUpperCase()+label.slice(1)+': '), document.createTextNode(candidate[label])); card.append(p); }
  card.append(node('h4', 'Supporting evidence'));
  const evidence = node('ul');
  for (const e of candidate.evidence) evidence.append(node('li', e.kind === 'transcript' ? `${e.ref}, ${range(e.start,e.end)} (chunk): "${e.quote}"` : `${e.ref}, ${time(e.timestamp)}: ${e.observation}`));
  card.append(evidence, node('h4', 'What remains uncertain'), list(candidate.uncertainty));
  card.append(button('Review with surrounding context', () => seekSource(candidate.context.start,candidate.context.end), fixture));
  const dense = report.frames.filter(f => f.tier === 'dense' && f.timestamp >= candidate.context.start && f.timestamp < candidate.context.end);
  if (dense.length) { const details = node('details'), grid = node('div', undefined, 'dense-grid'); details.append(node('summary', `${dense.length} denser context stills (timestamps below; gaps may miss action)`)); dense.forEach(f => grid.append(frameView(f,fixture))); details.append(grid); card.append(details); }
  const form = node('form', undefined, 'review-form'), fields = node('div', undefined, 'boundary-grid');
  const inputs = {};
  for (const name of ['start','end']) {
    const wrap = node('label', `${name === 'start' ? 'In' : 'Out'} (source seconds)`), input = node('input'); input.type = 'number'; input.step = '0.1'; input.min = candidate.context.start; input.max = candidate.context.end; input.value = saved?.[name] ?? candidate[name]; input.required = true; input.disabled = !editable; inputs[name] = input; wrap.append(input);
    wrap.append(button(`Use playhead for ${name === 'start' ? 'in' : 'out'}`, () => { input.value = (Math.round(video.currentTime*10)/10).toFixed(1); }, !editable)); fields.append(wrap);
  }
  form.append(fields, node('p', `Adjust only within inspected context ${range(candidate.context.start,candidate.context.end)}.`, 'muted'));
  const reviewedLabel = node('label', undefined, 'check'), reviewed = node('input'); reviewed.type = 'checkbox'; reviewed.checked = saved?.source_reviewed || false; reviewed.disabled = !editable; reviewedLabel.append(reviewed, document.createTextNode(' I watched this source range with the selected audio and checked its boundaries.')); form.append(reviewedLabel);
  const selectLabel = node('label', 'Decision'), select = node('select');
  for (const value of ['uncertain','keep','reject']) { const option = node('option', value[0].toUpperCase()+value.slice(1)); option.value = value; select.append(option); }
  select.value = saved?.decision || 'uncertain'; select.disabled = !editable; selectLabel.append(select); form.append(selectLabel);
  const noteLabel = node('label', 'Review note'), note = node('textarea'); note.maxLength = 2000; note.rows = 2; note.value = saved?.note || ''; note.disabled = !editable; noteLabel.append(note); form.append(noteLabel);
  const submit = node('button', saved ? 'Save updated decision' : 'Save review decision'); submit.type = 'submit'; submit.disabled = !editable; form.append(submit);
  if (saved) form.append(node('p', `Saved: ${saved.decision} / ${range(saved.start,saved.end)}`, 'saved'));
  form.addEventListener('submit', async event => {
    event.preventDefault(); submit.disabled = true;
    try { await post('/api/review', {mode:'real',run_id:report.run_id,candidate_id:candidate.id,decision:select.value,start:Number(inputs.start.value),end:Number(inputs.end.value),note:note.value,source_reviewed:reviewed.checked}); message('Review decision saved locally. No render started.'); await refresh(true); }
    catch (error) { message(error.message,true); } finally { submit.disabled = !editable; }
  });
  card.append(form); return card;
}
function renderReport(report) {
  const fixture = report.mode === 'fixture';
  $('fixture-banner').hidden = !fixture; $('analysis-panel').hidden = fixture; $('source-video').hidden = fixture;
  $('load-source').disabled = fixture || !current.source_available; $('loop-context').disabled = fixture;
  $('review-volume').disabled = fixture;
  if (fixture) $('audio-status').textContent = 'This synthetic fixture has no real audio.';
  $('source-empty').hidden = !fixture && Boolean(video.getAttribute('src'));
  $('source-empty').textContent = fixture ? 'Fixture diagrams have no real source video. Playback is disabled.' : 'Select a timeline frame or candidate to load the original locally. Press Play when ready.';
  $('scope').textContent = `${fixture ? 'SYNTHETIC TEST WINDOW' : 'REAL SOURCE WINDOW'} ${range(report.window.start,report.window.end)} / ${report.status.replaceAll('_',' ')}`;
  const titles = {pending:'Awaiting real transcript and judgment', candidates:'Moments to review', reject_all:'No worthy moment supported in this window', uncertain:'Not enough evidence to choose a moment'};
  $('verdict-title').textContent = report.status === 'blocked' ? 'Analysis stopped; any proposals below are incomplete' : (titles[report.verdict] || 'Analysis in progress');
  $('rationale').textContent = report.rationale;
  $('uncertainty').replaceChildren(...report.uncertainty.map(t => node('li',t)));
  $('candidate-count').textContent = report.candidates.length;
  $('candidates').replaceChildren(...report.candidates.map(c => candidateCard(c,report)));
  if (!report.candidates.length) $('candidates').append(node('div', report.verdict === 'reject_all' ? 'Reject all. No range is proposed or queued for rendering.' : report.verdict === 'uncertain' ? 'No range selected. More context may be needed.' : 'No real candidates yet. The prepared stills below are context, not editorial judgments.', 'empty'));
  $('selection-link').hidden = fixture || !Object.values(report.review_decisions).some(d => d.decision === 'keep');
  $('timeline').replaceChildren();
  for (const t of report.transcript) {
    const row = node('article', undefined, 'timeline-row');
    const frame = report.frames.find(f => f.tier === 'coarse' && f.timestamp >= t.start && f.timestamp < t.end);
    if (frame) row.append(frameView(frame,fixture));
    const text = node('div'); text.append(button(`${t.id} / ${range(t.start,t.end)}`, () => seekSource(t.start,t.end),fixture), node('p', t.text === null ? 'Transcript pending. No dialogue has been inferred from this image.' : t.text || '[No speech recognized in this chunk; recognition is unverified.]'), node('small', `${t.origin} / ${t.timing_precision}`)); row.append(text); $('timeline').append(row);
  }
  if (!fixture) configureAudio();
}
async function refresh(force = false) {
  const version = ++requestVersion, mode = $('mode').value;
  try {
    const response = await fetch('/api/state?mode=' + encodeURIComponent(mode)); if (!response.ok) throw new Error('Could not load local review state');
    const data = await response.json(); if (version !== requestVersion) return;
    current = data;
    $('budget').textContent = `$${Number(data.budget.counted_usd).toFixed(4)} spent + reserved`;
    $('job').textContent = data.job.error || data.job.stage;
    $('job').classList.toggle('error',Boolean(data.job.error));
    $('key-status').textContent = data.environment_key_present ? 'A process key is available; you may leave this field blank.' : 'No process key detected. Enter an appropriate key locally when ready.';
    $('analyze').disabled = data.job.running || data.report.mode !== 'real' || Boolean(data.report.run_id) || data.budget.uncertain_requests > 0 || !data.source_available || (data.prepared_audio_tracks && !data.prepared_audio_tracks.length);
    $('track').disabled = Boolean(data.report.audio_track !== null);
    if (data.prepared_audio_tracks) {
      for (const option of $('track').options) option.disabled = !data.prepared_audio_tracks.includes(Number(option.value));
      if (data.prepared_audio_tracks.length && !data.prepared_audio_tracks.includes(Number($('track').value))) $('track').value = data.prepared_audio_tracks[0];
    }
    if (data.report.audio_track !== null) {
      $('track').value = data.report.audio_track;
      const url = audioPath(data.report.audio_track);
      if ($('track-preview').getAttribute('src') !== url) $('track-preview').src = url;
    }
    const next = JSON.stringify(data.report);
    if (force || next !== signature) { signature = next; renderReport(data.report); }
    $('outputs').replaceChildren(...data.outputs.map(o => {const a = node('a',o.name); a.href=media(o.path); a.target='_blank'; a.rel='noopener'; return a;}));
  } catch (error) { message(error.message,true); }
}
$('mode').addEventListener('change', () => { video.pause(); companion.pause(); $('track-preview').pause(); video.removeAttribute('src'); video.load(); playingRange=null; $('api-key').value=''; message(''); refresh(true); });
$('refresh').addEventListener('click', () => refresh(true));
$('load-source').addEventListener('click', () => seekSource(120,480));
$('track').addEventListener('change', () => { video.pause(); companion.pause(); $('audio-verified').checked=false; $('track-preview').src=audioPath(Number($('track').value)); configureAudio(); });
$('track-preview').src = audioPath(0);
$('analyze').addEventListener('click', async () => {
  const key = $('api-key').value; $('api-key').value=''; $('analyze').disabled=true; message('');
  try { await post('/api/analyze',{mode:'real',api_key:key,audio_track:Number($('track').value),audio_role_verified:$('audio-verified').checked}); message('Bounded editorial analysis started. No render will start automatically.'); }
  catch (error) { message(error.message,true); } finally { await refresh(true); }
});
refresh(true);
setInterval(() => { if (current?.job.running) refresh(); },2500);
