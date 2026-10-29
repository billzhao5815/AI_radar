'use strict';
const app=document.querySelector('#app'), notice=document.querySelector('#notice');
const path=location.pathname, params=new URLSearchParams(location.search);
let state, token='', currentRun=null, timer=null;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>'¥'+Number(v||0).toFixed(3);
const tags=a=>(a||[]).map(x=>`<span class="tag">${esc(x)}</span>`).join('');
const statusNames={running:'运行中',ok:'已完成',partial:'部分完成',budget:'预算已暂停',interrupted:'已中断',pending:'待处理',relevant:'相关',uncertain:'不确定',irrelevant:'不相关',error:'失败',empty:'无结果'};
const status=s=>statusNames[s]||s;
function message(s){notice.textContent=s||'';}
async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json','X-Radar-Token':token},body:JSON.stringify(body)}:{cache:'no-store'});const data=await r.json();if(!r.ok)throw Error(data.error||'请求失败');return data;}
async function refresh(){state=await api('/api/state');token=state.token;}
function header(k,title,sub){return `<div class="hero"><div class="eyebrow">${k} / AI RADAR</div><h1>${title}</h1><p class="subtle">${sub}</p></div>`;}
function settings(p){return `<h3>R01 · 监控目标</h3><p>${esc(p.monitoring_goal)}</p><p>${tags(p.monitoring_scope.include)}</p><p class="subtle">排除：${esc(p.monitoring_scope.exclude.join('、')||'没有额外排除')}</p><div class="rule"><h3>R02 · 信息来源</h3>${tags(p.sources.map(s=>state.names[s]))}</div><div class="rule"><h3>R04 · 相关性判断</h3><p>去重、缓存与候选筛选 → 批量语义判断。仅排除明确无关或明确命中用户排除范围的内容；相关、可能相关及信息不足的内容均进入聚合。</p><p class="subtle">候选优先词（未命中仍保留探索机会）</p>${tags(p.terms)}</div><div class="rule"><h3>R05 · 主题发现与传播热度</h3><p>发现共同的具体题材、玩法、方法、事件与商业机会；保留未聚合信息和全部来源。处理本轮 R04 放行的内容（含不确定内容），不做价值评分与跨天趋势。</p></div>${p.assumptions.length?`<div class="rule"><h3>计划假设</h3><ul>${p.assumptions.map(a=>`<li>${esc(a)}</li>`).join('')}</ul></div>`:''}`;}
function channelKeywords(p){return p.channel_keywords?`<div class="rule"><h3>各渠道搜索词</h3>${p.sources.map(source=>`<p><strong>${esc(state.names[source])}</strong> ${p.channel_keywords[source]?.length?tags(p.channel_keywords[source]):'<span class="subtle">固定榜单 / 订阅，无需搜索词</span>'}</p>`).join('')}</div>`:'';}
function taskTable(p){return `<div class="scroll"><table><thead><tr><th>平台 / 动作</th><th>搜索目标</th><th>范围与深度</th></tr></thead><tbody>${p.tasks.map(t=>{const c=state.capabilities.find(c=>c.id===t.capability_id);return `<tr><td>${esc(state.names[t.source])}<br><span class="subtle">${esc(c?.name||t.capability_id)}</span></td><td>${esc(t.query||'平台榜单 / 订阅')}</td><td>${Object.entries(t.options).map(([k,v])=>esc(optionLabel(k,v))).join(' · ')}<br>最多保留 ${t.result_limit} 条</td></tr>`;}).join('')}</tbody></table></div>`;}
function optionLabel(k,v){const names={days:'时间范围',pages:'页数',order:'排序',rid:'分区',upload_date:'发布时间',duration:'时长',label:'内容范围',sort:'排序',since:'榜单周期',limit:'每类数量',time_field:'仓库时间依据',hours:'最近小时',min_points:'最低讨论积分'};const values={click:'播放量',pubdate:'最新发布',this_week:'本周',this_year:'今年',short:'短视频',Top:'热门',Latest:'最新',latest:'最新',hot:'热度',daily:'日榜',weekly:'周榜',monthly:'月榜',pushed:'最近更新',created:'新建时间'};if(k==='days')return v?`最近 ${v} 天`:'接口支持的不限时间范围';if(k==='rid')return '分区 '+({1012:'科技数码',1010:'知识',1001:'影视',1005:'动画',1007:'鬼畜',1003:'音乐'}[v]||v);if(k==='label')return v?'低粉爆款':'全部作品';return `${names[k]||k}：${values[v]||v||'不限'}`;}
function budgetCard(p){return `<aside><div class="card side"><div class="eyebrow">每轮分析预算</div><div class="budget">¥0.8 <small>目标</small></div><p>最高 ¥1.2 · R04 + R05 合计</p><div class="rule"><p>达到预算后保留已完成结果，其余标为待处理。恢复不会重置额度。</p><p class="subtle">配置 Agent 与采集费独立统计，金额按本地配置单价估算。</p></div>${p?`<div class="rule"><h3>采集预算预留</h3><p>最多 ${p.collection_budget.max_calls_with_retries} 次 TikHub 请求（含重试）<br>估算上限 $${p.collection_budget.max_usd_est.toFixed(3)}</p></div>`:''}</div><div class="card"><h3>统一模型配置</h3><p class="subtle">${state.llm_ready?'已读取原项目的大模型配置。':'请在原项目 .env 中设置 LLM_API_KEY 后重启服务。'} 浏览器不接收或保存密钥。</p></div></aside>`;}
async function setup(){
  let a=state.config?.answers||{}, goalId='', acceptedGoal='', working=false;
  const draftId=params.get('draft');
  let restoredDraft=null;
  if(draftId){restoredDraft=await api('/api/draft?id='+encodeURIComponent(draftId));a=restoredDraft.payload?.answers||restoredDraft.payload||a;goalId=restoredDraft.payload?.goal_id||'';}
  else goalId=params.get('goal')||state.config?.goal_id||'';
  let restoredGoal=null;
  if(goalId){try{restoredGoal=await api('/api/goal?id='+encodeURIComponent(goalId));if(!draftId)a={...a,goal:restoredGoal.input};}catch(err){message(err.message);goalId='';}}
  const splitDetail=a.detail&&typeof a.detail==='object'&&!Array.isArray(a.detail);
  const savedScope=(draftId?restoredDraft?.payload:state.config)?.monitoring_scope;
  const keywordText=v=>Array.isArray(v)?v.join('，'):(typeof v==='string'?v:'');
  const includeText=keywordText(splitDetail?a.detail.include:savedScope?.include);
  const excludeText=keywordText(splitDetail?a.detail.exclude:savedScope?.exclude);
  const legacyDetail=!splitDetail&&!savedScope&&typeof a.detail==='string'?a.detail:'';
  app.innerHTML=header('01','让雷达知道，你在关注什么','先检查 AI 相关性，再选择渠道与关注范围，生成关键词时自动理解目标。')+`<div class="layout"><form id="setupForm">
    <section class="card"><label for="goal"><span class="step">1</span>你希望监控哪个 AI 相关领域？</label><textarea id="goal" maxlength="2000" required placeholder="例如AI视频，AI副业，FDE等，请输入关键词，不要输入长句" aria-describedby="goalStatus">${esc(a.goal||'')}</textarea><div class="actions"><button id="checkGoal" type="button">校验 AI 相关性 →</button></div><div id="goalStatus" role="status" aria-live="polite"></div></section>
    <fieldset id="details" disabled><section class="card"><label><span class="step">2</span>你希望从哪些平台获取信息？</label><div class="platforms">${Object.entries(state.names).map(([id,name])=>{const available=state.capabilities.some(c=>c.source===id&&c.available);return `<label class="platform"><input type="checkbox" name="source" value="${id}" ${a.sources?.includes(id)?'checked':''} ${available?'':'disabled'}> ${esc(name)}${available?'':'<small>需配置 TikHub Key</small>'}</label>`;}).join('')}</div><p class="subtle">选择渠道后，将使用该渠道的全部固定采集能力。</p></section>
    ${legacyDetail?`<section class="card"><p class="subtle">旧版需求请分别填写到下方的关注和排除项：</p><p>${esc(legacyDetail)}</p></section>`:''}
    <section class="card"><label for="detailInclude"><span class="step">3</span>你具体想关注什么</label><textarea id="detailInclude" maxlength="2000" placeholder="请输入关键词，逗号分隔，不要输入长句">${esc(includeText)}</textarea></section>
    <section class="card"><label for="detailExclude"><span class="step">4</span>你不想看到什么</label><textarea id="detailExclude" maxlength="2000" placeholder="请输入关键词，逗号分隔，不要输入长句">${esc(excludeText)}</textarea></section><div class="actions"><button id="generate" type="submit">生成计划预览 →</button><span class="subtle">只生成配置，不启动采集</span></div></fieldset>
    <p id="draftStatus" role="status" aria-live="polite"></p></form>${budgetCard()}</div>`;
  const goalInput=document.querySelector('#goal'), check=document.querySelector('#checkGoal'), details=document.querySelector('#details'), goalStatus=document.querySelector('#goalStatus'), draftStatus=document.querySelector('#draftStatus');
  function controls(){check.disabled=working||state.busy||!state.llm_ready;goalInput.disabled=working;details.disabled=working||state.busy||!goalId||acceptedGoal!==goalInput.value.trim();}
  function remember(key,id){const url=new URL(location.href);url.search='';url.searchParams.set(key,id);history.replaceState(null,'',url);}
  function showGoal(g){
    goalId=g.id;goalStatus.className='';
    if(g.status==='ready'&&g.input===goalInput.value.trim()){
      acceptedGoal=g.input;
      goalStatus.innerHTML=`<h3>AI 相关性校验通过</h3><p>${esc(g.input)}</p><p class="subtle">${esc(g.payload.reason)}</p><p class="subtle">继续选择渠道并填写具体需求，生成关键词时会按 AI 行业主流含义理解目标。</p><p class="subtle">相关性校验费用 ${money(g.costs.agent.estimated_cny)}</p>`;
    }else{
      acceptedGoal='';goalStatus.className='error';
      const detail=g.payload?.clarification||g.payload?.reason||g.error||'目标尚未通过校验，请重新输入';
      goalStatus.textContent=g.status==='clarification'?'这是旧版校验结果，请点击“校验 AI 相关性”重新校验。':(g.status==='rejected'?'目标不属于 AI 领域，请修改：':'')+detail;
    }
    controls();
  }
  async function pollGoal(id){
    try{const g=await api('/api/goal?id='+encodeURIComponent(id));
      await refresh();
      if(g.status==='generating'||state.busy){timer=setTimeout(()=>pollGoal(id),1500);return;}
      working=false;showGoal(g);
    }catch(err){working=false;goalStatus.textContent=err.message;await refresh().catch(()=>{});controls();}
  }
  async function pollDraft(id){
    try{const d=await api('/api/draft?id='+encodeURIComponent(id));
      if(d.status==='generating'){draftStatus.textContent='正在解析目标、提炼需求并生成校验渠道关键词…';timer=setTimeout(()=>pollDraft(id),1500);return;}
      if(d.status==='ready'||d.status==='confirmed'){location.href='/plan?draft='+encodeURIComponent(id);return;}
      await refresh();
      if(state.busy){timer=setTimeout(()=>pollDraft(id),1500);return;}
      working=false;controls();draftStatus.className='error';
      draftStatus.textContent=(d.status==='clarification'?'请补充或修改具体需求：':'')+(d.error||'生成失败，请重试')+`（关键词生成费用 ${money(d.costs.agent.estimated_cny)}）`;
    }catch(err){working=false;draftStatus.textContent=err.message;await refresh().catch(()=>{});controls();}
  }
  goalInput.oninput=()=>{goalId='';acceptedGoal='';goalStatus.textContent='目标已修改，请重新校验。';draftStatus.textContent='';history.replaceState(null,'',location.pathname);controls();};
  check.onclick=async()=>{
    if(!goalInput.reportValidity())return;
    working=true;acceptedGoal='';goalId='';controls();message('');goalStatus.className='';goalStatus.textContent='正在检查 AI 相关性…';draftStatus.textContent='';
    try{const g=await api('/api/understand',{goal:goalInput.value});goalId=g.goal_id;remember('goal',goalId);await pollGoal(goalId);}
    catch(err){working=false;goalStatus.className='error';goalStatus.textContent=err.message;await refresh().catch(()=>{});controls();}
  };
  document.querySelector('#setupForm').onsubmit=async e=>{
    e.preventDefault();if(working)return;
    if(!acceptedGoal||acceptedGoal!==goalInput.value.trim())return message('请先校验当前监控目标');
    const sources=[...document.querySelectorAll('input[name=source]:checked')].map(x=>x.value);
    if(!sources.length)return message('请至少选择一个平台');
    working=true;controls();message('');draftStatus.className='';draftStatus.textContent='正在解析目标、提炼需求并生成校验渠道关键词…';
    try{const d=await api('/api/generate',{goal:goalInput.value,goal_id:goalId,sources,detail:{include:document.querySelector('#detailInclude').value,exclude:document.querySelector('#detailExclude').value}});remember('draft',d.draft_id);await pollDraft(d.draft_id);}
    catch(err){working=false;draftStatus.className='error';draftStatus.textContent=err.message;await refresh().catch(()=>{});controls();}
  };
  if(restoredGoal?.status==='generating'){working=true;controls();goalStatus.textContent='正在检查 AI 相关性…';await pollGoal(goalId);}
  else if(restoredGoal)showGoal(restoredGoal);
  else controls();
  if(restoredDraft){
    if(restoredDraft.status==='generating'){working=true;controls();await pollDraft(draftId);}
    else if(['error','clarification'].includes(restoredDraft.status)){
      draftStatus.className='error';draftStatus.textContent=restoredDraft.error;
    }
  }
}

