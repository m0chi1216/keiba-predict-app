const $ = id => document.getElementById(id);
let mode = 'id', races = [], busy = false;
const dateParts = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
$('race-date').value = ['year','month','day'].map(key => dateParts.find(p => p.type === key).value).join('-');
function setMode(next) {
  mode = next;
  $('id-mode').hidden = next !== 'id'; $('list-mode').hidden = next !== 'list';
  for (const key of ['id','list']) { $(key+'-tab').classList.toggle('active',key===next); $(key+'-tab').setAttribute('aria-pressed',String(key===next)); }
}
$('id-tab').onclick = () => setMode('id'); $('list-tab').onclick = () => setMode('list');
function setBusy(value) {
  busy = value;
  document.querySelectorAll('aside button,aside input').forEach(el => el.disabled = value);
  $('track').disabled = value || !races.length; $('race-select').disabled = value || !races.length;
}
function node(tag, text, className) { const el = document.createElement(tag); if(text!==undefined) el.textContent = text; if(className) el.className=className; return el; }
function notify(message) { $('notice').textContent = message; }
const fmt = (value, digits=2) => value == null ? '—' : Number(value).toLocaleString('ja-JP',{minimumFractionDigits:digits,maximumFractionDigits:digits});
const stamp = value => new Date(value).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'});
async function api(url, options) {
  const response = await fetch(url, options); const result = await response.json();
  if(!response.ok) { const error=new Error(result.error || '通信エラー'); error.status=response.status; throw error; } return result;
}
async function job(request, existing=null) {
  if(busy) return;
  notify(''); setBusy(true); $('progress').hidden=false; $('logs').textContent='処理を開始しています…';
  if(request.action==='predict') { $('results').hidden=true; $('empty').hidden=true; }
  $('progress-label').textContent=request.action==='races'?'開催レースを取得中':'データ作成・AI予測を実行中';
  try {
    const created = existing || await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
    let snapshot=existing;
    while(true) {
      let current;
      try {
        current = snapshot || await api('/api/jobs/'+created.id);
        snapshot=null; notify('');
      } catch(error) {
        if(error.status && error.status<500) throw error;
        notify('接続を確認しています。サーバー側の処理は続いています。');
        await new Promise(resolve => setTimeout(resolve,3000));
        continue;
      }
      $('logs').textContent=current.logs || '処理を開始しています…';
      $('logs').scrollTop=$('logs').scrollHeight;
      if(current.status==='error') throw new Error(current.error);
      if(current.status==='done') { $('progress').hidden=true; return current.result; }
      await new Promise(resolve => setTimeout(resolve,1500));
    }
  } catch(error) { notify(error.message); }
  finally { setBusy(false); $('progress-label').textContent='処理ログ'; $('results').hidden=false; }
}
function populateRaces() {
  const selected = races.filter(race=>race.track===$('track').value);
  $('race-select').replaceChildren(...selected.map(race => {const option=node('option',`${race.number}R  ${race.name}`);option.value=race.race_id;return option;}));
}
$('track').onchange=populateRaces;
function showRaces(result) {
  races=result.races;
  $('race-date').value=result.date;
  $('track').replaceChildren(...[...new Set(races.map(race=>race.track))].map(track => node('option',track)));
  populateRaces(); $('track').disabled=!races.length; $('race-select').disabled=!races.length;
}
$('load-races').onclick=async()=>{
  const result = await job({action:'races',date:$('race-date').value});
  if(!result) return;
  showRaces(result);
};
$('race-date').onchange=()=>{races=[];$('track').replaceChildren(node('option','開催レースを取得してください'));$('race-select').replaceChildren(node('option','レース未選択'));$('track').disabled=true;$('race-select').disabled=true;};
$('predict').onclick=async()=>{
  const race_id = mode==='id' ? $('race-id').value.trim() : $('race-select').value;
  const strategies=[...document.querySelectorAll('input[name=ai]:checked')].map(el=>el.value);
  if(!/^[0-9]{12}$/.test(race_id)) return notify('半角数字12桁のrace idを入力するか、開催レースを選択してください。');
  if(!strategies.length) return notify('AIを1つ以上選択してください。');
  const result=await job({action:'predict',race_id,strategies,use_saved:$('use-saved').checked});
  if(result) render(result);
};
function render(result) {
  $('empty').hidden=true; $('results').replaceChildren();
  const head=node('div',undefined,'result-head');
  head.append(node('p','PREDICTION RESULT','eyebrow'),node('h2',`${result.track} ${result.number}R`));
  const source=node('a','netkeiba 出馬表 ↗'); source.href='https://race.netkeiba.com/race/shutuba.html?race_id='+result.race_id;source.target='_blank';source.rel='noopener noreferrer';
  const meta=node('p',`race id: ${result.race_id} · 予測 ${stamp(result.created_at)}\nデータ保存 ${stamp(result.input_modified)}${result.use_saved?' · 保存済みデータを使用':''}`);meta.style.whiteSpace='pre-line';head.append(meta,source); $('results').append(head);
  for(const model of result.models) {
    const regression=model.settings.task==='regression', section=node('article',undefined,'panel model-result');
    const heading=node('div',undefined,'model-heading'); heading.append(node('h3',model.label),node('small',model.config));section.append(heading);
    const s=model.settings;
    section.append(node('p',`単勝 · 購入候補 上位${s.top_n}頭 · 購入スコア > ${fmt(s.score_threshold,4)} · 1倍 < オッズ ≤ ${fmt(s.max_odds,0)}倍`,'conditions'));
    const wrap=node('div',undefined,'table-wrap'), table=node('table'),thead=node('thead'),tr=node('tr');
    for(const name of ['馬番','馬名','単勝',regression?'rankスコア':'勝率','購入スコア','購入判定'])tr.append(node('th',name));
    thead.append(tr);table.append(thead);const tbody=node('tbody');
    for(const horse of model.horses) {
      const row=node('tr',undefined,horse.selected?'buy':'');
      const number=node('td');number.append(node('span',String(horse.horse_num??'—'),'horse-number'));row.append(number);
      const name=node('td'); name.append(node('strong',horse.horse_name??'名称未取得'),node('small',horse.rank==null?'購入対象外のレース':`${regression?'予測着順':'勝率順位'} ${fmt(horse.rank,0)}位`));row.append(name);
      row.append(node('td',horse.odds==null?'—':fmt(horse.odds,1)+'倍'),node('td',horse.score==null?'—':fmt(horse.score*100,2)+'%'),node('td',fmt(horse.purchase_score,3),'score-cell'));
      const verdict=node('td');verdict.append(node('span',horse.selected?'購入対象':horse.eligible?'条件適合':'見送り','pill '+(horse.selected?'selected':horse.eligible?'eligible':'neutral')));
      verdict.append(node('small',horse.selected?`単勝 ${fmt(horse.bet_amount,0)}円`:horse.reasons.join(' / ')));row.append(verdict);tbody.append(row);
    }
    table.append(tbody);wrap.append(table);section.append(wrap);
    if(!model.horses.length) section.append(node('p','上位5頭にオッズ条件を満たす馬がいません。','footnote'));
    section.append(node('p',regression?'rankスコアは予測着順をsoftmax変換した値です。校正済みの勝率ではありません。購入スコア = rankスコア × 単勝オッズ。':'購入スコア = 勝率 × 単勝オッズ。勝率上位5頭のうちオッズ条件を満たす馬を、購入スコアが高い順に表示します。','footnote'));
    const bought=model.horses.filter(h=>h.selected);
    section.append(node('p',bought.length?'購入条件に適合する馬のうち、購入スコア最大の1頭を購入対象にしています。':'この設定では購入対象がありません。','footnote'));
    $('results').append(section);
  }
}

async function restoreJob() {
  setBusy(true);
  try {
    const {job:latest}=await api('/api/jobs');
    setBusy(false);
    if(!latest) return;
    const request=latest.request;
    if(request.action==='predict') {
      setMode('id'); $('race-id').value=request.race_id; $('use-saved').checked=!!request.use_saved;
      document.querySelectorAll('input[name=ai]').forEach(el => el.checked=request.strategies.includes(el.value));
    } else { setMode('list'); $('race-date').value=request.date; }
    const result=await job(request,latest);
    if(result) { if(request.action==='predict') render(result); else showRaces(result); }
  } catch(error) { notify('前回の処理を確認できませんでした。ページを再読み込みしてください。'); }
  finally { setBusy(false); }
}
restoreJob();
