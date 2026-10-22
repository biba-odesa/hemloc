'use strict';
const $ = selector => document.querySelector(selector);
const state = {view:'dashboard',page:1,size:25,total:0,me:null,csrf:'',editing:null,infoLanguage:'en',generation:0,sort:'prefix',direction:'asc',historyCategory:'blocklist',historyFilters:{}};
const titles = {asn:'Blocked ASNs',manual:'Blocked IP list',dashboard:'Dashboard',audit:'History',users:'Users',info:'Info'};
const writable = () => state.me?.role==='admin' && state.me?.node_role==='master';
const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
const dateFormat = new Intl.DateTimeFormat('en-GB',{year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'shortOffset'});
const when = value => value ? `${dateFormat.format(new Date(value*1000))} (${zone})` : 'Never';
const text = (tag,value,cls='') => {const el=document.createElement(tag);el.textContent=value;el.className=cls;return el;};
function notice(value,error=false){if(!state.me){$('#login-notice').hidden=false;$('#login-notice').textContent=value;return;}$('#notice').hidden=false;$('#notice').className=error?'error':'';$('#notice').textContent=value;const dialog=$('dialog[open]');if(error&&dialog){let alert=dialog.querySelector('.dialog-notice');if(!alert){alert=text('p','', 'dialog-notice danger');alert.setAttribute('role','alert');(dialog.querySelector('form')||dialog).prepend(alert);}alert.textContent=value;}}
let refreshTimer;
function showLogin(message=''){
  state.me=null;state.csrf='';state.generation++;clearInterval(refreshTimer);clearTimeout(previewTimer);clearTimeout(searchTimer);
  document.body.classList.add('signed-out');$('#navigation').hidden=true;$('#app-header').hidden=true;$('#workspace').hidden=true;$('#logout').hidden=true;$('#login-panel').hidden=false;
  $('#app-version').hidden=true;$('#app-version').textContent='';$('#app-version').removeAttribute('title');
  $('#content').replaceChildren();$('#identity').textContent='';$('#node').textContent='';$('#notice').hidden=true;
  document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
  $('#login-notice').textContent=message;$('#login-notice').hidden=!message;
}
async function api(path,method='GET',body){const options={method,credentials:'same-origin',headers:{}};if(method!=='GET'){options.headers['Content-Type']='application/json';options.headers['X-CSRF-Token']=state.csrf;options.body=JSON.stringify(body||{});}const response=await fetch(path,options);const data=await response.json();if(!response.ok){if(data.session_required)showLogin('Your session has ended. Sign in again.');const error=new Error(data.error||'Request failed');error.existingRule=data.existing_rule_id;throw error;}return data;}
async function refreshSession(){if(!state.me)return;const auth=await api('/api/session');if(!auth.authenticated){showLogin('Your session has ended. Sign in again.');return;}if(state.view==='dashboard'){await metrics();await refreshVisibleRoutes();}else if(state.view==='manual'&&!$('dialog[open]'))await refreshCoverage();}
async function action(fn){try{await fn();}catch(error){notice(error.message,true);if(error.existingRule){const root=$('dialog[open] .dialog-notice')||$('#notice');root.append(document.createTextNode(' '),button('Open existing record',()=>openRecord(error.existingRule)));}}}
function button(label,fn,danger=false){const el=text('button',label,danger?'danger':'');el.type='button';el.onclick=()=>action(fn);return el;}
function table(headers,rows,cls=''){const el=document.createElement('table'),head=document.createElement('thead'),tr=document.createElement('tr'),body=document.createElement('tbody');el.className=cls;headers.forEach(h=>tr.append(text('th',h)));head.append(tr);el.append(head,body);rows.forEach(cells=>{const row=document.createElement('tr');cells.forEach(value=>{const td=document.createElement('td');if(value instanceof Node)td.append(value);else td.textContent=String(value??'—');row.append(td);});body.append(row);});if(!rows.length){const row=document.createElement('tr'),td=text('td','No results','empty');td.colSpan=headers.length;row.append(td);body.append(row);}return el;}
function fields(entries){const dl=document.createElement('dl');dl.className='field-grid';for(const [key,value] of entries){dl.append(text('dt',key),text('dd',value??'Unknown'));}return dl;}
function tag(value){return text('span',value,'tag '+(['Established','Applied','In sync','Exported'].includes(value)?'good':['Failed','Excluded by protection','Stale','Unavailable'].includes(value)?'warn':''));}
function detail(label,render){const el=document.createElement('details');el.append(text('summary',label));el.addEventListener('toggle',()=>{if(el.open&&el.children.length===1){const body=document.createElement('div');el.append(body);action(async()=>{await render(body);});}});return el;}
function sourceName(rule){return rule.kind==='asn'?`AS${rule.asn} — ${rule.name||'Name unknown'}`:'Blocked from IP networks list';}
function duration(seconds){if(seconds==null)return 'Unknown';const days=Math.floor(seconds/86400),hours=Math.floor(seconds%86400/3600),minutes=Math.floor(seconds%3600/60);return `${days?days+'d ':''}${hours}h ${minutes}m ${Math.floor(seconds%60)}s`;}
function renderPeers(data){const root=$('#sessions');if(!root)return;root.replaceChildren(text('h2','BGP sessions'));if(!data.peers.length){root.append(text('p',data.application_status==='Stale'?'Stale observations':'Unknown — no current peer observations','empty'));return;}root.append(table(['Peer','Status','Uptime','IPv4 advertised','IPv6 advertised'],data.peers.map(p=>[p.peer,tag(p.status),p.status==='Established'?duration(p.uptime_seconds):p.status==='Disabled'?'—':p.status==='Stale'?'Stale':'Unknown',p.ipv4_advertised??(p.status==='Stale'?'Stale':'Unknown'),p.ipv6_advertised??(p.status==='Stale'?'Stale':'Unknown')]),'session-table'));root.append(text('small',`Observed: ${when(data.observed_at)}`,'muted'));}
async function metrics(){const data=await api('/api/dashboard');const peerName=data.peer.name.replace(/^hemloc(?:k)?-([ab])$/i,(_,letter)=>`Hemlock-${letter.toUpperCase()}`);$('#peer-title').textContent=`${peerName} status`;$('#peer-state').textContent=data.peer.status;$('#peer-state').className=data.peer.healthy===true&&data.peer.status==='In sync'?'sync-healthy':'sync-unhealthy';$('#peer-state').setAttribute('role','status');$('#peer-detail').textContent=`Last successful sync: ${data.peer.last_success?when(data.peer.last_success):"Unknown"} · Lag: ${data.peer.lag==null?'Unknown':data.peer.lag+' changes'}`;$('#blocked-v4').textContent=data.blocked?.ipv4??'Unknown';$('#blocked-v6').textContent=data.blocked?.ipv6??'Unknown';$('#blocked-total').textContent=data.blocked?.total??'Unknown';$('#application-detail').textContent=`Required: IPv4 ${data.required.ipv4} · IPv6 ${data.required.ipv6} · Total ${data.required.total}${data.application_status!=='Fresh'?' · '+data.application_status+' observations':''}`;const warnings=[];if(data.pending)warnings.push(`Pending: ${data.pending}${data.withdrawals?` (${data.withdrawals} withdrawals)`:""}`);if(data.failed)warnings.push(`Failed: ${data.failed}`);if(data.excluded)warnings.push(`Excluded by protection: ${data.excluded}`);if(data.application_status!=='Fresh')warnings.push(`Application state: ${data.application_status}`);warnings.push(...data.errors);$('#application-warning').hidden=!warnings.length;$('#application-warning').textContent=warnings.join(' · ');renderPeers(data);return data;}
function editRule(rule=null){state.editing=rule;const form=$('#edit-form');form.reset();$('#coverage-preview').replaceChildren();$('#batch-result').replaceChildren();form.elements.value.rows=(rule?.kind||state.view)==='manual'?6:1;form.elements.value.maxLength=(rule?.kind||state.view)==='manual'?(state.me.request_max_bytes||2097152):100;form.elements.value.value=rule?(rule.kind==='asn'?rule.asn:rule.prefix):'';form.elements.value.disabled=Boolean(rule);form.elements.comment.value=rule?.comment||'';const kind=rule?.kind||state.view;$('#edit-title').textContent=rule?(kind==='asn'?'Edit ASN':'Edit IP network'):(kind==='asn'?'Add ASN':'Add IP network');$('#value-caption').textContent=kind==='asn'?'ASN':'IP/CIDR';$('#editor').showModal();}
function userEditor(user=null){const form=$('#user-form');form.reset();form.elements.login.value=user?.id||'';form.elements.login.readOnly=Boolean(user);form.elements.role.value=user?.role||'guest';form.elements.enabled.checked=user?.enabled??true;form.elements.password.required=!user;$('#user-editor').showModal();}
function ruleActions(rule){const el=document.createElement('div');if(!writable())return text('small','Read-only');el.append(button('Edit comment',()=>editRule(rule)));if(rule.kind==='asn')el.append(button('Refresh IRR',async()=>{await api(`/api/rules/${rule.id}/refresh`,'POST');notice('IRR result saved. Review any proposal and application status.');await load();}));el.append(button('Delete',async()=>{if(confirm('Delete this rule? Prefixes required by other rules remain.')){await api(`/api/rules/${rule.id}`,'DELETE');await load();notice('Rule deletion saved. Route withdrawal is confirmed separately.');}},true));return el;}
async function prefixPages(root,rule,proposal=false){let pageNumber=1;const search=document.createElement('input');search.type='search';search.placeholder='Filter prefixes';search.setAttribute('aria-label','Filter rule prefixes');root.append(search);const content=document.createElement('div'),footer=document.createElement('div');footer.className='sub-pagination';root.append(content,footer);async function refresh(){const data=await api(`/api/rules/${rule.id}/prefixes?`+new URLSearchParams({proposal:String(proposal),q:search.value,page_number:pageNumber,size:25}));content.replaceChildren(table(['Prefix'],data.items.map(p=>[p])));pageNumber=data.page;renderPagination(footer,data,number=>{pageNumber=number;return refresh();});}search.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();pageNumber=1;action(refresh);}};await refresh();}
function ruleDetails(rule){return detail('Rule details',async root=>{root.append(fields([['Source',sourceName(rule)],['Comment',rule.comment||'—'],['Added by',rule.author],['Added',when(rule.created)],['Prefixes',rule.prefix_count],['Reference origins',(rule.origins||[]).map(o=>`AS${o.asn}${o.name?' — '+o.name:''}`).join(', ')||'Unknown'],['Last successful update',when(rule.last_success)],['Last error',rule.last_error||'None']]));if(rule.kind==='asn')root.append(detail('Accepted prefixes',body=>prefixPages(body,rule)));if(rule.pending){root.append(text('h3','Proposed update'),fields([['Prefixes',rule.pending.count],['Reason',rule.pending.reason],['Fetched',when(rule.pending.fetched)]]));await prefixPages(root,rule,true);if(writable())root.append(button('Confirm this proposed set',async()=>{if(confirm(`Apply this proposed set of ${rule.pending.count} prefixes?`)){await api(`/api/rules/${rule.id}/confirm`,'POST',{digest:rule.pending.digest});await load();notice('Proposed set saved. Application is confirmed separately.');}}));}});}
async function routeDetails(root,prefix){const data=await api('/api/route-detail?'+new URLSearchParams({prefix}));root.append(text('h3',data.prefix),fields([['State',routeStateLabel(data.state)],['Present in local GoBGP',data.local_rib==null?'Unknown':data.local_rib?'Yes':'No']]));root.append(text('h3','Source rules'),table(['Source','Comment','Added by','Added','Protection'],data.sources.map(s=>[s.source,s.comment||'—',s.author,when(s.added),s.excluded_reason||'Allowed'])));const attrs=data.configured_attributes;root.append(text('h3','Required attributes'),fields([['Next-hop',attrs.next_hop||'Not configured'],['Local preference',attrs.local_preference],['Communities',attrs.communities.join(', ')||'None']]));if(data.observed_attributes.length)root.append(text('h3','Observed local attributes'),table(['Next-hop','Local preference','Communities'],data.observed_attributes.map(p=>[p.next_hop,p.local_preference,p.communities.join(', ')])));root.append(text('h3','Export by peer'),table(['Peer','Export'],data.exports.map(p=>[p.peer,tag(p.state)])));}
function routeTable(items){const result=table(['Prefix','Source','Comment','Added','State'],[],'route-list'),body=result.querySelector('tbody');routeHeaders(result);body.replaceChildren();if(!items.length){body.append(table([''],[]).querySelector('tbody tr'));body.firstChild.firstChild.colSpan=5;return result;}for(const item of items){const row=document.createElement('tr'),expand=document.createElement('tr'),cell=document.createElement('td');expand.className='expanded-row';expand.hidden=true;cell.colSpan=5;expand.append(cell);const link=button(item.prefix,async()=>{expand.hidden=!expand.hidden;link.setAttribute('aria-expanded',String(!expand.hidden));if(!expand.hidden&&!cell.children.length)await routeDetails(cell,item.prefix);});link.className='route-link';link.setAttribute('aria-expanded','false');const first=item.sources[0];const sourceCell=document.createElement('div');sourceCell.append(text('span',first.source));if(item.sources.length>1)sourceCell.append(text('small',`+ ${item.sources.length-1} other reason${item.sources.length>2?'s':''} · expand prefix`));for(const value of [link,sourceCell,first.comment||'—',when(Math.min(...item.sources.map(s=>s.added))),routeStateTag(item.state)]){const td=document.createElement('td');value instanceof Node?td.append(value):td.textContent=value;row.append(td);}body.append(row,expand);}return result;}
function readableValue(value){return value&&typeof value==='object'&&'timestamp' in value?when(value.timestamp):String(value??'—');}
function renderInfo(root){
  const page=document.createElement('div');page.className='info-page';page.lang=state.infoLanguage;
  const controls=document.createElement('div');controls.className='language-switch';
  for(const language of ['en','ru','uk']){const control=button(language==='uk'?'UK':language.toUpperCase(),()=>{state.infoLanguage=language;root.replaceChildren();renderInfo(root);});control.setAttribute('aria-pressed',String(state.infoLanguage===language));controls.append(control);}
  const data=infoTexts[state.infoLanguage],labels=data.protectionLabels;page.append(controls,text('h2',data.title));
  for(const [title,blocks] of data.sections){
    const section=document.createElement('section');section.className='info-section';section.append(text('h2',title));
    for(const block of blocks){
      if(typeof block==='string')section.append(text('p',block));
      else if(block.list){const list=document.createElement('ol');for(const item of block.list)list.append(text('li',item));section.append(list);}
      else if(block.note)section.append(text('p',block.note,'section-notice'));
      else if(block.states){const rows=table([labels.state,labels.meaning],block.states,'info-states');section.append(rows);}
      else if(block.protection){const protection=document.createElement('div');protection.className='info-protection';section.append(protection);action(()=>infoProtection(protection,labels));}
    }page.append(section);
  }root.append(page);
}
async function infoProtection(root,labels){
  root.replaceChildren(text('p',labels.loading,'muted'));
  try{
    const summary=await api('/api/info/protection');if(!root.isConnected)return;
    root.replaceChildren(text('h3',`${labels.node}: ${summary.node_id}`),text('p',labels.loaded,'muted'));
    for(const [kind,title,count] of [['asns',labels.asns,summary.asn_count],['prefixes',labels.prefixes,summary.prefix_count]]){
      const list=detail(`${title} (${count})`,async body=>{
        let number=1;const filter=document.createElement('input');filter.type='search';filter.placeholder=labels.filter;filter.setAttribute('aria-label',`${labels.filter}: ${title}`);
        const content=document.createElement('div'),footer=document.createElement('div');footer.className='sub-pagination';body.append(filter,content,footer);
        async function refresh(){
          try{const data=await api('/api/info/protection?'+new URLSearchParams({kind,q:filter.value,page_number:number,size:25}));number=data.page;
            const rows=kind==='asns'?data.items.map(item=>['AS'+item.asn,item.last_success?when(item.last_success):labels.never]):data.items.map(item=>[item.prefix,item.sources.map(source=>labels[source]).join(' + ')]);
            const result=table(kind==='asns'?[labels.asn,labels.success]:[labels.prefix,labels.source],rows);
            if(!rows.length)result.querySelector('td').textContent=labels.empty;content.replaceChildren(result);
            const pages=Math.ceil(data.total/data.size),label=data.total?`${labels.page} ${data.page} ${labels.of} ${pages} · ${labels.showing} ${(data.page-1)*data.size+1}–${Math.min(data.page*data.size,data.total)} ${labels.of} ${data.total}`:labels.empty;
            const control=(name,page,disabled)=>{const el=button(labels[name],()=>{number=page;return refresh();});el.disabled=disabled;el.dataset.pageAction=name;return el;};
            footer.replaceChildren(control('first',1,!data.total||number<=1),control('previous',number-1,!data.total||number<=1),text('span',label),control('next',number+1,!data.total||number>=pages),control('last',pages,!data.total||number>=pages));
          }catch{content.replaceChildren(text('p',labels.error,'danger'));footer.replaceChildren();}
        }
        filter.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();number=1;action(refresh);}};await refresh();
      });list.dataset.protectionKind=kind;root.append(list);
    }
  }catch{root.replaceChildren(text('p',labels.error,'danger'));}
}
async function load(){if(!state.me)return;const generation=++state.generation;$('#title').textContent=titles[state.view];document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===state.view));$('#read-only').hidden=writable()||['info','users'].includes(state.view);$('#add').hidden=!writable()||!['asn','manual','users'].includes(state.view);$('#pagination').hidden=state.view==='info';$('.toolbar').hidden=state.view==='info';$('.metrics').hidden=state.view!=='dashboard';$('#search-mode-label').hidden=state.view!=='dashboard';$('#search').placeholder=state.view==='dashboard'?'Search prefixes, sources, comments or an IP address':'Search this table';const content=$('#content');content.replaceChildren();if(state.view==='info'){renderInfo(content);$('#notice').hidden=true;return;}let data;
  const query=new URLSearchParams({q:$('#search').value,page_number:state.page,size:state.size});
  if(state.view==='dashboard'){query.set('sort',state.sort);query.set('direction',state.direction);const sessions=document.createElement('section');sessions.id='sessions';content.append(sessions);const term=$('#search').value.trim();if(term&&$('#search-mode').value==='ip'){query.delete('q');query.set('ip',term);}data=await api('/api/routes?'+query);if(generation!==state.generation)return;content.append(text('h2',term?(data.total?`Matches found: ${data.total}`:'No matches'):'Routes',term?'search-result':''));content.append(routeTable(data.items));
  }else if(['asn','manual'].includes(state.view)){query.set('kind',state.view);data=await api('/api/rule-cards?'+query);if(generation!==state.generation)return;content.append(table(['Source / prefix','Comment','Added','Update','Actions'],data.items.map(rule=>{const object=document.createElement('div');object.dataset.ruleId=rule.id;object.append(text('strong',rule.kind==='asn'?sourceName(rule):rule.prefix),text('small',`${rule.prefix_count} prefix${rule.prefix_count===1?'':'es'}`),ruleDetails(rule));if(rule.kind==='manual')object.append(coverageBadges(rule.coverage,rule.prefix,rule.id));return[object,rule.comment||'—',`${rule.author}\n${when(rule.created)}`,`${when(rule.last_success)}${rule.last_error?'\n'+rule.last_error:''}${rule.pending?'\nAwaiting confirmation':''}`,ruleActions(rule)];})));
  }else if(state.view==='audit'){
    const tabs=document.createElement('div');tabs.className='history-tabs';tabs.setAttribute('role','tablist');
    for(const [key,label] of [['blocklist','Blocklist changes'],['users_access','Users & access'],['errors_security','Errors & security']]){if(state.me.role!=='admin'&&key!=='blocklist')continue;const tab=button(label,()=>{state.historyCategory=key;state.page=1;return load();});tab.setAttribute('role','tab');tab.setAttribute('aria-selected',String(state.historyCategory===key));tabs.append(tab);}content.append(tabs);
    if(state.me.role!=='admin')state.historyCategory='blocklist';
    const filters=document.createElement('form');filters.className='history-filters';
    for(const [key,label,type] of [['who','Actor','text'],['node','Node','text'],['action','Action','text'],['result','Result','text'],['since','From (local time)','datetime-local'],['until','Before (local time)','datetime-local']]){const field=document.createElement('input');field.name=key;field.type=type;field.placeholder=label;field.setAttribute('aria-label',label);field.value=state.historyFilters[key]||'';const labelElement=document.createElement('label');labelElement.append(text('span',label),field);filters.append(labelElement);}
    const apply=text('button','Apply filters');apply.type='submit';filters.append(apply);filters.onsubmit=e=>{e.preventDefault();state.historyFilters=Object.fromEntries(new FormData(filters));state.page=1;action(load);};content.append(filters);
    query.set('category',state.historyCategory);for(const [key,value] of Object.entries(state.historyFilters)){if(value)query.set(key,['since','until'].includes(key)?String(new Date(value).getTime()/1000):value);}
    data=await api('/api/history?'+query);if(generation!==state.generation)return;content.append(table(['When / node','Who','Action / object','Result','Changes'],data.items.map(entry=>[`${when(entry.at)}\n${entry.node}`,entry.actor,`${entry.action}\n${entry.target}`,entry.result,detail('Before / After',body=>{body.append(entry.changes.length?table(['Field','Before','After'],entry.changes.map(c=>[c.field,readableValue(c.before),readableValue(c.after)])):text('p','No field changes recorded.','muted'));})])));
  }else{const own=document.createElement('section');own.className='own-account';content.append(own);await ownAccount(own);if(generation!==state.generation)return;
    if(state.me.role!=='admin'){$('#pagination').hidden=true;$('.toolbar').hidden=true;return;}
    data=await api('/api/users?'+query);if(generation!==state.generation)return;content.append(text('h2','User management'),table(['Login','Role','Status','Actions'],data.items.map(u=>{const controls=document.createElement('div');if(writable())controls.append(button('Edit',()=>userEditor(u)));else controls.append(text('small','Read-only'));controls.append(button('Login history',()=>showLoginHistory(u.id)));return[u.id,u.role,u.enabled?'Enabled':'Disabled',controls];})));}
  state.total=data.total;state.page=data.page;renderPagination($('#pagination'),data,number=>{state.page=number;return load();});if(state.view==='dashboard')await metrics();if($('#notice').classList.contains('error'))$('#notice').hidden=true;
}
function showVersion(application){const label=$('#app-version');label.textContent=application?.version?`Hemlock v${application.version}`:'Hemlock · Version unavailable';label.title=application?.build_commit?`Build commit: ${application.build_commit}`:'';label.hidden=false;}
async function session(){state.me=await api('/api/me');showVersion(state.me.application);state.csrf=state.me.csrf;$('#login-panel').hidden=true;document.body.classList.remove('signed-out');$('#navigation').hidden=false;$('#app-header').hidden=false;$('#workspace').hidden=false;clearInterval(refreshTimer);refreshTimer=setInterval(()=>action(refreshSession),20000);$('#logout').hidden=false;document.querySelector('nav button[data-view=users]').hidden=false;$('#identity').textContent=`${state.me.login} · ${state.me.role}`;$('#node').textContent=`${state.me.node_id} / ${state.me.node_role}`;const requested=location.hash.slice(1)==='observation'?'dashboard':location.hash.slice(1);if(titles[requested])state.view=requested;await load();}
$('#login-form').onsubmit=event=>{event.preventDefault();action(async()=>{const form=event.target;const data=await api('/api/login','POST',{login:form.elements.login.value,password:form.elements.password.value});form.reset();state.csrf=data.csrf;await session();$('#notice').hidden=true;});};
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>action(async()=>{state.view=b.dataset.view;location.hash=state.view;state.page=1;$('#search').value='';await load();}));
$('#reload').onclick=()=>action(load);$('#search').onkeydown=event=>{if(event.key==='Enter'){clearTimeout(searchTimer);state.page=1;action(load);}};$('#search-mode').onchange=()=>{state.page=1;action(load);};
$('#add').onclick=()=>state.view==='users'?userEditor():editRule();
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('close',()=>dialog.querySelectorAll('.dialog-notice').forEach(alert=>alert.remove())));document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$('#'+b.dataset.close).close());
$('#edit-form').onsubmit=event=>{event.preventDefault();action(async()=>{const form=event.target;const submit=form.querySelector('button.primary');submit.disabled=true;try{
  if(!state.editing&&state.view==='manual'){
    const data=await api('/api/rules/manual-batch','POST',{value:form.elements.value.value,comment:form.elements.comment.value});
    form.elements.value.value=data.items.filter(item=>item.status!=='added').map(item=>item.input).join('\n');
    const summary=`Added: ${data.added} · Skipped: ${data.skipped} · Invalid: ${data.invalid}${data.unconfirmed?' · Unconfirmed: '+data.unconfirmed:''}`;
    const root=$('#batch-result');root.replaceChildren(text('p',summary));const list=document.createElement('ul');
    for(const item of data.items.filter(item=>item.status!=='added')){const row=text('li',`${item.input}: ${item.reason}`);if(item.rule_id)row.append(document.createTextNode(' '),button('Open existing record',()=>openRecord(item.rule_id)));list.append(row);}root.append(list);
    if(data.error)root.append(text('p',data.error,'danger'));
    $('#coverage-preview').replaceChildren();await load();return;
  }
  if(state.editing)await api('/api/rules/'+state.editing.id,'PATCH',{comment:form.elements.comment.value});else await api('/api/rules/'+state.view,'POST',{value:form.elements.value.value,comment:form.elements.comment.value});$('#editor').close();form.reset();await load();notice('Rule saved. Replication and application are confirmed separately.');
}finally{submit.disabled=false;}});};
$('#user-form').onsubmit=event=>{event.preventDefault();action(async()=>{const form=event.target;const body={role:form.elements.role.value,enabled:form.elements.enabled.checked};if(form.elements.password.value)body.password=form.elements.password.value;await api('/api/users/'+encodeURIComponent(form.elements.login.value),'PUT',body);form.reset();$('#user-editor').close();await load();notice('Account saved. Previous sessions are revoked after replication.');});};
$('#password-form').onsubmit=event=>{event.preventDefault();action(async()=>{const form=event.target;if(form.elements.new_password.value!==form.elements.repeat.value)throw new Error('Passwords do not match');await api('/api/password','POST',{current_password:form.elements.current_password.value,new_password:form.elements.new_password.value});form.reset();location.reload();});};
$('#logout').onclick=()=>action(async()=>{const pending=api('/api/logout','POST');showLogin();$('#login-form').reset();await pending;});
function themeAction(){const dark=document.documentElement.dataset.theme==='dark';$('#theme').textContent=dark?'☀':'☾';$('#theme').title=dark?'Switch to light theme':'Switch to dark theme';$('#theme').setAttribute('aria-label',$('#theme').title);}
$('#theme').onclick=()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;try{localStorage.setItem('hemloc-theme',theme);}catch{}themeAction();};themeAction();
api('/api/session').then(auth=>{if(auth.authenticated)return session();}).catch(error=>notice(error.message,true));

