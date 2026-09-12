let detailVersion=0, detailCode=null, detailData=null, detailRange=60;
const detailCharts={};
function chart(id,option){const el=document.getElementById(id);const c=detailCharts[id]||(detailCharts[id]=echarts.init(el));c.setOption(option,true);}
const axis={axisLabel:{color:'#aabbd0'},axisLine:{lineStyle:{color:'#526078'}},splitLine:{lineStyle:{color:'#24334c'}}};
const detailMetric=(label,value,tone='')=>`<article><span>${escapeHTML(label)}</span><strong class="${tone}">${escapeHTML(value)}</strong></article>`;
function renderPriceCharts(){
  const d=detailData;if(!d)return;
  const all=d.rows||[],rows=all.slice(-detailRange),dates=rows.map(r=>r.date),closes=rows.map(r=>r.close);
  const moving=n=>rows.map((_,i)=>i<n-1?null:rows.slice(i-n+1,i+1).reduce((sum,x)=>sum+x.close,0)/n);
  const watchIndex=d.watch_date?dates.findIndex(date=>date>=d.watch_date):-1;
  const mark=watchIndex>=0?{data:[{name:'关注日期',xAxis:dates[watchIndex]}],label:{formatter:'关注'},lineStyle:{color:'#f5a623'}}:undefined;
  chart('stock-price-chart',{textStyle:{color:'#aabbd0'},tooltip:{trigger:'axis'},legend:{textStyle:{color:'#aabbd0'}},grid:{left:58,right:18,top:35,bottom:30},xAxis:{...axis,type:'category',data:dates},yAxis:{...axis,type:'value',scale:true},series:[{name:'收盘价',type:'line',showSymbol:false,data:closes,markLine:mark},{name:'MA5',type:'line',showSymbol:false,data:moving(5)},{name:'MA10',type:'line',showSymbol:false,data:moving(10)},{name:'MA20',type:'line',showSymbol:false,data:moving(20)}]});
  const avg=rows.map((r,i)=>i<19?null:rows.slice(i-19,i+1).reduce((s,x)=>s+x.volume,0)/20);
  const volumeLabel=value=>`${Number(value/10000).toLocaleString('zh-CN',{maximumFractionDigits:value>=100000?0:1})}万`;
  const volumeTip=value=>value==null||value==='-'?'—':`${Number(value).toLocaleString('zh-CN')} 手`;
  chart('stock-volume-chart',{tooltip:{trigger:'axis',confine:true},legend:{textStyle:{color:'#aabbd0'}},grid:{left:12,right:18,top:30,bottom:30,containLabel:true},xAxis:{...axis,type:'category',data:dates},yAxis:{...axis,type:'value',axisLabel:{color:'#aabbd0',formatter:volumeLabel}},series:[{name:'成交量（手）',type:'bar',tooltip:{valueFormatter:volumeTip},data:rows.map(r=>({value:r.volume,itemStyle:{color:r.close>=r.open?'#ef5350':'#26a69a'}}))},{name:'20日均量',type:'line',showSymbol:false,tooltip:{valueFormatter:volumeTip},data:avg}]});
}
function renderDetail(d){
  detailData=d;
  $('#stock-dialog-title').textContent=`${d.name} · ${d.code} · ${({main:'主板',star:'科创板',gem:'创业板',bse:'北交所'})[stockMarket(d.code)]}`;
  const rows=d.rows||[], dates=rows.map(r=>r.date), closes=rows.map(r=>r.close),snapshot=d.snapshot||{};
  $('#stock-dialog-status').textContent=`行情：${d.quote_fetched_at?'东方财富 · '+d.quote_fetched_at:'基础行情快照'}｜日线：${d.source} · ${dates.at(-1)||'暂无'}${d.warnings.length?' · '+d.warnings.join('；'):''}`;
  let peak=0,drawdown=0;
  closes.forEach(c=>{peak=Math.max(peak,c);drawdown=Math.min(drawdown,c/peak-1)});
  const retValue=n=>closes.length>n?(closes.at(-1)/closes.at(-n-1)-1)*100:null;
  const ret=n=>retValue(n)==null?'—':pct(retValue(n));
  const watchIndex=d.watch_date?dates.findIndex(date=>date>=d.watch_date):-1;
  const watchValid=watchIndex>=0&&d.watch_date>=dates[0];
  const latest=snapshot.close??closes.at(-1),today=snapshot.pct_change;
  const streak=Number(snapshot.streak||0),streakText=streak>0?`连涨${streak}日`:streak<0?`连跌${Math.abs(streak)}日`:'—';
  const high20=rows.length?Math.max(...rows.slice(-20).map(r=>r.high||r.close)):null;
  const distance20=latest&&high20?(latest/high20-1)*100:null;
  $('#stock-quick-metrics').innerHTML=[
    detailMetric('最新价',latest==null?'—':Number(latest).toFixed(2),cls(today)),detailMetric('今日',pct(today),cls(today)),
    detailMetric('3日',ret(3),cls(retValue(3))),detailMetric('5日',ret(5),cls(retValue(5))),detailMetric('20日',ret(20),cls(retValue(20))),
    detailMetric('连续表现',streakText,cls(streak)),detailMetric('换手率',pct(snapshot.turnover),''),
    detailMetric('成交额',money(snapshot.amount),''),detailMetric('距20日高点',pct(distance20),cls(distance20)),
    detailMetric('总市值',money(snapshot.market_cap),'')].join('');
  const extra=[];
  if(rows.length)extra.push(`区间回撤 ${pct(drawdown*100)}`,`距区间高点 ${pct((closes.at(-1)/peak-1)*100)}`);
  if(watchValid)extra.push(`关注以来 ${pct((closes.at(-1)/closes[watchIndex]-1)*100)}`);
  if(snapshot.pe!=null)extra.push(`市盈率（PE）${Number(snapshot.pe).toFixed(1)}`);
  if(snapshot.pb!=null)extra.push(`市净率（PB）${Number(snapshot.pb).toFixed(2)}`);
  if(snapshot.float_market_cap!=null)extra.push(`流通市值 ${money(snapshot.float_market_cap)}`);
  $('#stock-detail-metrics').textContent=extra.join('｜')||'暂无完整行情，可点击更新日线或刷新基础行情';
  const contextIndex=state.selected?state.stocks.findIndex(x=>String(x.code)===d.code):-1;
  const tags=[];
  if(contextIndex>=0)tags.push(`<b>当前：${escapeHTML(state.selected.name)} · 涨幅第${contextIndex+1}/${state.stocks.length}</b>`);
  (d.memberships||[]).slice(0,12).forEach(x=>tags.push(`<span>${escapeHTML(x.name)}</span>`));
  $('#stock-sector-tags').innerHTML=tags.length?`<small>板块归属</small>${tags.join('')}`:'<small>暂无已缓存板块归属</small>';
  renderPriceCharts();
  const select=$('#stock-comparison');select.replaceChildren();
  d.comparisons.forEach((x,i)=>{const option=document.createElement('option');option.value=i;option.textContent=x.name;select.append(option)});
  renderComparison();
  const ticker=(d.code.startsWith('6')?'SH':stockMarket(d.code)==='bse'?'BJ':'SZ')+d.code;
  const links=[['公司概况',`https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/Index?type=web&code=${ticker}`],['财务分析',`https://emweb.securities.eastmoney.com/PC_HSF10/FinanceAnalysis/Index?type=web&code=${ticker}`],['公告 / 年报',`https://data.eastmoney.com/notices/stock/${d.code}.html`]];
  $('#stock-detail-links').replaceChildren();links.forEach(([name,url])=>{const a=document.createElement('a');a.textContent=name+'（东方财富）↗';a.href=url;a.target='_blank';a.rel='noopener noreferrer';$('#stock-detail-links').append(a)});
}
function renderComparison(){
  const d=detailData,b=d?.comparisons[Number($('#stock-comparison').value)];
  const map=new Map((b?.rows||[]).map(x=>[x.date,x.close]));
  const rows=(d?.rows||[]).filter(x=>map.has(x.date)&&map.get(x.date)>0);
  const stockSource=String(d?.source||'').split(' · ')[0];
  $('#stock-comparison-note').textContent=rows.length>=2?`${stockSource} / ${b.source||b.name} · ${rows[0].date}—${rows.at(-1).date} · 本地计算`:'暂无足够数据';
  chart('stock-compare-chart',{tooltip:{trigger:'axis'},legend:{textStyle:{color:'#aabbd0'}},grid:{left:65,right:20,top:35,bottom:30},xAxis:{...axis,type:'category',data:rows.length>=2?rows.map(x=>x.date):[]},yAxis:{...axis,type:'value',axisLabel:{color:'#aabbd0',formatter:'{value}%'}},series:rows.length>=2?[{name:d.name,type:'line',showSymbol:false,data:rows.map(x=>(x.close/rows[0].close-1)*100)},{name:b.name,type:'line',showSymbol:false,data:rows.map(x=>(map.get(x.date)/map.get(rows[0].date)-1)*100)}]:[]});
}
async function openStockDetail(code,update=false){
  code=String(code).replace(/^(sh|sz|bj)/i,'');if(!/^\d{6}$/.test(code))return;
  const version=++detailVersion;detailCode=code;
  if(!$('#stock-dialog').open)$('#stock-dialog').showModal();
  $('#stock-dialog-title').textContent=code;
  $('#stock-dialog-status').textContent=update?'正在联网更新…':'正在读取本地缓存…';
  $('#stock-detail-metrics').textContent='';$('#stock-quick-metrics').replaceChildren();$('#stock-sector-tags').replaceChildren();$('#stock-detail-links').replaceChildren();
  Object.values(detailCharts).forEach(c=>c.clear());
  try{
    let data=await json(`/api/stocks/${code}/detail${update?'/refresh':''}`,update?{method:'POST'}:undefined);
    if(version!==detailVersion)return;
    if(!data.cached&&!update){$('#stock-dialog-status').textContent='首次查看，正在按需获取日线…';data=await json(`/api/stocks/${code}/detail/refresh`,{method:'POST'})}
    if(version!==detailVersion)return;
    renderDetail(data);Object.values(detailCharts).forEach(c=>c.resize());
  }catch(e){if(version===detailVersion)$('#stock-dialog-status').textContent=`读取失败：${e.message}，可稍后重试。`}
}
$('#close-stock-dialog').onclick=()=>$('#stock-dialog').close();
$('#stock-dialog').addEventListener('click',event=>{
  const dialog=$('#stock-dialog'),box=dialog.getBoundingClientRect();
  const outside=event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom;
  if(outside)dialog.close();
});
$('#stock-dialog').addEventListener('close',()=>{++detailVersion});
$('#refresh-stock-quote').onclick=async()=>{
  if(!detailCode)return;const b=$('#refresh-stock-quote');b.disabled=true;b.textContent='更新中…';
  try{const data=await json(`/api/stocks/${detailCode}/detail/quote/refresh`,{method:'POST'});renderDetail(data);toast(data.warnings.length?data.warnings.join('；'):'东方财富行情已更新')}
  catch(e){toast(e.message)}finally{b.disabled=false;b.textContent='更新行情'}
};
$('#refresh-stock-detail').onclick=()=>detailCode&&openStockDetail(detailCode,true);
$('#watch-stock-detail').onclick=async()=>{if(detailCode)try{await addWatch('stock',detailCode,detailData?.code===detailCode?detailData.name:detailCode)}catch(e){toast(e.message)}};
$('#stock-comparison').onchange=renderComparison;
document.querySelectorAll('.detail-range').forEach(b=>b.onclick=()=>{detailRange=Number(b.dataset.range);document.querySelectorAll('.detail-range').forEach(x=>x.classList.toggle('active',x===b));renderPriceCharts()});
new ResizeObserver(()=>Object.values(detailCharts).forEach(c=>c.resize())).observe($('#stock-dialog'));
// Add a detail entry without replacing watchlist's bidirectional selection action.
function decorateStocks(){
  for(const id of ['stocks','stock-search-rows'])document.querySelectorAll(`#${id} tr`).forEach(tr=>{
    const cells=tr.cells;if(cells.length<2||cells[1].querySelector('button'))return;
    const code=cells[0].textContent.trim();if(!/^\d{6}$/.test(code))return;
    const b=document.createElement('button');b.className='stock-detail-link';b.textContent=cells[1].textContent;b.onclick=()=>openStockDetail(code);cells[1].replaceChildren(b);
  });
}
for(const id of ['stocks','stock-search-rows'])new MutationObserver(decorateStocks).observe(document.getElementById(id),{childList:true});
decorateStocks();
