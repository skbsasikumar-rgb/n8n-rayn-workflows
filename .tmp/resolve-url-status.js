function escapeRegExp(value) {
  return String(value || '').replace(/[.*+?^$()|[\]\\]/g, '\\$&');
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
function normalizeRoot(value) {
  const normalized = normalizeCandidateUrl(value);
  if (!normalized) return '';
  const match = normalized.match(/^(?:https?:\/\/)?([^/?#]+)/i);
  const hostname = String(match?.[1] || '').toLowerCase().trim();
  if (!hostname) return '';
  return 'https://' + hostname + '/';
}
function canonicalDomain(value) {
  const root = normalizeRoot(value);
  const match = root.match(/^(?:https?:\/\/)?([^/?#]+)/i);
  return String(match?.[1] || '').replace(/^www\./i, '').toLowerCase().trim();
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
function isTaxonomyPath(pathname){
  return /^\/(?:author|tag|category)\b/i.test(String(pathname || '/'));
}
function isUtilityPath(pathname){
  return /\/(?:author|tag|category|about(?:-us)?|contact(?:-us)?|blog|news|article|articles|faq|faqs|guide|policy|privacy|terms|career|careers|events?|latest-events|health-screening|services?|our-services?|treatments?|lasting-power-of-attorney|get-document|documents?|downloads?)\b/i.test(String(pathname || '/'));
}
function isListingIndexPath(pathname){
  return /^\/(?:clinic|clinics|location|locations|find-a-clinic|find-us|our-clinics?|clinic-locations?)$/i.test(String(pathname || '/'));
}
function hasLocationToken(value){
  return /\b(?:singapore|bishan|bukit|merah|novena|orchard|tampines|toa payoh|jurong|hougang|sengkang|woodlands|yishun|punggol|serangoon|ang mo kio|bedok|clementi|queenstown|batok|panjang|choa chu kang|pasir ris|geylang|kallang|marine parade|redhill|sin ming|boon lay|farrer park|alexandra|upper thomson|marsiling|hougang|east coast)\b/i.test(String(value || ''));
}
function registrableLabel(hostname) {
  const labels = String(hostname || '').split('.').filter(Boolean);
  if (labels.length >= 3 && labels[labels.length - 1] === 'sg' && ['com','org','net','edu','gov'].includes(labels[labels.length - 2])) return labels[labels.length - 3] || '';
  return labels[labels.length - 2] || labels[0] || '';
}
function splitLabel(label) {
  const raw = String(label || '').toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
  if (!raw) return [];
  return raw.replace(/([0-9])([a-z])/g, '$1-$2').replace(/([a-z])([0-9])/g, '$1-$2').split('-').filter(Boolean);
}
function prettyToken(token) {
  const t = String(token || '');
  if (!t) return '';
  if (/^\d+$/.test(t)) return t;
  if (t.length <= 3 && /^[a-z]+$/i.test(t)) return t.toUpperCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
}
function cleanCompanyNameFromUrl(value) {
  const root = normalizeRoot(value);
  if (!root) return '';
  const match = root.match(/^(?:https?:\/\/)?([^/?#]+)/i);
  const hostname = String(match?.[1] || '').replace(/^www\./i, '').toLowerCase().trim();
  if (!hostname) return '';
  return splitLabel(registrableLabel(hostname)).map(prettyToken).join(' ').replace(/\s+/g, ' ').trim();
}
function cleanHomepageName(value) {
  let text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  if (/^synthetic\s+domain\s+variant$/i.test(text)) return '';
  const splitParts = text.split(/\s+[|–—-]\s+|\s+[»›]\s+|[»›]/).map((p) => p.trim()).filter(Boolean);
  if (splitParts.length > 1) {
    const marketing = /\b(?:your|trusted|partner|official|homepage|home|welcome|book|appointment|now|find us|learn more)\b/i;
    const identity = /\b(?:clinic|medical|centre|center|hospital|group|care|mission|health|surgery|services|foundation|academy)\b/i;
    const score = (part) => {
      let s = 0;
      if (identity.test(part)) s += 4;
      if (marketing.test(part)) s -= 4;
      if (part.length >= 4 && part.length <= 60) s += 1;
      return s;
    };
    splitParts.sort((a, b) => score(b) - score(a));
    text = splitParts[0] || text;
  }
  text = text
    .replace(/^\s*(?:welcome to|home of|official site of|about(?: us)?)\s+/i, '')
    .replace(/\s*[\-|–—]\s*(?:official|homepage|home|singapore|healthcare|medical group|your healthcare partner|your trusted healthcare partner).*$/i, '')
    .replace(/^[^A-Za-z0-9]+/, '')
    .replace(/\([^)]*\)/g, ' ')
    .replace(/\b(?:pte\.?\s*ltd\.?|private\s+limited|limited|ltd\.?|llp|inc\.?|corp\.?|corporation|co\.?|sdn\.?\s*bhd\.?)\b/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const tokens = ['singapore','bishan','bukit merah','bukit timah','novena','orchard','toa payoh','bedok','hougang','sengkang','woodlands','yishun','punggol','serangoon','ang mo kio','clementi','queenstown','bukit batok','bukit panjang','choa chu kang','pasir ris','geylang','kallang','marine parade','redhill','sin ming','boon lay'];
  for (const token of tokens) text = text.replace(new RegExp('\\b' + escapeRegExp(token) + '\\b', 'gi'), ' ');
  text = text.replace(/\s+/g, ' ').replace(/[.\-–—:|@,\s]+$/, '').trim();
  if (/^[A-Z0-9&+\s.'-]+$/.test(text) && /[A-Z]/.test(text)) {
    text = text.toLowerCase().replace(/\b([a-z])([a-z]*)/g, (_, a, b) => a.toUpperCase() + b);
  }
  return text;
}
function cleanInputCompanyName(value) {
  return cleanHomepageName(String(value || ''));
}
function tokenize(value){
  return String(value||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim().split(/\s+/).filter(Boolean);
}
function meaningfulIdentityTokens(value){
  return tokenize(value).filter((token)=>!['singapore','clinic','clinics','medical','medicine','family','doctor','doctors','care','health','healthcare','centre','center','group','holdings','holding','limited','ltd','pte','private','company','services','service','practice','practices','hospital','surgery'].includes(token));
}
function overlapCount(a,b){
  const left=new Set(tokenize(a));
  const right=new Set(tokenize(b));
  let count=0;
  for(const token of left){ if(right.has(token)) count += 1; }
  return count;
}
function isLikelyPersonName(value){
  const text=String(value||'').trim();
  if(!text) return false;
  if(/\b(?:clinic|medical|centre|center|hospital|group|care|mission|services|health|holdings|company|foundation|surgery|network|academy)\b/i.test(text)) return false;
  if(/^(?:dr\.?|doctor)\b/i.test(text)) return true;
  const words=text.split(/\s+/).filter(Boolean);
  if(words.length<2 || words.length>4) return false;
  if(words.every((w)=>/^[A-Za-z][A-Za-z'.-]*$/.test(w) && /^[A-Z]/.test(w))) return true;
  return false;
}
function isHtml(headers) {
  const entries = Object.entries(headers || {});
  for (const [k, v] of entries) {
    if (String(k).toLowerCase() === 'content-type' && /text\/html|application\/xhtml\+xml/i.test(String(v || ''))) return true;
  }
  return false;
}
const responses = $input.all();
const candidates = $('Parse URL Choice').all();
const normalizeInput = $('Normalize Input').first().json || {};
const cleanFromInput = cleanInputCompanyName(normalizeInput.company_name || '');
const inputHasLocation = hasLocationToken(normalizeInput.company_name || '');
const successful = [];
for (const response of responses) {
  const idx = Number(response.pairedItem?.item ?? 0);
  const candidate = candidates[idx]?.json || {};
  const url = normalizeCandidateUrl(String(candidate.best_url || '').trim());
  if (!url) continue;
  const status = Number(response.json?.statusCode || response.json?.status || 0);
  const headers = response.json?.headers || {};
  if (!(status >= 200 && status < 400)) continue;
  const pathname = pathnameFromUrl(url);
  const pathDepth = pathname.split('/').filter(Boolean).length;
  const rootOnly = pathDepth === 0;
  const taxonomyPath = isTaxonomyPath(pathname);
  const utilityPath = Boolean(candidate.utility_path_hint) || isUtilityPath(pathname);
  const listingIndexPath = isListingIndexPath(pathname);
  if (taxonomyPath) continue;
  if ((utilityPath || listingIndexPath) && !candidate.path_signal) continue;
  const title = String(candidate.title || '');
  const snippet = String(candidate.snippet || '');
  const titleSnippetText = [title, snippet].join(' ').trim();
  const identityFromText = overlapCount(titleSnippetText, cleanFromInput);
  const evidenceScore = Number(candidate.evidence_score || 0)
    + (candidate.exact_name_in_title ? 4 : 0)
    + (candidate.exact_name_in_snippet ? 3 : 0)
    + Math.min(Number(candidate.mention_count || 0), 3)
    + Math.min(Number(candidate.domain_token_overlap || 0), 2) * 2
    + (candidate.path_signal ? 2 : 0)
    + (candidate.network_hint ? 1 : 0)
    + Math.min(identityFromText, 3)
    - (candidate.listing_hint ? 3 : 0)
    - (utilityPath ? 6 : 0)
    - (listingIndexPath ? 5 : 0)
    - (!rootOnly && !candidate.path_signal ? 2 : 0);
  const insufficientIdentity = Number(candidate.evidence_score || 0) < 6
    && !candidate.exact_name_in_title
    && !candidate.exact_name_in_snippet
    && Number(candidate.domain_token_overlap || 0) < 1
    && !candidate.path_signal
    && Number(candidate.mention_count || 0) < 2
    && identityFromText < 2;
  const weakRoot = Boolean(rootOnly)
    && !candidate.path_signal
    && !candidate.exact_name_in_title
    && !candidate.exact_name_in_snippet
    && Number(candidate.mention_count || 0) < 1
    && Number(candidate.domain_token_overlap || 0) < 1
    && identityFromText < 1;
  if (insufficientIdentity) continue;
  if (weakRoot) continue;
  const sourceName = String(title || snippet || candidate.canonical_domain || url || '').trim();
  const cleanFromTitle = cleanHomepageName(sourceName);
  const cleanFromDomain = cleanCompanyNameFromUrl(url);
  let cleanName = cleanFromTitle || cleanFromInput || cleanFromDomain;
  let parentName = '';
  if (!cleanName) cleanName = cleanFromInput || cleanFromDomain;
  const cleanNameTokens = new Set(tokenize(cleanName));
  const missingInputIdentity = meaningfulIdentityTokens(cleanFromInput).filter((token) => !cleanNameTokens.has(token));
  const chosenPathCompact = url.toLowerCase().replace(/^https?:\/\//i, '').replace(/^[^/]+\//, '');
  if (candidate.path_signal && cleanFromInput && missingInputIdentity.length > 0 && missingInputIdentity.some((token) => chosenPathCompact.includes(token))) {
    cleanName = cleanFromInput;
  }
  if (candidate.path_signal && cleanFromTitle && cleanFromInput && cleanFromTitle.toLowerCase() !== cleanFromInput.toLowerCase() && overlapCount(cleanFromTitle, cleanFromInput) > 0 && !isLikelyPersonName(cleanFromTitle)) {
    parentName = cleanFromTitle;
  }
  if (isLikelyPersonName(cleanName) && cleanFromInput && !isLikelyPersonName(cleanFromInput)) {
    cleanName = cleanFromInput;
  }
  if (cleanFromInput && overlapCount(cleanName, cleanFromInput) === 0 && !isLikelyPersonName(cleanFromInput)) {
    cleanName = cleanFromInput;
  }
  successful.push({
    best_url: url,
    homepage_root: normalizeRoot(url),
    canonical_domain: String(candidate.canonical_domain || canonicalDomain(url) || ''),
    url_status_ok: true,
    url_status_code: status,
    clean_company_name: cleanName,
    company_homepage_name: cleanName,
    parent_company: parentName,
    homepage_identity_score: evidenceScore,
    path_signal: Boolean(candidate.path_signal),
    listing_index_path: Boolean(listingIndexPath),
    checkpoint_url_only: Boolean(normalizeInput.checkpoint_url_only || false),
  });
}
successful.sort((a,b)=> (b.homepage_identity_score - a.homepage_identity_score));
let chosen = successful[0] || null;
if (chosen) {
  const chosenDomain = String(chosen.canonical_domain || canonicalDomain(chosen.best_url) || '');
  const chosenPath = pathnameFromUrl(chosen.best_url);
  const sameDomainRoot = successful.find((row) => String(row.canonical_domain || '') === chosenDomain && pathnameFromUrl(row.best_url) === '/');
  if (sameDomainRoot && chosenPath !== '/' && (isUtilityPath(chosenPath) || isListingIndexPath(chosenPath) || !chosen.path_signal || sameDomainRoot.homepage_identity_score >= (chosen.homepage_identity_score - 2))) {
    chosen = sameDomainRoot;
  }
  if (chosen && chosenPath !== '/' && !inputHasLocation && /^\/(?:clinic|clinics)\b/i.test(chosenPath)) {
    chosen = {
      ...chosen,
      best_url: normalizeRoot(chosen.best_url),
      homepage_root: normalizeRoot(chosen.best_url),
    };
  }
  if (chosen && chosenPath !== '/' && (isUtilityPath(chosenPath) || isListingIndexPath(chosenPath))) {
    chosen = {
      ...chosen,
      best_url: normalizeRoot(chosen.best_url),
      homepage_root: normalizeRoot(chosen.best_url),
    };
  }
}
if (!chosen) {
  const fallbackCandidate = candidates[0]?.json || {};
  const fallbackUrl = normalizeCandidateUrl(String(fallbackCandidate.best_url || '').trim());
  const fallbackScore = Number(fallbackCandidate.evidence_score || 0);
  const fallbackDomainStrong = Number(fallbackCandidate.domain_token_overlap || 0) > 0 || Boolean(fallbackCandidate.company_starts_with_domain) || Boolean(fallbackCandidate.compact_containment);
  const fallbackPath = pathnameFromUrl(fallbackUrl);
  const fallbackIsClean = !Boolean(fallbackCandidate.listing_hint) && fallbackPath === '/' && !isUtilityPath(fallbackPath);
  if (fallbackUrl && fallbackScore >= 12 && fallbackDomainStrong && fallbackIsClean) {
    const title = String(fallbackCandidate.title || '');
    const snippet = String(fallbackCandidate.snippet || '');
    const sourceName = String(title || snippet || fallbackCandidate.canonical_domain || fallbackUrl || '').trim();
    const cleanFromTitle = cleanHomepageName(sourceName);
    const cleanFromDomain = cleanCompanyNameFromUrl(fallbackUrl);
    let cleanName = cleanFromTitle || cleanFromInput || cleanFromDomain;
    if (!cleanName) cleanName = cleanFromInput || cleanFromDomain;
    if (isLikelyPersonName(cleanName) && cleanFromInput && !isLikelyPersonName(cleanFromInput)) {
      cleanName = cleanFromInput;
    }
    chosen = {
      best_url: fallbackUrl,
      homepage_root: normalizeRoot(fallbackUrl),
      canonical_domain: String(fallbackCandidate.canonical_domain || canonicalDomain(fallbackUrl) || ''),
      url_status_ok: false,
      url_status_code: Number(responses[0]?.json?.statusCode || responses[0]?.json?.status || 0),
      clean_company_name: cleanName,
      company_homepage_name: cleanName,
      homepage_identity_score: fallbackScore,
      checkpoint_url_only: Boolean(normalizeInput.checkpoint_url_only || false),
    };
  }
}
if (!chosen) {
  chosen = { best_url: '', canonical_domain: '', url_status_ok: false, url_status_code: 0, clean_company_name: '', company_homepage_name: '', checkpoint_url_only: Boolean(normalizeInput.checkpoint_url_only || false) };
}
return { json: chosen };
