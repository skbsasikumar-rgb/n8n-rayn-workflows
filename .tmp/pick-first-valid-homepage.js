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
  if(!hostname)return '';
  return 'https://'+hostname+'/';
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
function registrableLabel(hostname){
  const labels=String(hostname||'').split('.').filter(Boolean);
  if(labels.length>=3&&labels[labels.length-1]==='sg'&&['com','org','net','edu','gov'].includes(labels[labels.length-2])) return labels[labels.length-3]||'';
  return labels[labels.length-2]||labels[0]||'';
}
function compact(value){ return String(value||'').toLowerCase().replace(/[^a-z0-9]+/g,''); }
function tokens(value){ return String(value||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim().split(/\s+/).filter(Boolean); }
function extractResults(payload){
  const organic = Array.isArray(payload?.organic) ? payload.organic : [];
  const results = Array.isArray(payload?.results) ? payload.results : [];
  return organic.length ? organic : results;
}
function cleanInput(value){
  return String(value||'')
    .replace(/\([^)]*\)/g,' ')
    .replace(/\b(?:pte\.?\s*ltd\.?|private\s+limited|limited|ltd\.?|llp|inc\.?|corp\.?|corporation|co\.?|sdn\.?\s*bhd\.?)\b/gi,' ')
    .replace(/\s+/g,' ')
    .trim();
}
const BLOCKED_HOSTS=['facebook.com','instagram.com','linkedin.com','x.com','twitter.com','youtube.com','yellowpages.com.sg','streetdirectory.com','findhealthclinics.com','wherecrowded.sg','recordowl.com','doctorxdentist.com','waze.com','google.com','maps.apple.com','moh.gov.sg','healthhub.sg','acra.gov.sg','gobusiness.gov.sg','sma.org.sg','ams.edu.sg','straitstimes.com','todayonline.com','channelnewsasia.com','businessinsider.com','techinasia.com','foodpanda.sg','grab.com','amazon.com','tripadvisor.com','foursquare.com','yelp.com','practo.com','threebestrated.sg','contact.page','neighbourhoodshop.sg','tracxn.com','hotfrog.sg','infobel.sg','zipleaf.com','companies.sg','sgpbusiness.com','keepital.com','sgx.com','scam.sg','zoominfo.com'];
const BLOCKED_HOST_KEYWORDS=['jobstreet','sgpgrid','crunchbase','rocketreach','apollo','signalhire','contactout','leadiq'];
const LISTING_HINT=/(?:directory|listing|reviews?|rating|opening hours|postal code|address|general practitioner|company profile|business database|profile, contacts|contact details|marketplace|delivery|reservations|book now|streetdirectory|findhealthclinics|yellow pages|local businesses|google rating|top rated|company data|shopping center|shopping centre|mall|stores?|store locator|poi|places?|corporate information|registration number|uen|share price|stock exchange|listed company|company announcement)/i;
const NETWORK_HINT=/(?:our clinics|clinic locations|clinic list|list of clinics|our branches|branches|our outlets|medical group|group practice|find a clinic|find us|our centres|our centers)/i;
const GENERIC_TOKENS=new Set(['singapore','clinic','clinics','medical','medicine','family','doctor','doctors','care','health','healthcare','centre','center','group','holdings','holding','limited','ltd','pte','private','company','services','service','practice','practices','hospital','surgery']);
const LOCATION_TOKENS=new Set(['singapore','bishan','novena','orchard','tampines','toa','payoh','jurong','hougang','sengkang','woodlands','yishun','punggol','serangoon','ang','mo','kio','bedok','clementi','queenstown','bukit','batok','choa','chu','kang','pasir','ris','geylang','kallang','marine','parade','potong','redhill','sin','ming','merah']);
const input=$('Normalize Input').first().json || {};
const companyName=String(input.company_name || '').trim();
const anchorName=cleanInput(String(input.search_loose || companyName || '').trim()) || cleanInput(companyName);
const payload=$input.all()[0]?.json || {};
const rows=extractResults(payload).slice(0,12);
const companyCompact=compact(anchorName || companyName);
const requiredAcronyms=(String(companyName).match(/\b[A-Z]{2,5}\b/g) || []).filter((token) => !['DR','GP','SG'].includes(token));
const legalEntityInput=/\b(?:holdings?|group|limited|ltd|pte|private|llp|inc|corp|corporation)\b/i.test(companyName);
const meaningfulTokensBase=tokens(anchorName || companyName).filter(t => (t.length>=3 || /^\d+$/.test(t)) && !GENERIC_TOKENS.has(t) && !LOCATION_TOKENS.has(t));
const meaningfulTokens=meaningfulTokensBase.length ? meaningfulTokensBase : (()=>{ const compactAnchor=compact(anchorName || companyName); return compactAnchor.length>=4 ? [compactAnchor] : []; })();
const candidates=[];
const seen=new Set();
for(const result of rows){
  const rawUrl=String(result?.link || result?.url || '').trim();
  const rawUrlLower=rawUrl.toLowerCase();
  const normalizedUrl=normalizeCandidateUrl(rawUrl);
  const root=normalizeRoot(normalizedUrl);
  if(!normalizedUrl||!root) continue;
  const domain=canonicalDomain(root);
  if(!domain || seen.has(normalizedUrl)) continue;
  seen.add(normalizedUrl);
  if(BLOCKED_HOSTS.some(host => domain===host || domain.endsWith('.'+host))) continue;
  if(BLOCKED_HOST_KEYWORDS.some((kw)=>domain.includes(kw))) continue;
  if(domain.endsWith('.gov.sg') || domain.endsWith('.edu.sg')) continue;
  const binaryDocHint=/\.(?:pdf|docx?|xlsx?|pptx?)(?:$|[?#])/i.test(normalizedUrl);
  if(binaryDocHint) continue;
  const title=String(result?.title||'').trim();
  const snippet=String(result?.snippet||result?.content||'').trim();
  const text=[title,snippet,rawUrl].join(' ');
  const textCompact=compact(text);
  const rootLabel=registrableLabel(domain);
  const rootCompact=compact(rootLabel);
  const titleCompact=compact(title);
  const snippetCompact=compact(snippet);
  const exactNameInTitle=Boolean(companyCompact && titleCompact.includes(companyCompact));
  const exactNameInSnippet=Boolean(companyCompact && snippetCompact.includes(companyCompact));
  const domainTokenOverlap=meaningfulTokens.filter(t => rootCompact.includes(compact(t)) || compact(t).includes(rootCompact)).length;
  const titleTokens=tokens(title);
  const snippetTokens=tokens(snippet);
  const pathCompact=compact(normalizedUrl.replace(/^https?:\/\//i,'').replace(/^[^/]+\//,''));
  const pathSignal=meaningfulTokens.some((t)=>pathCompact.includes(compact(t)));
  const pathname=pathnameFromUrl(normalizedUrl || rawUrl);
  const pathSegments=pathname.split('/').filter(Boolean);
  const pathDepth=pathSegments.length;
  const pathRoot=pathDepth===0;
  const authorTaxonomyPath=/^\/(?:author|tag|category)\b/i.test(pathname);
  const contentUtilityPath=/\/(?:blog|news|article|articles|faq|faqs|guide|policy|privacy|terms|careers?|events?|latest-events|lasting-power-of-attorney|get-document|documents?|downloads?)\b/i.test(pathname);
  const utilityPathHint=authorTaxonomyPath || /\/(?:faq|faqs|about(?:-us)?|contact(?:-us)?|news|blog|article|articles|events?|latest-events|career|careers|policy|privacy|terms|guide|lasting-power-of-attorney|get-document|documents?|downloads?|investor-relations?|author|tag|category)\b/i.test(pathname);
  function tokenMentioned(token){
    const normalized=compact(token);
    if(!normalized) return false;
    if(/^\d+$/.test(token)) return titleCompact.includes(normalized) || snippetCompact.includes(normalized);
    if(normalized.length<=3) return titleTokens.includes(token) || snippetTokens.includes(token);
    return titleTokens.includes(token) || snippetTokens.includes(token) || titleCompact.includes(normalized) || snippetCompact.includes(normalized);
  }
  const mentionCount=meaningfulTokens.filter((t) => tokenMentioned(t)).length;
  const networkHint=NETWORK_HINT.test(text);
  const listingPathHint=/\/(?:items?|companies?|company-details?|pois?|directory|listing|stores?|store-locator|place|locations?|profile|corporate-information|healthcare-providers?|providers?|doctor-finder|clinic-finder|gp-finder|search-results?|facilit(?:y|ies)|author|tag|category|jobs?|careers?)\b/i.test(rawUrlLower);
  const listingHint=LISTING_HINT.test(text) || listingPathHint;
  const jobsHint=/\b(?:jobs?|career|hiring|vacancies?)\b/i.test([title,snippet,pathname].join(' '));
  const acronymMatched = requiredAcronyms.length === 0 || requiredAcronyms.some((token) => textCompact.includes(compact(token)));
  const companyStartsWithDomain = Boolean(companyCompact && (companyCompact.startsWith(rootCompact) || rootCompact.startsWith(companyCompact)));
  const compactContainment = Boolean(companyCompact && rootCompact && (companyCompact.includes(rootCompact) || rootCompact.includes(companyCompact)));
  const domainStrong = domainTokenOverlap > 0 || companyStartsWithDomain || compactContainment;
  const hasIdentitySignal = exactNameInTitle || exactNameInSnippet || mentionCount > 0 || domainStrong || pathSignal;
  const profileSlugHint = !domainStrong && pathDepth >= 2 && (/^[a-z]{1,2}$/.test(pathSegments[0] || '') || /\d{5,}/.test(pathSegments[pathSegments.length - 1] || ''));
  if(profileSlugHint) continue;
  if(authorTaxonomyPath) continue;
  if(contentUtilityPath && !pathSignal) continue;
  if(listingHint && !domainStrong) continue;
  if(listingHint && !hasIdentitySignal && !networkHint) continue;
  if(utilityPathHint && !domainStrong && !pathSignal) continue;
  if(jobsHint && !domainStrong) continue;
  if(!acronymMatched) continue;
if(!legalEntityInput && !domainStrong && !pathSignal && !networkHint && !exactNameInTitle && !exactNameInSnippet && mentionCount===0) continue;
  if(!hasIdentitySignal) continue;
  let evidenceScore=0;
  if(exactNameInTitle) evidenceScore += 5;
  if(exactNameInSnippet) evidenceScore += 4;
  evidenceScore += Math.min(mentionCount,3);
  evidenceScore += Math.min(domainTokenOverlap,2) * 2;
  if(pathSignal) evidenceScore += 2;
  if(networkHint) evidenceScore += 1;
  if(pathRoot) evidenceScore += 2;
  if(pathDepth >= 2 && !pathSignal) evidenceScore -= 2;
  if(pathDepth >= 3 && !pathSignal) evidenceScore -= 2;
  if(utilityPathHint) evidenceScore -= 7;
  if(legalEntityInput && pathRoot) evidenceScore += 2;
  if(legalEntityInput && !pathRoot) evidenceScore -= 2;
  if(listingHint && !networkHint && !domainStrong) evidenceScore -= 7;
  else if(listingHint && !networkHint) evidenceScore -= 3;
  candidates.push({
    rank: candidates.length + 1,
    source_rank: Number(result?.position || result?.rank || candidates.length + 1),
    url: normalizedUrl,
    homepage_root: root,
    canonical_domain: domain,
    candidate_pathname: pathname,
    domain_label: rootLabel,
    title,
    snippet,
    exact_name_in_title: exactNameInTitle,
    exact_name_in_snippet: exactNameInSnippet,
    domain_token_overlap: domainTokenOverlap,
    mention_count: mentionCount,
    path_signal: Boolean(pathSignal),
    path_depth: pathDepth,
    path_root: Boolean(pathRoot),
    utility_path_hint: Boolean(utilityPathHint),
    network_hint: Boolean(networkHint),
    listing_hint: Boolean(listingHint),
    legal_entity_input: legalEntityInput,
    company_starts_with_domain: companyStartsWithDomain,
    compact_containment: compactContainment,
    evidence_score: evidenceScore,
  });
}

candidates.sort((a,b)=> (b.evidence_score - a.evidence_score) || (a.source_rank - b.source_rank));
const prompt = [
  'Pick the best official homepage URL for this company from the candidate list.',
  'Company: ' + companyName,
  '',
  'Rules:',
  '- Use evidence_score, title, snippet, and identity signals; select the strongest official match.',
  '- Shared/group domains are allowed only when the clinic/company identity is explicitly evidenced.',
  '- If candidate URL path is clinic-specific, keep that full URL instead of collapsing to root.',
  '- Do not pick social, directories, aggregators, map pages, news, or government pages.',
  '- If none is official, return blank.',
  '- Return valid JSON only with two keys: selected and alternates.',
  '',
  'Candidates:',
  JSON.stringify(candidates, null, 2),
].join('\n');
return {json:{company_name:companyName,candidates,prompt,checkpoint_url_only:Boolean(input.checkpoint_url_only||false)}};
