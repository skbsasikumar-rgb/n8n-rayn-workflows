function clean(value) { return String(value || '').trim(); }
function looksLikeUrl(value) {
  return /^https?:\/\//i.test(String(value || '').trim()) || /:\/\/|www\./i.test(String(value || ''));
}
function safeNodeJson(name) {
  try { return $(name).item.json || {}; }
  catch {
    try { return $(name).first().json || {}; }
    catch { return {}; }
  }
}
function cleanText(value) {
  const raw = clean(value);
  if (!raw) return '';
  if (looksLikeUrl(raw)) return '';
  const lowered = raw.toLowerCase();
  if (['undefined', 'null', 'n/a', 'na', 'none'].includes(lowered)) return '';
  return raw;
}
function escapeRegExp(value) {
  return String(value || '').replace(/[.*+?^$()|[\]\\]/g, '\\$&');
}
function cleanBusinessName(value) {
  let text = cleanText(value)
    .replace(/^\s*(?:welcome to|home of|official site of|about(?: us)?)\s+/i, '')
    .replace(/\s*[\-|–—]\s*(?:official|homepage|home|singapore|healthcare|medical group|your healthcare partner|your trusted healthcare partner).*$/i, '')
    .replace(/^[^A-Za-z0-9]+/, '')
    .replace(/\([^)]*\)/g, ' ')
    .replace(/\b(?:pte\.?\s*ltd\.?|private\s+limited|limited|ltd\.?|llp|inc\.?|corp\.?|corporation|co\.?|sdn\.?\s*bhd\.?)\b/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const locations = ['singapore','bishan','novena','orchard','tampines','toa payoh','jurong','hougang','sengkang','woodlands','yishun','punggol','serangoon','ang mo kio','bedok','clementi','queenstown','bukit batok','bukit panjang','choa chu kang','pasir ris','geylang','kallang','marine parade','redhill','sin ming','boon lay'];
  for (const location of locations) text = text.replace(new RegExp('\\b' + escapeRegExp(location) + '\\b', 'gi'), ' ');
  return text.replace(/\s+/g, ' ').replace(/[.\-–—:|@,\s]+$/, '').trim();
}
function cleanParentBusinessName(value) {
  return cleanText(value)
    .replace(/^\s*(?:welcome to|home of|official site of|about(?: us)?)\s+/i, '')
    .replace(/^[^A-Za-z0-9]+/, '')
    .replace(/\([^)]*\)/g, ' ')
    .replace(/\b(?:pte\.?\s*ltd\.?|private\s+limited|limited|ltd\.?|llp|inc\.?|corp\.?|corporation|co\.?|sdn\.?\s*bhd\.?)\b/gi, ' ')
    .replace(/\s+/g, ' ')
    .replace(/[.\-–—:|@,\s]+$/, '')
    .trim();
}
function tokenize(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9+]+/g, ' ').trim().split(/\s+/).filter(Boolean);
}
function overlapScore(left, right) {
  const a = new Set(tokenize(left));
  const b = new Set(tokenize(right));
  if (!a.size || !b.size) return 0;
  let shared = 0;
  for (const token of a) if (b.has(token)) shared += 1;
  return shared / Math.min(a.size, b.size);
}
function isLikelyPersonName(value) {
  const text = cleanText(value);
  if (!text) return false;
  if (/\b(?:clinic|medical|centre|center|hospital|group|care|mission|services|health|holdings|company|foundation|surgery|network|academy)\b/i.test(text)) return false;
  if (/^(?:dr\.?|doctor)\b/i.test(text)) return true;
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length < 2 || words.length > 4) return false;
  return words.every((word) => /^[A-Za-z][A-Za-z'.-]*$/.test(word) && /^[A-Z]/.test(word));
}
function extractNameCandidatesFromScrape(content) {
  const lines = String(content || '').split(/\n+/).map((line) => line.trim()).filter(Boolean).slice(0, 220);
  const out = [];
  for (const line of lines) {
    const normalized = line.replace(/^#+\s*/, '').trim();
    if (normalized.length < 3 || normalized.length > 100) continue;
    if (/^https?:\/\//i.test(normalized) || /:\/\/|www\./i.test(normalized)) continue;
    if (/^(?:skip to|book now|contact|opening hours|services|about us|our services|copyright|privacy policy|have questions\??)$/i.test(normalized)) continue;
    if (/\b(?:clinic|medical|centre|center|hospital|group|care|mission|foundation|services|surgery|academy)\b/i.test(normalized)) {
      out.push(normalized);
    }
  }
  return out;
}
function pickBestCompanyName(candidates, anchor) {
  const cleanedAnchor = cleanBusinessName(anchor);
  let best = '';
  let bestScore = -1;
  for (const raw of candidates) {
    const candidate = cleanBusinessName(raw);
    if (!candidate) continue;
    if (/^https?:\/\//i.test(String(raw || '')) || /:\/\/|www\./i.test(String(raw || ''))) continue;
    let score = 0;
    score += overlapScore(candidate, cleanedAnchor) * 6;
    if (/\b(?:clinic|medical|centre|center|hospital|mission|foundation|care|services|group|surgery|academy)\b/i.test(candidate)) score += 2;
    if (candidate.length >= 4 && candidate.length <= 60) score += 1;
    if (isLikelyPersonName(candidate) && !isLikelyPersonName(cleanedAnchor)) score -= 6;
    if (/\b(?:welcome|homepage|official|contact support|find a clinic|clinic locations)\b/i.test(candidate)) score -= 5;
    if (/^(?:about|contact|services|locations?)$/i.test(candidate)) score -= 6;
    if (score > bestScore) {
      bestScore = score;
      best = candidate;
    }
  }
  const chosen = best || cleanedAnchor;
  const tail = chosen.slice(cleanedAnchor.length).trim().toLowerCase();
  if (cleanedAnchor && chosen.toLowerCase().startsWith(cleanedAnchor.toLowerCase()) && tail && /^(?:centre|center|clinic|clinics|medical|group|services?)$/.test(tail)) {
    return cleanedAnchor;
  }
  return chosen || cleanedAnchor;
}
function normalizeParentName(value) {
  let text = cleanText(value);
  if (!text) return '';
  text = text.replace(/^\s*(?:its|their|our)\s+/i, '');
  const relation = text.match(/(?:operated by|managed by|service arm of|brand of|part of|member of|under|owned by|subsidiary of|incepted by|by)\s+(.+)/i);
  if (relation && relation[1]) text = relation[1];
  text = text.split(/(?:\s+(?:that|which|who|offering|providing|with|to|for|across|in|at|on)\b|[.;,\n])/i)[0] || text;
  return cleanParentBusinessName(text).replace(/^the\s+/i, '').trim();
}
function isPlausibleParentName(value) {
  const candidate = cleanParentBusinessName(value);
  if (!candidate) return false;
  if (candidate.length > 90) return false;
  if (/[.!?]/.test(candidate)) return false;
  if (/\b(?:ministry of health|healthier sg|health hub|ministry of manpower|programme|program|scheme|initiative)\b/i.test(candidate)) return false;
  if (/\b(?:welcome|book|appointment|download|click|learn|more|opening hours|questions|available|support|selecting|opened|provides?|offers?|delivers?|supports?|focused|blending|operates?|serves?|helping|making|dedicated|trusted|located|accepts)\b/i.test(candidate)) return false;
  if (/^\d+$/.test(candidate)) return false;
  if (/^[a-z\s]+$/.test(candidate)) return false;
  if (/\d{4}/.test(candidate)) return false;
  const words = candidate.split(/\s+/).filter(Boolean);
  if (words.length > 6 && !/\b(?:holdings?|group|medical|health|healthcare|clinic|care|hospital|centre|center|international|services|foundation|company)\b/i.test(candidate)) return false;
  if (/\b(?:holdings?|group|medical|health|healthcare|clinic|care|hospital|centre|center|international|services|foundation|company)\b/i.test(candidate)) return true;
  return words.length >= 2 && words.every((word) => /^[A-Z0-9][A-Za-z0-9&+.'-]*$/.test(word));
}
function extractExplicitParent(value) {
  const haystack = String(value || '');
  if (!haystack) return '';
  const patterns = [
    /\b(?:clinic\s+chain|brand|network|company|group|practice)\s+by\s+([A-Z][A-Za-z0-9&+.,'()\- ]{2,90}?)(?=(?:\s+(?:offering|providing|with|that|which|who|to|for|across|in|at|on)\b)|[.;,\n]|$)/gi,
    /\b(?:part\s+of|member\s+of|under|owned\s+by|subsidiary\s+of)\s+(?:the\s+)?([A-Z][A-Za-z0-9&+.,'()\- ]{2,90}?)(?=(?:\s+(?:offering|providing|with|that|which|who|to|for|across|in|at|on)\b)|[.;,\n]|$)/gi,
  ];
  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(haystack)) !== null) {
      if (/\b(?:its|their|our)\s+subsidiary\b/i.test(match[0])) continue;
      if (/\b(?:educational arm|consumer healthcare division|services arm)\b/i.test(match[0])) continue;
      const candidate = normalizeParentName(match[1]);
      if (!candidate) continue;
      if (/^(?:dr\+?|doctor\s*plus|clinic|medical|home|homepage|official)$/i.test(candidate)) continue;
      if (!isPlausibleParentName(candidate)) continue;
      return candidate;
    }
  }
  return '';
}
function looksLikeParent(value) {
  return isPlausibleParentName(value);
}
function extractCorporateParent(content, homepageName, anchorName) {
  const haystack = String(content || '');
  if (!haystack) return '';
  const seen = new Set();
  const matches = [];
  const patterns = [
    /\b([A-Z][A-Za-z0-9&+.'()\- ]{2,90}?\b(?:Medical Group|Group|Holdings))\b/g,
  ];
  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(haystack)) !== null) {
      const candidate = cleanParentBusinessName(match[1]);
      if (!candidate || seen.has(candidate.toLowerCase())) continue;
      seen.add(candidate.toLowerCase());
      if (/^(?:integrated healthcare group|healthcare institute|asian medical foundation)$/i.test(candidate)) continue;
      if (!isPlausibleParentName(candidate)) continue;
      const identityOverlap = Math.max(overlapScore(candidate, homepageName), overlapScore(candidate, anchorName));
      if (identityOverlap <= 0) continue;
      let score = identityOverlap * 10;
      if (/\bholdings?\b/i.test(candidate)) score += 4;
      if (/\bgroup\b/i.test(candidate)) score += 3;
      const occurrences = haystack.match(new RegExp(escapeRegExp(match[1]), 'g')) || [];
      score += Math.min(occurrences.length, 3);
      matches.push({ candidate, score });
    }
  }
  matches.sort((left, right) => right.score - left.score);
  return matches[0]?.candidate || '';
}

const input = safeNodeJson('Normalize Input');
const url = safeNodeJson('Resolve URL Status');
const contact = safeNodeJson('Select Best Contact');
const scrape = safeNodeJson('Crawl4AI - Scrape');

const anchorName = cleanBusinessName(input.company_name || '');
const cleanCompanyName = cleanBusinessName(contact.clean_company_name || url.clean_company_name || anchorName || input.company_name);
const scrapeCandidates = extractNameCandidatesFromScrape(scrape.website_content);
const companyHomepageName = pickBestCompanyName([
  contact.company_homepage_name,
  url.company_homepage_name,
  url.clean_company_name,
  ...scrapeCandidates,
  cleanCompanyName,
  anchorName,
], anchorName || cleanCompanyName || input.company_name);

const explicitParent = clean(
  input.parent_company || input.parentCompany || input.company_parent || input.group_name ||
  input.group_company || input.holding_company || input.holdings_name || input.parent_group ||
  input.ultimate_parent || input.ultimate_parent_company || input.corporate_parent ||
  input.parent_entity || input.entity_parent || input.owner_company || input.org_parent || ''
);
const contentParent = extractExplicitParent(scrape.website_content);
const corporateParent = extractCorporateParent(scrape.website_content, companyHomepageName, anchorName || cleanCompanyName);
const existingParent = clean(contact.parent_company || url.parent_company || '');
const trustedExistingParent = looksLikeParent(existingParent) && overlapScore(existingParent, companyHomepageName) < 0.85
  ? cleanParentBusinessName(existingParent)
  : '';
const parentCompany = normalizeParentName(explicitParent || contentParent || corporateParent || trustedExistingParent || companyHomepageName || cleanCompanyName);

return {
  json: {
    Id: input.Id,
    company_name: clean(input.company_name),
    clean_company_name: cleanCompanyName || anchorName,
    company_homepage_name: companyHomepageName || cleanCompanyName || anchorName,
    parent_company: parentCompany || companyHomepageName || cleanCompanyName || anchorName,
    hia_batch: clean(input.hia_batch),
    status: 'partial',
    best_url: clean(url.best_url),
    canonical_domain: clean(url.canonical_domain),
    duplicate_of_id: '',
    website_content: clean(scrape.website_content),
    full_name: clean(contact.full_name),
    first_name: clean(contact.first_name),
    role: clean(contact.role),
    email: clean(contact.email),
    linkedin_url: clean(contact.linkedin_url),
    contact_source: clean(contact.contact_source) || 'none',
    contact_confidence: clean(contact.contact_confidence) || 'LOW',
    evidence_gap: 'contact_search_complete',
    last_stage: 'contact_search',
    last_error: ''
  }
};