async function plan(){let p=state.config,draft=null;const id=params.get('draft');if(id){draft=await api('/api/draft?id='+encodeURIComponent(id));if(draft.status==='generating'){app.innerHTML=header('02','正在准备你的采集计划','正在整理目标、校验平台与预算。页面可以保留，完成后会自动显示。')+`<div class="card"><p>生成中…</p><p class="subtle">当前有效配置保持不变，不会启动采集。</p><p>Agent 费用：${money(draft.costs.agent.estimated_cny)}</p></div>`;timer=setTimeout(()=>plan().catch(e=>message(e.message)),2000);return;}if(['error','clarification'].includes(draft.status)){app.innerHTML=header('02','计划尚未生成','原有有效配置保持不变。')+`<div class="card"><p class="error">${esc(draft.error)}</p><p>Agent 费用：${money(draft.costs.agent.estimated_cny)}</p><a class="button" href="/setup?draft=${esc(id)}">修改答案并重试</a></div>`;return;}p=draft.payload;}
if(!p){app.innerHTML=header('02','还没有有效的采集计划','先告诉雷达你关注的目标。')+'<a class="button" href="/setup">开始配置 →</a>';return;}
const preview=draft?.status==='ready';app.innerHTML=header('02',preview?'确认你的采集计划':esc(p.name),preview?'预览确认后才会生效。确认不会启动采集。':`配置版本 ${esc(state.config?.version||'')} · 计划已冻结，重复运行使用相同任务。`)+`<div class="layout"><div><section class="card">${settings(p)}</section><section class="card"><h2>R03 · 采集计划</h2><p class="subtle">${p.schema_version===2?'程序按所选渠道的全部固定能力生成任务，关键词来自配置 Agent。':'这是此前保存的计划，重新配置后将使用全部固定能力。'}</p>${channelKeywords(p)}${taskTable(p)}${(p.planning_notes||[]).map(n=>`<p class="subtle">${esc(n)}</p>`).join('')}</section><div class="actions">${preview?`<button id="confirm">确认并保存配置</button><a class="button secondary" href="/setup?draft=${esc(id)}">返回修改 / 放弃预览</a>`:'<button id="start">开始采集 →</button><a class="button secondary" href="/setup">修改配置</a><a href="/collect">查看历史结果</a><button class="secondary" id="exportPlan">导出配置</button>'}</div>${draft?`<p class="subtle">本次关键词生成费用 ${money(draft.costs.agent.estimated_cny)}${draft.goal_costs?` · 相关性校验费用 ${money(draft.goal_costs.agent.estimated_cny)}（复用时不重复计费）`:''}</p>`:''}</div>${budgetCard(p)}</div>`;
const confirm=document.querySelector('#confirm');if(confirm)confirm.onclick=()=>action(confirm,async()=>{await api('/api/confirm',{draft_id:id});location.href='/plan';});const exp=document.querySelector('#exportPlan');if(exp)exp.onclick=()=>downloadJson(p,'radar-plan-v'+(state.config?.version||1)+'.json');bindStart();}
async function action(btn,fn){btn.disabled=true;message('');try{await fn();}catch(e){message(e.message);btn.disabled=false;}}
function bindStart(){const btn=document.querySelector('#start');if(btn){btn.disabled=state.busy||!state.llm_ready;btn.onclick=()=>action(btn,async()=>{const r=await api('/api/start',{});location.href='/collect?run='+r.run_id;});}}
function safeUrl(u){try{const v=new URL(u);return ['http:','https:'].includes(v.protocol)?esc(v.href):'#';}catch{return '#';}}
function evidenceView(i){const e=i.r04_evidence||{};const labels={direct_grounded:'直接相关 · 引用已核对',adjacent:'相邻参考',mention:'仅提及',insufficient:'信息不足',evidence_unmatched:'引用待核对',promotion_only:'仅推广提及',incidental_mention:'背景提及',relation_missing:'关系判断不完整',unrelated:'无关'};let html=e.review_code?tags([labels[e.review_code]||e.review_code]):'';for(const [key,label] of [['target_evidence','目标对象'],['evidence','实质依据']]){const spans=e[key];if(Array.isArray(spans)){html+=spans.map(v=>typeof v==='string'?`<p>${label}：${esc(v)}</p>`:`<p>${label} · ${v.field==='title'?'标题':'正文'}：${esc(v.quote)}</p>`).join('');}else if(spans){html+=`<p>${label}：${esc(spans)}</p>`;}}return html;}
function sourceLink(i){return `<a target="_blank" rel="noopener noreferrer" href="${safeUrl(i.url)}">${esc(i.title||i.id)}</a>`;}
function downloadJson(data,name){const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
function exportRun(){downloadJson(currentRun,`radar-run-${currentRun.run_id}.json`);}
function topicCard(g,byId){const m=g.metrics||{}, reps=g.representative_item_ids||g.item_ids.slice(0,6);return `<article class="card group" id="topic-${esc(g.group_id)}">${tags([g.type||g.category])}<h2>${esc(g.title)}</h2><p>${esc(g.summary)}</p><p class="subtle">${m.item_count??g.item_ids.length} 条信息 · ${m.author_count??'未知'} 个可识别账号 · ${m.platform_count??'未知'} 个平台</p><p>${m.max_heat==null?'相对热度未知':`最高相对热度 ${esc(m.max_heat)} / 100 · 前三平均 ${esc(m.avg_top_heat)}`}${m.low_fans_hot_count?` · 低粉爆款 ${m.low_fans_hot_count} 条`:''}</p><ul>${reps.map(id=>`<li>${byId[id]?sourceLink(byId[id]):esc(id)}</li>`).join('')}</ul><details><summary>展开全部 ${g.item_ids.length} 条关联内容</summary><ul>${g.item_ids.map(id=>`<li>${byId[id]?sourceLink(byId[id]):esc(id)}</li>`).join('')}</ul></details></article>`;}
async function collect(){await refresh();let rid=Number(params.get('run'));if(!rid){const rows=state.runs.filter(r=>r.config_id===state.config?.version);rid=(rows.find(r=>r.status==='ok')||rows[0])?.id;}
if(!rid){app.innerHTML=header('03','准备好收集第一批信息','采集只执行到 R05，完成后在这里查看结果。')+'<div class="empty"><p>当前配置还没有运行记录</p><a class="button" href="/plan">查看计划并开始采集</a></div>';return;}
currentRun=await api('/api/run?id='+rid);const r=currentRun,s=r.state,c=r.counts,items=r.items,byId=Object.fromEntries(items.map(i=>[i.id,i]));const total=r.costs.r04.estimated_cny+r.costs.r05.estimated_cny;
app.innerHTML=header('03','把信息，整理成线索',`${esc(r.name)} · 配置 v${r.config_version} · 运行 #${r.run_id}`)+`<div class="runhead"><span class="tag">${esc(status(s.status))}</span><select id="history" aria-label="切换历史运行">${state.runs.map(x=>`<option value="${x.id}" ${x.id===rid?'selected':''}>#${x.id} · ${esc(x.name)} · ${esc(x.day)} · ${esc(status(x.status))}</option>`).join('')}</select><button class="secondary right" id="export">导出完整结果</button></div><div class="progress">${[['collect','采集'],['r04','R04 相关性'],['r05','R05 聚合'],['done','结果']].map(([k,v])=>`<span class="${s.stage===k?'current':''}">${v}</span>`).join('')}</div><div class="metrics"><div class="metric"><strong>${items.length}</strong><span>去重后的原始信息</span></div><div class="metric"><strong>${c.relevant||0}</strong><span>相关 · 不确定 ${c.uncertain||0}</span></div><div class="metric"><strong>${(c.pending||0)+(r.r05_pending||0)}</strong><span>待处理（R04 ${c.pending||0} / R05 ${r.r05_pending||0}） · 缓存命中 ${items.filter(i=>i.cache_hit).length}</span></div><div class="metric"><strong>${money(total)}</strong><span>分析费用 / 额度 ${money(s.limit_cny)}</span></div></div>${(s.analysis_warnings||[]).length?`<details class="card"><summary>分析保护与纠正记录（${s.analysis_warnings.length}）</summary><ul>${s.analysis_warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details>`:''}${s.errors.length?`<div class="card"><h3>运行提示</h3><p class="error">${s.errors.map(esc).join('<br>')}</p></div>`:''}<div class="layout"><div><div class="card"><h2>主题集合 <span class="tag">${s.groups.length} 组</span></h2>${!s.r05_complete?'<p class="subtle">聚合尚未全部完成。已完成批次保存在下方，可恢复；此前完成的主题（如有）不代表当前全部输入。</p>':''}${s.groups.length?'':'<p class="subtle">暂无已完成主题。相关条目进入聚合后将在这里显示。</p>'}</div><p class="subtle">热度仅代表当前采集样本中的相对传播表现，不代表行业整体热度或升温趋势。</p>${s.groups.map(g=>topicCard(g,byId)).join('')}<section class="card"><h2>未聚合信息</h2><p class="subtle">已分析但暂未形成有意义的具体主题。</p><ul>${(s.ungrouped_item_ids||[]).map(id=>`<li>${byId[id]?sourceLink(byId[id]):esc(id)}</li>`).join('')||'<li>暂无</li>'}</ul></section><section class="card"><h2>逐条检查</h2><select id="filter" aria-label="筛选相关性状态"><option value="">全部信息</option value="uncertain">不确定</option><option value="pending">待处理</option><option value="irrelevant">不相关</option><option value="relevant">相关</option></select><div id="itemList"></div></section></div><aside><section class="card side"><h2>费用明细</h2>${['r04','r05'].map(k=>`<h3>${k.toUpperCase()} · ${money(r.costs[k].estimated_cny)}</h3><p class="subtle">输入 ${r.costs[k].input_tokens.toLocaleString()} / 输出 ${r.costs[k].output_tokens.toLocaleString()} Token<br>${r.costs[k].calls} 次调用</p>`).join('')}<p class="subtle">含用量未知请求的保守预留 ${money(r.costs.r04.uncertain_reserved_cny+r.costs.r05.uncertain_reserved_cny)}；费用为估算。</p><div class="rule"><p>TikHub 预算占用 $${Number(s.collection_usd).toFixed(3)}（含重试预留）</p></div></section>${s.status!=='running'&&s.status!=='ok'?`<section class="card"><h3>继续处理</h3><p class="subtle">沿用本轮配置与剩余额度，已完成分析不重复调用。</p><label for="extra">明确追加分析预算（元，可留 0）</label><input id="extra" type="number" min="0" max="10" step="0.1" value="0"><button id="resume">恢复此轮运行</button></section>`:''}<section class="card"><h3>采集任务</h3>${Object.entries(s.tasks).map(([id,t])=>`<p><strong>${esc(id)} · ${esc(status(t.status))}</strong><br>${t.count||0} 条 <span class="error">${esc(t.error||(t.errors||[]).join('；'))}</span></p>`).join('')}</section><a href="/plan">← 返回当前配置</a></aside></div>`;
document.querySelector('#export').onclick=exportRun;document.querySelector('#history').onchange=e=>location.href='/collect?run='+e.target.value;
const filter=document.querySelector('#filter');function list(){const visible=items.filter(i=>!filter.value||i.r04_status===filter.value);document.querySelector('#itemList').innerHTML=visible.slice(0,150).map(i=>`<div class="rule">${tags([status(i.r04_status),i.source])}<h3>${sourceLink(i)}</h3><p class="subtle">${esc(i.r04_reason||'等待候选处理或剩余预算')}</p>${evidenceView(i)}<p class="subtle">主题关联：${(i.group_ids||[]).map(id=>`<a href="#topic-${esc(id)}">${esc((s.groups.find(g=>g.group_id===id)||{}).title||id)}</a>`).join('、')||(i.r05_status==='ungrouped'?'未聚合':i.r05_status==='pending'?'待处理':'—')}</p><details><summary>查看已采集文本与任务来源</summary><p>${esc(i.text||'接口未提供额外文本')}</p><code>${esc(i.id)}</code><p>任务 ${esc(i.task_ids.join('、'))}</p></details></div>`).join('')+(visible.length>150?'<p>页面显示前 150 条，完整信息请导出查看。</p>':'');}filter.onchange=list;list();
const resume=document.querySelector('#resume');if(resume)resume.onclick=()=>action(resume,async()=>{await api('/api/resume',{run_id:rid,extra_budget:Number(document.querySelector('#extra').value)});location.href='/collect?run='+rid;});if(s.status==='running')timer=setTimeout(()=>collect().catch(e=>message(e.message)),2500);
}
(async()=>{try{await refresh();document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',a.pathname===path));if(path==='/setup')await setup();else if(path==='/plan')await plan();else await collect();}catch(e){message(e.message);}})();