window.addEventListener('hashchange',()=>{const requested=location.hash.slice(1)==='observation'?'dashboard':location.hash.slice(1);if(state.me&&titles[requested]&&requested!==state.view){state.view=requested;state.page=1;$('#search').value='';action(load);}});
async function refreshVisibleRoutes(){
  if(state.view!=='dashboard'||!$('.route-list'))return;
  const generation=state.generation,query=new URLSearchParams({page_number:state.page,size:state.size,sort:state.sort,direction:state.direction});
  const term=$('#search').value.trim();if(term)query.set($('#search-mode').value==='ip'?'ip':'q',term);
  const data=await api('/api/routes?'+query);if(generation!==state.generation||state.view!=='dashboard')return;
  if(data.total!==state.total||data.page!==state.page){await load();return;}
  const current=$('.route-list');if(!current)return;
  const open=[...current.querySelectorAll('.expanded-row:not([hidden])')];
  const prefixes=[...current.querySelectorAll('.route-link')].map(el=>el.textContent);if(prefixes.join('|')!==data.items.map(item=>item.prefix).join('|')){current.replaceWith(routeTable(data.items));return;}
  if(!open.length){current.replaceWith(routeTable(data.items));return;}
  for(const row of current.querySelectorAll('tbody>tr:not(.expanded-row)')){
    const link=row.querySelector('.route-link');if(!link)continue;
    const fresh=data.items.find(item=>item.prefix===link.textContent);row.lastElementChild.replaceChildren(routeStateTag(fresh?.state||'Unknown'));
  }
  for(const expanded of open){const candidate=expanded.previousElementSibling.querySelector('.route-link').textContent;const body=document.createElement('div');await routeDetails(body,candidate);if(generation===state.generation&&expanded.isConnected)expanded.firstChild.replaceChildren(body);}
}

