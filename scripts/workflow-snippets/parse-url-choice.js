function stripFences(value){
  const fence=String.fromCharCode(96).repeat(3);
  return String(value||'').split(fence+'json').join('').split(fence).join('').trim();
}
function normalizeCandidateUrl(value){
  const raw=String(value||'').trim();
  if(!raw)return '';
  const withProtocol=/^[a-z][a-z0-9+.-]*:\/\//i.test(raw)?raw:'https://'+raw;
  const match=withProtocol.match(/^(?:https?:\/\/)?([^\/?#]+)([^?#]*)/i);
  if(!match) return '';
  const host=String(match[1]||'').toLowerCase().trim();
  if(!host||!host.includes('.')) return '';
  let pathname=String(match[2]||'/').replace(/\/+/g,'/');
  if(!pathname.startsWith('/')) pathname='/' + pathname;
  if(pathname.length>1 && pathname.endsWith('/')) pathname=pathname.slice(0,-1);
  return 'https://' + host + (pathname||'/');
}
function normalizeRoot(value){
  const normalized=normalizeCandidateUrl(value);
  if(!normalized)return '';
  const match=normalized.match(/^(?:https?:\/\/)?([^/?#]+)/i);
  const hostname=String(match?.[1]||'').toLowerCase().trim();
  return hostname ? ('https://'+hostname+'/') : '';
}
function canonicalDomain(value){
  const root=normalizeRoot(value);
  const match=root.match(/^(?:https?:\/\/)?([^/?#]+)/i);
  return String(match?.[1]||'').replace(/^www\./i,'').toLowerCase().trim();
}
function pathnameFromUrl(value){
  const normalized=normalizeCandidateUrl(value);
  let pathname='/';
  try {
    pathname = new URL(normalized || String(value || '')).pathname || '/';
  } catch {
    const raw = String(normalized || value || '');
    const match = raw.match(/^https?:\/\/[^/]+(\/[^?#]*)/i);
    pathname = String(match?.[1] || '/');
  }
  pathname=String(pathname||'/').toLowerCase().replace(/\/+/g,'/');
  if(!pathname.startsWith('/')) pathname='/' + pathname;
  if(pathname.length>1 && pathname.endsWith('/')) pathname=pathname.slice(0,-1);
  return pathname || '/';
}
const source=$('Pick First Valid Homepage').first().json || {};
const candidates=Array.isArray(source.candidates) ? source.candidates : [];
const inputItem=$input.first()?.json || {};
const content=String(inputItem.choices?.[0]?.message?.content || inputItem.body?.choices?.[0]?.message?.content || '').trim();
let parsed={};
try{ parsed=JSON.parse(stripFences(content)); }catch{}
const requestedRaw=[];
if(Object.prototype.hasOwnProperty.call(parsed,'selected')) requestedRaw.push(parsed.selected);
if(Array.isArray(parsed.alternates)) requestedRaw.push(...parsed.alternates);
const byUrl=new Map();
const byRoot=new Map();
for(const candidate of candidates){
  const normalizedUrl=normalizeCandidateUrl(candidate.url || candidate.homepage_root || '');
  const root=normalizeRoot(normalizedUrl || candidate.homepage_root || '');
  if(normalizedUrl) byUrl.set(normalizedUrl,candidate);
  if(root && !byRoot.has(root)) byRoot.set(root,candidate);
}
const ordered=[];
const seen=new Set();
for(const raw of requestedRaw){
  const normalized=normalizeCandidateUrl(raw);
  const root=normalizeRoot(raw);
  const candidate=(normalized && byUrl.get(normalized)) || (root && byRoot.get(root));
  if(candidate){
    const key=String(candidate.url || candidate.homepage_root || '');
    if(!seen.has(key)){
      ordered.push(candidate);
      seen.add(key);
    }
  }
}
for(const candidate of candidates){
  const key=String(candidate.url || candidate.homepage_root || '');
  if(!seen.has(key)){
    ordered.push(candidate);
    seen.add(key);
  }
}
if(!ordered.length){
  return [{json:{best_url:'',canonical_domain:'',candidate_rank:0,title:'',snippet:''}}];
}
return ordered.map((candidate,index)=>{
  const bestUrl=normalizeCandidateUrl(candidate.url || candidate.homepage_root || '');
  const pathname=pathnameFromUrl(bestUrl);
  const pathDepth=pathname.split('/').filter(Boolean).length;
  const utilityPathHint=Boolean(candidate.utility_path_hint) || /\/(?:author|tag|category|blog|news|article|articles|faq|faqs|guide|policy|privacy|terms|career|careers|events?|latest-events|lasting-power-of-attorney|get-document|documents?|downloads?)\b/i.test(pathname);
  return {json:{
    best_url:bestUrl,
    homepage_root:normalizeRoot(bestUrl),
    canonical_domain:String(candidate.canonical_domain||canonicalDomain(bestUrl)||''),
    title:String(candidate.title||''),
    snippet:String(candidate.snippet||''),
    candidate_rank:index+1,
    evidence_score:Number(candidate.evidence_score || 0),
    exact_name_in_title:Boolean(candidate.exact_name_in_title),
    exact_name_in_snippet:Boolean(candidate.exact_name_in_snippet),
    mention_count:Number(candidate.mention_count || 0),
    domain_token_overlap:Number(candidate.domain_token_overlap || 0),
    path_signal:Boolean(candidate.path_signal),
    path_depth:pathDepth,
    path_root:pathDepth===0,
    utility_path_hint:utilityPathHint,
    candidate_pathname:pathname,
    network_hint:Boolean(candidate.network_hint),
    listing_hint:Boolean(candidate.listing_hint),
    company_starts_with_domain:Boolean(candidate.company_starts_with_domain),
    compact_containment:Boolean(candidate.compact_containment),
  }};
});
