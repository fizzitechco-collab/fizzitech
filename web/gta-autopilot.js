/* LEGEND_SOURCE1080_GTA_UI_V1 */
/* LEGEND_GTA_DASHBOARD_V2 — English/Hindi separate screens, manual source links,
 * explicit connected destination accounts, automatic best available source quality. */
let gtaState = null;
let gtaLoading = false;
let gtaActiveLane = 'english';
const gtaEscape = s => String(s ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const gtaOption = (items, value) => items.map(([id,label])=>`<option value="${gtaEscape(id)}" ${String(id)===String(value)?'selected':''}>${gtaEscape(label)}</option>`).join('');
const gtaNames = {youtube:'YouTube Shorts', instagram:'Instagram Reels', tiktok:'TikTok'};
function gtaAccountMenu(platform, selected){
  const accounts = (gtaState?.accounts || []).filter(a=>a.platform===platform);
  const options = [['',accounts.length ? `Choose ${gtaNames[platform]} destination` : `No ${gtaNames[platform]} account connected`],
    ...accounts.map(a=>[a.id,a.name])];
  return gtaOption(options, selected||'');
}
function gtaDestinationRow(platform, field, selected){
  const n=(gtaState?.accounts||[]).filter(a=>a.platform===platform).length;
  return `<div class="gta-destination"><label class="gta-label">${gtaNames[platform]} account
    <select data-gta="${field}" aria-label="${gtaNames[platform]} upload account">${gtaAccountMenu(platform,selected)}</select></label>
    <button type="button" class="btn sm" data-gta-action="connect" aria-label="Connect ${gtaNames[platform]} account">${n?'Manage':'Connect'}</button></div>`;
}
function gtaLane(lang){
 const d=gtaState?.lanes?.[lang]||{};
 const run=gtaState?.runtime?.[lang]||{};
 const language=lang==='english'?'English':'Hindi / Hinglish';
 const limit = (v, items) => gtaOption([['0','MAX — all suitable clips'],...items.map(x=>[String(x),String(x)])],String(v??0));
 return `<section class="gta-lane" data-lane="${lang}" ${gtaActiveLane!==lang?'hidden':''}>
   <header class="gta-lane-head"><div><small>${lang==='english'?'ENGLISH • GTA 6':'HINDI / HINGLISH • GTA 6'}</small>
     <h3>${language} Autopilot</h3><p>Sources and upload destinations are independent from the other language.</p></div>
     <span class="gta-state ${run.status==='recording'?'on':''}">${gtaEscape(d.enabled?(run.status||'waiting'):'OFF')}</span></header>
   <div class="gta-section"><div class="gta-section-heading"><span class="gta-step">01</span><div><h4>Which YouTubers should I watch?</h4><p>Paste full YouTube channel URLs. These are the creators whose GTA 6 livestreams and videos will be clipped—not upload accounts.</p></div></div>
     <label class="gta-label">Source creator channels <span>One channel link per line · up to 20 · LIVE first</span>
       <textarea data-gta="channels" rows="5" placeholder="https://www.youtube.com/@creator1\nhttps://www.youtube.com/@creator2">${gtaEscape((d.channels||[]).join('\n'))}</textarea></label>
     <p class="gta-tip">Channel links go here. Your own English/Hindi publishing channels are selected below.</p></div>
   <div class="gta-section"><div class="gta-section-heading"><span class="gta-step">02</span><div><h4>Where should my clips upload?</h4><p>Connect your own channels under Settings → Connected apps, then choose a different destination for each language.</p></div></div>
      <div class="gta-destinations">${gtaDestinationRow('youtube','youtube_account',d.youtube_account)}${gtaDestinationRow('instagram','instagram_account',d.instagram_account)}${gtaDestinationRow('tiktok','tiktok_account',d.tiktok_account)}</div>
      <label class="gta-switch gta-main-switch"><input type="checkbox" data-gta="autopost" ${d.autopost?'checked':''}><span><b>Auto-post: ${d.autopost?'ON':'OFF'}</b><small>When ON, upload each finished clip to every selected account above. OFF = make clips only.</small></span></label>
      <label class="gta-switch"><input type="checkbox" data-gta="rights" ${d.rights?'checked':''}><span>I have permission to reuse and publish these creators' footage.</span></label>
      <p class="gta-tip">Seeing “No account connected”? Press Connect, authorize YouTube / Instagram / TikTok, return here and select that account. Both mode requires separate posting accounts for English and Hindi.</p>
   </div>
   <div class="gta-section"><div class="gta-section-heading"><span class="gta-step">03</span><div><h4>Highlight quality & limits</h4><p>Find one → render → post (if ON) → find next. MAX means no fixed daily/video count imposed by this dashboard.</p></div></div>
      <div class="gta-fields">
        <label class="gta-label">Video quality <select data-gta="quality">${gtaOption([['auto','Best available (max 1080p)'],['1080','Require 1080p'],['720','Require 720p'],['360','360p quick']], String(d.quality??'auto'))}</select></label>
        <label class="gta-label">Archived videos: minimum subscribers<input data-gta="min_subs" type="number" min="0" max="20000000" value="${Number(d.min_subs??(lang==='english'?500000:100000))}"></label>
        <label class="gta-label">Clips per archived video<select data-gta="max_per_video">${limit(d.max_per_video,[5,10,20,50,100])}</select></label>
        <label class="gta-label">Clips per day<select data-gta="daily_cap">${limit(d.daily_cap,[10,20,50,100,200])}</select></label>
        <label class="gta-label">Minimum highlight score<input data-gta="min_score" type="number" min="0" max="100" value="${Number(d.min_score??75)}"></label>
      </div>
      <label class="gta-switch"><input type="checkbox" data-gta="cta" ${d.cta?'checked':''}><span>Add small end CTA: Watch more on the original creator's channel</span></label>
      <p class="gta-tip">TikTok publishing: the promotional CTA is automatically disabled for TikTok-bound auto-post clips. Real source quality depends on stream formats; lower-quality videos won't be fake-upscaled to 1080p. MAX still respects stream length, suitable highlights and platform API limits.</p>
   </div>
   <div class="gta-runtime" aria-live="polite"><b>${gtaEscape(run.message||'Not monitoring')}</b>
      ${run.job_id?`<small>Video job: ${gtaEscape(run.job_id)}</small>`:''}
      ${run.live_job_id?`<small>LIVE: ${gtaEscape(run.live_job_id)}</small>`:''}
      <small>${Number(run.processed||0)} completed clips today · LIVE checks every 5 minutes</small>
      ${run.error?`<small class="gta-error">${gtaEscape(run.error)}</small>`:''}</div>
   <div class="gta-actions"><button type="button" class="btn danger" data-gta-action="stop" data-gta-lang="${lang}">Stop ${language}</button></div>
 </section>`;
}
function gtaChooseLane(lang){
 if(!['english','hindi'].includes(lang))return;
 gtaActiveLane=lang;
 document.querySelectorAll('#gta-auto [data-lane]').forEach(s=>{s.hidden=s.dataset.lane!==lang;});
 document.querySelectorAll('#gta-auto [data-gta-tab]').forEach(b=>{
   const on=b.dataset.gtaTab===lang; b.classList.toggle('active',on);b.setAttribute('aria-selected',String(on));
 });
}
async function drawGtaAuto(){
 const root=document.getElementById('gta-auto');
 if(!root||gtaLoading)return;
 gtaLoading=true;
 try{
   gtaState=await api('/api/gta-autopilot');
   root.innerHTML=`<div class="gta-title"><div><span>GTA VI / ENGLISH + HINDI AUTOMATION</span><h2>Auto Clipping</h2>
     <p>Add source YouTube channels yourself. Find one highlight → render → optionally post to 3 platforms → repeat.</p></div><button type="button" class="btn" data-gta-action="refresh">Refresh status</button></div>
     <div class="gta-toolbar"><label class="gta-label">Monitoring mode<select id="gta-mode">${gtaOption([['english','English only'],['hindi','Hindi only'],['both','Both (run separately)']],gtaState.mode)}</select></label>
       <div class="gta-actions"><button type="button" class="btn" data-gta-action="save">Save settings</button><button type="button" class="btn primary" data-gta-action="start">Save & Start</button><button type="button" class="btn danger" data-gta-action="stop" data-gta-lang="both">Stop All</button></div></div>
     <div class="gta-tabs" role="tablist" aria-label="Language dashboards"><button type="button" role="tab" data-gta-tab="english">English dashboard</button>
       <button type="button" role="tab" data-gta-tab="hindi">Hindi dashboard</button><span>Both mode runs both in background</span></div>
     <div class="gta-rows">${gtaLane('english')}${gtaLane('hindi')}</div>
     <div class="gta-note">Connect upload accounts first under <b>Settings → Connected apps</b>. Your source channels are not upload destinations. Auto-post requires connected accounts and permission to reuse the footage. TikTok may require a reviewed app with video.publish permission; Instagram needs a professional account. The GTA 6 filter uses title/transcript evidence rather than guaranteed visual recognition.</div>`;
   gtaChooseLane(gtaActiveLane);
 }catch(err){root.innerHTML=`<div class="gta-error">Unable to load GTA Auto Clipping: ${gtaEscape(err.message)}</div>`;}
 finally{gtaLoading=false;}
}
function gtaCollect(){
 const lanes={};
 for(const lang of ['english','hindi']){
   const el=document.querySelector(`#gta-auto [data-lane="${lang}"]`);
   if(!el)throw new Error('Open Auto Clipping before saving');
   const v=k=>el.querySelector(`[data-gta="${k}"]`);
   lanes[lang]={channels:v('channels').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean),
     youtube_account:v('youtube_account').value,instagram_account:v('instagram_account').value,tiktok_account:v('tiktok_account').value,
     min_subs:Number(v('min_subs').value),quality:v('quality').value,
     daily_cap:Number(v('daily_cap').value),max_per_video:Number(v('max_per_video').value),
     min_score:Number(v('min_score').value),cta:v('cta').checked,rights:v('rights').checked,autopost:v('autopost').checked};
 }
 return {mode:document.querySelector('#gta-mode').value, lanes};
}
async function gtaSave(start){
 const payload=gtaCollect();
 const active=payload.mode==='both'?['english','hindi']:[payload.mode];
 if(start){
   for(const lang of active){
     const d=payload.lanes[lang];
     if(!d.channels.length){gtaChooseLane(lang);throw new Error(`Add at least one source YouTube channel to ${lang} first.`);}
     if(d.autopost){
       if(!d.rights){gtaChooseLane(lang);throw new Error(`${lang}: confirm you have publishing permission.`);}
       if(![d.youtube_account,d.instagram_account,d.tiktok_account].some(Boolean)){
         gtaChooseLane(lang);throw new Error(`${lang}: connect and select a publishing account, or switch Auto-post OFF.`);
       }
     }
   }
 }
 if(start && active.some(lang=>payload.lanes[lang].autopost)){
   if(!confirm('Enable unattended posting to the selected YouTube, Instagram and/or TikTok accounts? Confirm you have rights to the creators\' footage.'))return;
 }
 await send('/api/gta-autopilot',payload,'PUT');
 if(start)await send('/api/gta-autopilot/start',{},'POST');
 toast(start?'GTA 6 Auto Clipping started':'Settings saved','ok');
 await drawGtaAuto();
}
document.addEventListener('click',async e=>{
 const tab=e.target.closest('[data-gta-tab]');
 if(tab && document.getElementById('gta-auto')?.contains(tab)){
   e.preventDefault();e.stopPropagation();gtaChooseLane(tab.dataset.gtaTab);return;
 }
 const b=e.target.closest('[data-gta-action]');
 if(!b)return;
 e.preventDefault();e.stopPropagation();
 if(b.disabled)return;
 b.disabled=true;
 try{
   const a=b.dataset.gtaAction;
   if(a==='connect') {go('settings','apps');return;}
   if(a==='refresh')await drawGtaAuto();
   if(a==='save')await gtaSave(false);
   if(a==='start')await gtaSave(true);
   if(a==='stop'){
     await send('/api/gta-autopilot/stop',{lang:b.dataset.gtaLang||'both'},'POST');
     toast('Auto Clipping stop requested','ok'); await drawGtaAuto();
   }
 }catch(err){toast(err.message||'Action failed','bad');}
 finally{b.disabled=false;}
},true);
document.addEventListener('change',e=>{
 const inp=e.target.closest('#gta-auto [data-gta="autopost"]');
 if(inp){ const lbl=inp.closest('label');const title=lbl?.querySelector('b');if(title)title.textContent='Auto-post: '+(inp.checked?'ON':'OFF');}
});
// Only refresh status text, not the entire form: preserve unsaved channel links.
setInterval(async()=>{
 const root=document.getElementById('gta-auto');if(!root||!root.querySelector('.gta-lane')||document.hidden)return;
 try{
   const d=await api('/api/gta-autopilot');gtaState={...gtaState,runtime:d.runtime};
   for(const lang of ['english','hindi']){
     const el=root.querySelector(`[data-lane="${lang}"]`),r=d.runtime?.[lang]||{};
     if(!el)continue;
     const badge=el.querySelector('.gta-state');
     if(badge){badge.textContent=d.lanes?.[lang]?.enabled?(r.status||'waiting'):'OFF';badge.classList.toggle('on',r.status==='recording');}
     const status=el.querySelector('.gta-runtime');
     if(status){const b=status.querySelector('b');if(b)b.textContent=r.message||'Not monitoring';}
   }
 }catch(_ignored){}
},15000);
