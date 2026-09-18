// The weekly pull of the shortlist's new posts, run INSIDE the logged-in x.com
// tab (paste into the console, or run through the browser tool). Nothing here
// leaves the browser: it calls X's own GraphQL endpoints with the session the
// tab already has, keeps only the accounts' own posts since SINCE, and puts
// the result in window.__pull. When done, dump it for reading with
//
//   document.body.innerHTML = '<pre id="claude-dump">' + JSON.stringify(window.__pull) + '</pre>'
//
// then save the JSON as research/x/pulls/<date>.json, write the reviewed
// calls to research/x/calls/<date>.json and run research/seed-x-calls.py.
// About twenty accounts an hour before X's rate limit answers with HTTP 429;
// run the rest an hour later. Edit HANDLES and SINCE before running.
const HANDLES = ['LEADER_TRADING','Lazarus_Capital','StonkChris','cantonmeow','TheRonnieVShow','jrouldz','aleabitoreddit','__Con_','Freedom_By_40','MMatters22596','mind1nvestor','AsafNaamani','ZaStocks','HArctander','MacroCharts','RichardMoglen','GreatMattsby','Fibonacci_TA','Mr_Derivatives','GarethSoloway'];
// second batch: ['equitydd','PlayBookTrades','1ChartMaster','TomLambos','FranVezz','DeNebulord','Crypto_Moe84','benjamincowen','kevinxu','michael_rigoni','penny_ether','nanalyzetweets']
const SINCE = new Date('2026-09-04T00:00:00Z');
const MY_USER_ID = '2505699762';
const ct0 = (document.cookie.match(/ct0=([^;]+)/) || [])[1];
const BEARER = 'AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'; // X's public web-client token
const headers = {'authorization': 'Bearer ' + BEARER, 'x-csrf-token': ct0, 'x-twitter-auth-type': 'OAuth2Session', 'x-twitter-active-user': 'yes'};
// query ids change with the bundle: read them from the page's own scripts
let qFollowing = null, qTweets = null;
for (const src of [...document.scripts].map(s => s.src).filter(Boolean)) {
  try { const t = await (await fetch(src)).text();
    qFollowing = qFollowing || (t.match(/queryId:"([^"]+)",operationName:"Following"/) || [])[1];
    qTweets = qTweets || (t.match(/queryId:"([^"]+)",operationName:"UserTweets"/) || [])[1];
    if (qFollowing && qTweets) break; } catch (e) {}
}
// handles -> user ids, from the user's own following list
const ids = {}; let cursor = null;
for (let p = 0; p < 8 && Object.keys(ids).length < HANDLES.length; p++) {
  const vars = {userId: MY_USER_ID, count: 100, includePromotedContent: false}; if (cursor) vars.cursor = cursor;
  const j = await (await fetch(`https://x.com/i/api/graphql/${qFollowing}/Following?variables=${encodeURIComponent(JSON.stringify(vars))}&features=%7B%7D`, {headers, credentials: 'include'})).json();
  let entries = []; (j?.data?.user?.result?.timeline?.timeline?.instructions || []).forEach(x => { if (x.entries) entries = entries.concat(x.entries); });
  let next = null;
  for (const e of entries) { const c = e.content || {}; if (c.__typename === 'TimelineTimelineCursor' && c.cursorType === 'Bottom') next = c.value;
    const u = c.itemContent?.user_results?.result; if (u?.core && HANDLES.includes(u.core.screen_name)) ids[u.core.screen_name] = u.rest_id; }
  if (!next) break; cursor = next;
}
window.__pull = {since: SINCE.toISOString(), tweets: {}, errors: [], done: 0, total: HANDLES.length, ids};
const walk = (o, acc) => { if (!o || typeof o !== 'object') return; if (o.__typename === 'Tweet' && o.legacy && o.rest_id) acc.push(o); Object.values(o).forEach(v => walk(v, acc)); };
(async () => {
  for (const h of HANDLES) {
    const uid = ids[h]; if (!uid) { window.__pull.errors.push(h + ': no id'); window.__pull.done++; continue; }
    try {
      const vars = {userId: uid, count: 40, includePromotedContent: false, withQuickPromoteEligibilityTweetFields: false, withVoice: false, withV2Timeline: true};
      const r = await fetch(`https://x.com/i/api/graphql/${qTweets}/UserTweets?variables=${encodeURIComponent(JSON.stringify(vars))}&features=%7B%7D`, {headers, credentials: 'include'});
      const txt = await r.text(); if (!txt.startsWith('{')) throw new Error('HTTP ' + r.status + ' ' + txt.slice(0, 30));
      const j = JSON.parse(txt); const tws = []; walk(j, tws); const out = [];
      for (const t of tws) { const L = t.legacy; if (!L || String(L.user_id_str || '') !== String(uid) || L.retweeted_status_result || (L.full_text || '').startsWith('RT @')) continue;
        if (new Date(L.created_at) < SINCE) continue;   // the account's own posts since the last pull only
        const text = t.note_tweet?.note_tweet_results?.result?.text || L.full_text || '';
        if (!out.find(x => x.id === t.rest_id)) out.push({id: t.rest_id, date: L.created_at, text: text.replace(/\s+/g, ' ').slice(0, 600), reply: !!L.in_reply_to_status_id_str}); }
      window.__pull.tweets[h] = out;
    } catch (e) { window.__pull.errors.push(h + ': ' + e.message); }
    window.__pull.done++; await new Promise(r => setTimeout(r, 3500));
  }
})();
JSON.stringify({q: !!(qFollowing && qTweets), ids: Object.keys(ids).length, missing: HANDLES.filter(h => !ids[h])});
