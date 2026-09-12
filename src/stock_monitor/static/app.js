const state={sectors:[],concepts:[],selected:null,chart:null,stocks:[],market:'all',heatKind:'industry',period:1};
const $=s=>document.querySelector(s);
const money=v=>v==null?'—':v>=1e8?`${(v/1e8).toFixed(1)}亿`:`${(v/1e4).toFixed(0)}万`;
const pct=v=>v==null?'—':`${v>0?'+':''}${Number(v).toFixed(2)}%`;
const cls=v=>v>0?'up':v<0?'down':'';
const signed=v=>v==null?'—':`${v>0?'+':''}${Number(v).toFixed(2)}`;
const marketMoney=v=>v==null?'—':Math.abs(v)>=1e12?`${(Math.abs(v)/1e12).toFixed(3)}万亿`:`${(Math.abs(v)/1e8).toFixed(0)}亿`;
const flowMoney=v=>{if(v==null)return '—';const a=Math.abs(Number(v)),s=v>0?'+':v<0?'-':'';return s+(a>=1e8?(a/1e8).toFixed(2)+'亿':a>=1e4?(a/1e4).toFixed(0)+'万':a.toFixed(0))};
const flowPage=(kind,period)=>`https://data.eastmoney.com/bkzj/${kind==='industry'?'hy':'gn'}.html?stat=${period}`;
function toast(text){const el=$('#toast');el.textContent=text;el.style.display='block';setTimeout(()=>el.style.display='none',4000)}
async function json(url,options){const res=await fetch(url,options);if(!res.ok){const x=await res.json().catch(()=>({}));throw new Error(x.detail||`请求失败 ${res.status}`)}return res.json()}
let loadVersion=0;
async function load(period=state.period){
  const version=++loadVersion;
  state.period=period;
  const [overview,sectors,concepts]=await Promise.all([json('/api/overview'),json(`/api/sectors?period=${period}&sector_type=industry`),json(`/api/sectors?period=${period}&sector_type=concept`)]);
  if(version!==loadVersion)return;
  state.sectors=sectors.items;
  state.concepts=concepts.items;
  const src=overview.sources||{};
  state.sources=src;
  const sectorSource=sectors.source||'东方财富 · 板块资金流';
  const conceptSource=concepts.source||'东方财富 · 板块资金流';
  $('#sources').textContent=`来源：板块 ${sectorSource} · 个股 ${src.stocks||'—'} · 指数 ${src.indices||'—'}`;
  const stamp=v=>v?new Date(v).toLocaleString():'暂无数据';
  $('#stamp').textContent=`更新：行业 ${stamp(sectors.collected_at)} · 概念 ${stamp(concepts.collected_at)}`;
  drawHeatmap();
  loadShanghaiIndex();
}
async function loadShanghaiIndex(){
  try{
    const x=await json('/api/market-summary');
    $('#sh-index-close').textContent=x&&x.close!=null?Number(x.close).toFixed(2):'—';
    $('#sh-index-change').textContent=x?`${signed(x.change_points)}  ${pct(x.pct_change)}`:'—';
    $('#sh-index').className=x?cls(x.pct_change):'';
    for(const key of ['up','flat','down'])$(`#breadth-${key}`).textContent=x?x[key]:'—';
    $('#market-amount').textContent=marketMoney(x?.amount_yuan);
    const delta=x?.amount_change_yuan;
    $('#amount-change-label').textContent=delta==null?'比昨日':delta>0?'比昨日放量':delta<0?'比昨日缩量':'比昨日持平';
    $('#amount-change').textContent=marketMoney(delta);
    $('#amount-change-wrap').className=cls(delta);
    const referenceTime=x?.reference_time?new Date(String(x.reference_time).replace(' ','T')).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}):null;
    $('#sh-index-stamp').textContent=x?`行情 ${referenceTime||x.reference_time}`:'暂无缓存，请刷新';
  }catch(e){$('#sh-index-stamp').textContent=`指数读取失败：${e.message}`}
}
function drawHeatmap(){
  const kindText=state.heatKind==='concept'?'概念':'行业',periodText=state.period===1?'今日':state.period+'日';
  $('#heat-title').textContent=`${kindText}资金`;
  $('#heat-legend').innerHTML=`面积＝主力净额｜红入绿出｜<a class="source-link" href="${flowPage(state.heatKind,state.period)}" target="_blank" rel="noopener noreferrer">${periodText} · 东方财富</a>`;
  const items=(state.heatKind==='concept'?state.concepts:state.sectors).slice(0,20);
  const container=$('#heatmap');
  if(!state.chart)state.chart=echarts.init(container);
  state.chart.clear();
  state.chart.off('click');
  if(!items.length){state.chart.setOption({title:{text:'当前周期暂无板块数据',textStyle:{color:'#8fa0b8'}}});return}
  const weights=items.map(x=>Math.sqrt(Math.abs(Number(x.net_flow)||0)));
  const floor=Math.max(...weights,1)/6;
  const data=items.map((x,i)=>({name:x.name,code:x.code,flow:x.net_flow,direction:x.flow_direction,rank:x.flow_rank,pct:x.pct_change,value:Math.max(weights[i],floor),itemStyle:{color:x.net_flow>0?'#a8323d':x.net_flow<0?'#116b62':'#39465c'}}));
  state.chart.setOption({tooltip:{formatter:p=>`${escapeHTML(p.name)}<br>涨跌幅 ${pct(p.data.pct)}<br>主力净额 ${flowMoney(p.data.flow)}<br>${p.data.direction==='in'?'净流入':'净流出'}第 ${p.data.rank} 名<br>面积按净额绝对值压缩`},series:[{type:'treemap',left:0,right:0,top:0,bottom:0,roam:false,nodeClick:false,breadcrumb:{show:false},visibleMin:0,squareRatio:1,label:{show:true,fontSize:13,lineHeight:18,color:'#fff',overflow:'break',formatter:p=>`${p.name.match(/.{1,6}/gu).join('\n')}\n${pct(p.data.pct)}\n${flowMoney(p.data.flow)}`},itemStyle:{borderColor:'#09101c',borderWidth:2,gapWidth:3},data}]});
  state.chart.on('click',p=>selectSector(p.data.code,p.name,state.heatKind));
}
function stockMarket(code){
  const digits=String(code||'').replace(/\D/g,'').slice(-6);
  if(/^(688|689)/.test(digits)) return 'star';
  if(/^(300|301)/.test(digits)) return 'gem';
  if(/^(4|8|92)/.test(digits)) return 'bse';
  return 'main';
}
function renderStocks(){
  const excludeST=$('#exclude-st').checked;
  const items=state.stocks.filter(x=>(state.market==='all'||stockMarket(x.code)===state.market)&&(!excludeST||!String(x.name).toUpperCase().includes('ST')));
  const labels={all:'全部市场',main:'主板（普通）',gem:'创业板',star:'科创板',bse:'北交所'};
  const code=state.selected?.code||'';
  const provider=/^(881|308|309|301)/.test(code)?'同花顺旧板块缓存':code.startsWith('BK')?'东方财富':'未知来源';
  $('#detail-meta').textContent=`${provider} · ${items.length}/${state.stocks.length}只 · ${labels[state.market]} · 涨幅排序`;
  $('#stocks').innerHTML=items.map(x=>`<tr><td>${x.code}</td><td>${x.name}</td><td class="num ${cls(x.pct_change)}">${pct(x.pct_change)}</td><td class="num">${x.close??'—'}</td><td class="num">${money(x.amount)}</td><td class="num">${pct(x.turnover)}</td><td class="num">${x.pe?.toFixed?.(1)??'—'}</td><td><button data-stock="${x.code}" data-name="${x.name}">关注</button></td></tr>`).join('')||'<tr><td colspan="8" class="empty">当前筛选条件下没有股票</td></tr>';
  document.querySelectorAll('[data-stock]').forEach(b=>b.onclick=()=>addWatch('stock',b.dataset.stock,b.dataset.name));
}
async function selectSector(code,name,type='industry'){
  state.selected={code,name,type};$('#detail-name').textContent=`${name} · ${type==='concept'?'概念':'行业'}`;$('#detail-meta').textContent='正在读取板块成分股…';$('#watch-sector').disabled=false;
  try{const data=await json(`/api/sectors/${encodeURIComponent(code)}/stocks`);data.items.sort((a,b)=>(b.pct_change||0)-(a.pct_change||0));state.stocks=data.items;renderStocks();
  }catch(e){$('#detail-meta').textContent='成分股读取失败';$('#stocks').innerHTML=`<tr><td colspan="8" class="empty">${e.message}</td></tr>`}
}
async function addWatch(type,code,name){await json('/api/watchlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_type:type,item_code:code,item_name:name})});toast(`已将“${name}”加入3个月关注池`)}
let watchItems=[], watchLinks=[], watchSelection=null;
const watchSort={sector:'desc',stock:'desc'};
const watchGroup=item=>item.item_type==='stock'?'stock':'sector';
const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function renderWatch(){
  const selected=watchItems.find(x=>watchSelection===x.item_type+'|'+x.item_code);
  let relatedCount=0;
  for(const kind of ['sector','stock']){
    const items=watchItems.map((item,index)=>({item,index})).filter(x=>watchGroup(x.item)===kind);
    const direction=watchSort[kind];
    items.sort((a,b)=>{
      const pinDifference=Number(Boolean(b.item.pinned))-Number(Boolean(a.item.pinned));
      if(pinDifference)return pinDifference;
      const av=Number(a.item.current_pct),bv=Number(b.item.current_pct);
      const aMissing=a.item.current_pct==null||!Number.isFinite(av),bMissing=b.item.current_pct==null||!Number.isFinite(bv);
      if(aMissing!==bMissing)return aMissing?1:-1;
      if(aMissing)return a.index-b.index;
      return direction==='desc'?bv-av:av-bv;
    });
    const sortButton=$(`[data-watch-sort="${kind}"]`);
    sortButton.textContent=`今日涨跌 ${direction==='desc'?'▼':'▲'}`;
    sortButton.title=direction==='desc'?'当前从高到低；点击改为从低到高':'当前从低到高；点击改为从高到低';
    $(`#watch-${kind}-sort-head`).setAttribute('aria-sort',direction==='desc'?'descending':'ascending');
    $(`#watch-${kind}-count`).textContent=`${kind==='stock'?'个股':'板块'}（${items.length}）`;
    $(`#watch-${kind}s`).innerHTML=items.map(({item:x,index:i})=>{
      const isSelected=selected===x;
      const linked=selected&&watchGroup(selected)!==kind&&watchLinks.some(l=>kind==='stock'?(l.sector_code===selected.item_code&&l.stock_code===x.item_code):(l.stock_code===selected.item_code&&l.sector_code===x.item_code));
      if(linked)relatedCount++;
      const price=x.current_price==null?'—':Number(x.current_price).toFixed(2);
      const rowClass=[x.pinned?'watch-pinned':'',isSelected?'watch-selected':linked?'watch-linked':''].filter(Boolean).join(' ');
      const nameAction=kind==='stock'
        ? `data-stock-quick="${i}" title="打开个股速览"`
        : `data-watch-select="${i}" aria-pressed="${isSelected}" title="选择板块并高亮关联个股"`;
      return `<tr class="${rowClass}" data-watch-row="${i}"><td><button ${nameAction}>${escapeHTML(x.item_name)}<small>${escapeHTML(x.item_code)}${isSelected?' · 已选':linked?' · 关联':''}</small></button></td><td class="num watch-price ${cls(x.current_pct)}">${price}</td><td class="num watch-change ${cls(x.current_pct)}">${pct(x.current_pct)}</td><td>${x.expires_at?new Date(x.expires_at).toLocaleDateString():'—'}</td><td><details class="watch-more"><summary>更多</summary><div class="watch-menu"><button data-pin="${i}" data-pinned="${x.pinned?'false':'true'}">${x.pinned?'取消置顶':'置顶'}</button><button data-extend="${i}" data-period="15d">延长15天</button><button data-extend="${i}" data-period="1m">延长1个月</button><button class="remove" data-remove="${i}">移除</button></div></details></td></tr>`;
    }).join('')||'<tr><td colspan="5" class="empty">暂无关注记录</td></tr>';
  }
  $('#watch-link-status').textContent=selected?`${selected.item_name}：关联 ${relatedCount} 项（绿色）`:'';
  $('#watch-link-status').hidden=!selected;
  const toggleWatchSelection=i=>{const x=watchItems[Number(i)];const key=x.item_type+'|'+x.item_code;watchSelection=watchSelection===key?null:key;renderWatch()};
  document.querySelectorAll('[data-watch-select]').forEach(b=>b.onclick=()=>toggleWatchSelection(b.dataset.watchSelect));
  document.querySelectorAll('[data-stock-quick]').forEach(b=>b.onclick=()=>{const x=watchItems[Number(b.dataset.stockQuick)];openStockDetail(x.item_code)});
  document.querySelectorAll('[data-watch-row]').forEach(row=>row.onclick=event=>{if(!event.target.closest('button,summary,details,a'))toggleWatchSelection(row.dataset.watchRow)});
  document.querySelectorAll('[data-pin]').forEach(b=>b.onclick=async()=>{
    const item=watchItems[Number(b.dataset.pin)],pinned=b.dataset.pinned==='true';b.disabled=true;
    try{await json(`/api/watchlist/${encodeURIComponent(item.item_type)}/${encodeURIComponent(item.item_code)}/pin?pinned=${pinned}`,{method:'POST'});await loadWatch();toast(pinned?'已置顶':'已取消置顶')}
    catch(e){toast(e.message);b.disabled=false}
  });
  document.querySelectorAll('[data-extend]').forEach(b=>b.onclick=async()=>{
    const item=watchItems[Number(b.dataset.extend)],label=b.dataset.period==='15d'?'15天':'1个月';
    b.disabled=true;
    try{await json(`/api/watchlist/${encodeURIComponent(item.item_type)}/${encodeURIComponent(item.item_code)}/extend?period=${b.dataset.period}`,{method:'POST'});await loadWatch();toast(`已延长${label}`)}
    catch(e){toast(e.message);b.disabled=false}
  });
  document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=async()=>{
    const item=watchItems[Number(b.dataset.remove)];
    b.disabled=true;
    try{await json(`/api/watchlist/${encodeURIComponent(item.item_type)}/${encodeURIComponent(item.item_code)}`,{method:'DELETE'});await loadWatch()}
    catch(e){toast(e.message);b.disabled=false}
  });
}
async function loadWatch(){
  try{const data=await json('/api/watchlist?quotes=true');watchItems=data.items;watchLinks=data.links||[];renderWatch()}
  catch(e){toast(e.message)}
}
$('#clear-watch-selection').onclick=()=>{watchSelection=null;renderWatch()};
document.querySelectorAll('[data-watch-sort]').forEach(b=>b.onclick=()=>{const kind=b.dataset.watchSort;watchSort[kind]=watchSort[kind]==='desc'?'asc':'desc';renderWatch()});
$('#refresh-watch-links').onclick=async()=>{const b=$('#refresh-watch-links');b.disabled=true;b.textContent='读取关联中…';try{const data=await json('/api/watchlist/refresh-links',{method:'POST'});await loadWatch();toast(data.warnings.length?data.warnings.join('；'):'关联已更新')}catch(e){toast(e.message)}finally{b.disabled=false;b.textContent='更新关联'}};
$('#refresh').onclick=async()=>{const b=$('#refresh');b.disabled=true;b.textContent='刷新中…';try{const x=await json('/api/refresh',{method:'POST'});await load();const failed=x.results.filter(r=>!r.ok);toast(failed.length?`完成 ${x.results.length-failed.length}/${x.results.length}｜失败：${failed.map(r=>r.module).join('、')}`:'基础行情刷新成功')}catch(e){toast(`刷新失败：${e.message}`)}finally{b.disabled=false;b.textContent='立即刷新'}};
$('#watch-sector').onclick=()=>state.selected&&addWatch('sector',state.selected.code,state.selected.name);
document.querySelectorAll('.market').forEach(b=>b.onclick=()=>{state.market=b.dataset.market;document.querySelectorAll('.market').forEach(x=>x.classList.toggle('active',x===b));renderStocks()});
$('#exclude-st').onchange=renderStocks;
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active',x===b));const watch=b.dataset.page==='watch';$('#radar-page').hidden=watch;$('#watch-page').hidden=!watch;if(watch)loadWatch()});
document.querySelectorAll('.period').forEach(b=>b.onclick=async()=>{document.querySelectorAll('.period').forEach(x=>x.classList.toggle('active',x===b));await load(Number(b.dataset.period))});
document.querySelectorAll('.heat-kind').forEach(b=>b.onclick=()=>{state.heatKind=b.dataset.kind;document.querySelectorAll('.heat-kind').forEach(x=>x.classList.toggle('active',x===b));drawHeatmap()});
let searchVersion=0, searchTimer;
async function searchStocks(){
  const version=++searchVersion, q=$('#stock-search').value.trim();
  $('#stock-search-results').hidden=!q;
  $('#stock-search-rows').replaceChildren();
  if(!q)return;
  $('#stock-search-status').textContent='搜索中…';
  try{
    const data=await json(`/api/stocks/search?q=${encodeURIComponent(q)}`);
    if(version!==searchVersion)return;
    $('#stock-search-status').textContent=!data.trade_date?'暂无数据，请刷新':`${state.sources?.stocks||'未知来源'} · ${data.trade_date} · ${data.total}只${data.total>50?'（显示前50）':''}`;
    $('#stock-search-rows').innerHTML=data.items.map((x,i)=>`<tr><td>${escapeHTML(x.code)}</td><td>${escapeHTML(x.name)}</td><td>${x.close??'—'}</td><td class="${cls(x.pct_change)}">${pct(x.pct_change)}</td><td><button data-search-add="${i}">关注</button></td></tr>`).join('');
    document.querySelectorAll('[data-search-add]').forEach(b=>b.onclick=async()=>{
      const x=data.items[Number(b.dataset.searchAdd)];b.disabled=true;
      try{await addWatch('stock',x.code,x.name);b.textContent='已关注';if(!$('#watch-page').hidden)await loadWatch()}
      catch(e){toast(e.message);b.disabled=false}
    });
  }catch(e){if(version===searchVersion)$('#stock-search-status').textContent=`搜索失败：${e.message}`}
}
$('#stock-search').oninput=()=>{++searchVersion;clearTimeout(searchTimer);searchTimer=setTimeout(searchStocks,250)};
$('#stock-search-form').onsubmit=e=>{e.preventDefault();clearTimeout(searchTimer);searchStocks()};
load().catch(e=>toast(e.message));
async function loadBoardActivity(update=false){
  const button=$('#refresh-board-activity');button.disabled=true;
  if(update)$('#board-activity-status').textContent='正在联网更新，旧榜单暂时保留…';
  try{
    const [d,watch]=await Promise.all([json('/api/board-activity'+(update?'/refresh':''),update?{method:'POST'}:undefined),json('/api/watchlist')]);
    const watched=new Set(watch.items.filter(x=>watchGroup(x)==='sector').map(x=>x.item_code));
    $('#board-activity-status').textContent=d.source_time?`${d.source||'东方财富'} · ${d.source_time} · ${d.items.length}/${d.total}个板块`:'暂无缓存，请更新';
    $('#board-activity-rows').innerHTML=d.items.slice(0,30).map((x,i)=>`<tr><td><a href="https://quote.eastmoney.com/bk/90.${encodeURIComponent(x.code)}.html" target="_blank" rel="noopener noreferrer">${escapeHTML(x.name)} ↗</a></td><td class="${cls(x.pct_change)}">${pct(x.pct_change)}</td><td class="${cls(x.main_net_inflow)}">${money(x.main_net_inflow)}</td><td>${x.count}</td><td>${x.stock_code?`<button data-activity-stock="${escapeHTML(x.stock_code)}">${escapeHTML(x.stock_name)} · ${escapeHTML(x.stock_change_type||'')} ${escapeHTML(x.stock_code)}</button>`:'—'}</td><td>${(x.types||[]).slice(0,3).map(t=>`${escapeHTML(t.name)} ${t.count}次`).join('；')||'—'}</td><td><button data-activity-watch="${i}" ${watched.has(x.code)?'disabled':''}>${watched.has(x.code)?'已关注':'关注板块'}</button></td></tr>`).join('')||'<tr><td colspan="7" class="empty">尚无异动记录</td></tr>';
    document.querySelectorAll('[data-activity-watch]').forEach(b=>b.onclick=async()=>{
      const x=d.items[Number(b.dataset.activityWatch)];b.disabled=true;
      try{await addWatch('sector',x.code,x.name);b.textContent='已关注';if(!$('#watch-page').hidden)await loadWatch()}
      catch(e){b.disabled=false;toast(e.message)}
    });
    document.querySelectorAll('[data-activity-stock]').forEach(b=>b.onclick=()=>openStockDetail(b.dataset.activityStock));
  }catch(e){$('#board-activity-status').textContent=`${e.message}；当前表格若有内容为旧缓存。`}
  finally{button.disabled=false}
}
$('#refresh-board-activity').onclick=()=>loadBoardActivity(true);
loadBoardActivity();
new ResizeObserver(()=>state.chart&&state.chart.resize()).observe($('#heatmap'));