function renderPagination(root,data,change){
  root.replaceChildren();const pages=Math.ceil(data.total/data.size);
  const main=root.id==='pagination';
  const control=(label,number,disabled,id)=>{const b=button(label,()=>change(number));b.disabled=disabled;if(main)b.id=id;return b;};
  const first=control('First',1,!data.total||data.page<=1,'first'),previous=control('Previous',data.page-1,!data.total||data.page<=1,'previous');
  const next=control('Next',data.page+1,!data.total||data.page>=pages,'next'),last=control('Last',pages,!data.total||data.page>=pages,'last');
  const label=text('span',data.total?`Page ${data.page} of ${pages} · Showing ${(data.page-1)*data.size+1}–${Math.min(data.page*data.size,data.total)} of ${data.total}`:'No results');if(main)label.id='page-label';
  root.append(first,previous,label,next,last);
}
async function openRecord(id){
  const rule=await api('/api/rule-card/'+encodeURIComponent(id));
  document.querySelectorAll('dialog[open]').forEach(d=>d.close());state.view=rule.kind;location.hash=state.view;state.page=1;
  $('#search').value=rule.kind==='asn'?String(rule.asn):rule.prefix;await load();
  const root=[...document.querySelectorAll('[data-rule-id]')].find(e=>e.dataset.ruleId===id);
  if(root){root.querySelector('details').open=true;root.scrollIntoView({block:'center'});root.classList.add('record-focus');}
}
function coverageBadges(badges,value,own=''){
  const root=document.createElement('div');root.className='coverage-badges';
  for(const badge of badges||[]){
    const item=detail(badge.label,async body=>{
      let number=1;const content=document.createElement('div'),footer=document.createElement('div');footer.className='sub-pagination';body.append(content,footer);
      async function refresh(){const data=await api('/api/coverage?'+new URLSearchParams({value,rule_id:own,relation:badge.relation,page_number:number,size:10}));number=data.page;
        content.replaceChildren(table(['Rule','Comment','Added by',''],data.items.map(r=>[r.kind==='asn'?sourceName(r):r.prefix,r.comment||'—',r.author,button('Open record',()=>openRecord(r.id))])));
        renderPagination(footer,data,n=>{number=n;return refresh();});
      }await refresh();
    });item.className='coverage '+(badge.relation==='asn'?'coverage-amber':'coverage-blue');root.append(item);
  }return root;
}
let previewGeneration=0,previewTimer;
$('#edit-form').elements.value.addEventListener('input',()=>{
  clearTimeout(previewTimer);const generation=++previewGeneration;$('#coverage-preview').replaceChildren();
  if(state.view!=='manual'||state.editing)return;
  const value=$('#edit-form').elements.value.value.trim();if(!value)return;
  previewTimer=setTimeout(async()=>{try{const data=await api('/api/coverage/batch','POST',{value});if(generation!==previewGeneration||!state.me)return;const root=$('#coverage-preview');root.replaceChildren(text('small',`Coverage preview: ${data.items.length} of ${data.total}; ${data.covered} covered; ${data.invalid} invalid. Blocking rules only, not remote installation.`,'muted'));for(const item of data.items){if(item.error)root.append(text('p',item.error,'danger'));if(item.badges.length){const row=document.createElement('div');row.append(text('span',item.prefix),coverageBadges(item.badges,item.prefix));root.append(row);}}}catch(error){if(generation===previewGeneration)$('#coverage-preview').replaceChildren(text('small',error.message,'muted'));}},250);
});
let searchTimer;
$('#search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.page=1;action(load);},300);});

async function refreshCoverage(){
  const generation=state.generation,query=new URLSearchParams({kind:'manual',q:$('#search').value,page_number:state.page,size:state.size});
  const data=await api('/api/rule-cards?'+query);if(generation!==state.generation)return;
  if(data.total!==state.total||data.page!==state.page){await load();return;}
  for(const rule of data.items){const root=[...document.querySelectorAll('[data-rule-id]')].find(el=>el.dataset.ruleId===rule.id);if(!root){await load();return;}
    const badges=root.querySelector('.coverage-badges');if(badges)badges.replaceWith(coverageBadges(rule.coverage,rule.prefix,rule.id));
  }
}

function routeStateLabel(value){return {Applied:'Applied locally',Pending:'Pending locally',Failed:'Application failed'}[value]||value;}
function routeStateTag(value){const el=tag(value);el.textContent=routeStateLabel(value);el.title=routeStateDescriptions[value]||'No current observation.';return el;}
function routeHeaders(table){
  const headers=table.querySelectorAll('thead th');
  for(const [index,key] of ['prefix','source','comment','added'].entries()){
    const active=state.sort===key,header=headers[index],label=header.textContent;
    header.setAttribute('aria-sort',active?(state.direction==='asc'?'ascending':'descending'):'none');
    const control=button(label+(active?(state.direction==='asc'?' ↑':' ↓'):''),async()=>{state.direction=state.sort===key&&state.direction==='asc'?'desc':'asc';state.sort=key;state.page=1;await load();});
    control.className='sort-control';control.title='Sort by '+label;header.replaceChildren(control);
  }
  const help=button('State ⓘ',()=>{
    const dialog=document.createElement('dialog');dialog.className='state-dialog';dialog.append(text('h2','Route State'),text('p',stateSummary));
    for(const [key,value] of Object.entries(routeStateDescriptions))dialog.append(text('h3',routeStateLabel(key)),text('p',value));
    dialog.append(button('Close',()=>dialog.close()));dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal();
  });help.className='sort-control';help.title=stateSummary;help.setAttribute('aria-label','State help');headers[4].replaceChildren(help);
}
async function loginHistory(root,login){
  const data=await api('/api/login-history?'+new URLSearchParams({login}));
  root.replaceChildren(text('h3','Last 5 successful logins'),table(['Time','IP address','Node'],data.items.map(item=>[when(item.at),item.ip||'Unknown (not recorded)',item.node])));
  if(!data.items.length)root.append(text('p','No successful logins recorded.','muted'));
  root.append(text('p',`${data.scope} Peer: ${data.peer.name} · ${data.peer.status}. Last successful sync: ${data.peer.last_success?when(data.peer.last_success):'Unknown'}.`,'muted login-freshness'));
}
async function ownAccount(root){
  root.append(text('h2','Your account'),fields([['Login',state.me.login],['Role',state.me.role]]));
  const control=button('Change password',()=>$('#password-editor').showModal());control.id='password-button';control.disabled=state.me.node_role!=='master';root.append(control);
  if(control.disabled)root.append(text('p',`Password changes are available on the master (${state.me.password_change_node}). Sign in there to change your password.`,'muted'));
  else root.append(text('p','Changing your password requires your current password.','muted'));
  const history=document.createElement('div');history.className='own-login-history';root.append(history);await loginHistory(history,state.me.login);
}
async function showLoginHistory(login){
  const dialog=document.createElement('dialog');dialog.className='login-history-dialog';dialog.append(text('h2','Login history — '+login));
  const root=document.createElement('div');dialog.append(root,button('Close',()=>dialog.close()));dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal();await loginHistory(root,login);
}
