const DashboardData = (() => {
  const known = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
  function summarize(state) {
    const posts = state.posts || [], keywords = state.keywords || [];
    const plays = posts.filter(p => known(p.plays)), likes = posts.filter(p => known(p.likes));
    const bins = [
      {name:'1亿以上',min:100000000,max:Infinity}, {name:'5000万–1亿',min:50000000,max:100000000},
      {name:'1000万–5000万',min:10000000,max:50000000}, {name:'1000万以下',min:0,max:10000000}
    ].map(bin => ({name:bin.name,count:plays.filter(p=>p.plays>=bin.min&&p.plays<bin.max).length}));
    bins.push({name:'播放量未知',count:posts.length-plays.length});
    const coverage = keywords.map(k=>({...k,count:posts.filter(p=>(p.keyword_ids||[]).includes(k.id)).length}));
    return {
      total:posts.length, playsKnown:plays.length, likesKnown:likes.length,
      playsTotal:plays.length?plays.reduce((n,p)=>n+p.plays,0):null,
      likesTotal:likes.length?likes.reduce((n,p)=>n+p.likes,0):null,
      highest:plays.length?Math.max(...plays.map(p=>p.plays)):null,
      top:[...plays].sort((a,b)=>b.plays-a.plays||a.id-b.id).slice(0,10),
      platforms:[...new Set(posts.map(p=>p.platform))].map(id=>({id,count:posts.filter(p=>p.platform===id).length})),
      keywords:coverage, keywordsCovered:coverage.filter(k=>k.count>0).length,
      bins, lastScan:state.last_scan||null, access:state.access||null,
      updatedAt:Math.max(0,...posts.map(p=>p.updated_at||0))||null
    };
  }
  function operationsSummary(data, adviceActions = []) {
    const businessDate = data.business_date;
    const timezone = /^[+-]\d{4}$/.test(data.timezone || '') ? data.timezone : '+0000';
    const minutes = (Number(timezone.slice(1,3)) * 60 + Number(timezone.slice(3))) * (timezone[0] === '-' ? -1 : 1);
    const dayAt = timestamp => {
      if (typeof timestamp !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}.*(?:Z|[+-]\d{2}:?\d{2})$/.test(timestamp)) return null;
      const epoch = Date.parse(timestamp);
      return Number.isFinite(epoch) ? new Date(epoch + minutes * 60000).toISOString().slice(0,10) : null;
    };
    const seen = new Set();
    const records = (data.published?.records || []).filter(item => {
      const key = item.platform + ':' + item.platform_post_id;
      if (item.simulated || seen.has(key)) return false;
      seen.add(key); return true;
    });
    const dated = records.map(item => ({...item, day:dayAt(item.published_at)}));
    const knownDates = dated.filter(item => item.day);
    const unknownDates = dated.length - knownDates.length;
    const base = Date.parse(businessDate + 'T12:00:00Z');
    const monday = new Date(base - ((new Date(base).getUTCDay() + 6) % 7) * 86400000).toISOString().slice(0,10);
    const week = Array.from({length:7}, (_,i) => {
      const day = new Date(base - (6 - i) * 86400000).toISOString().slice(0,10);
      return {day, count:knownDates.filter(item => item.day === day).length};
    });
    const groups = [['draft','待补资料','warn'],['pending_review','待审核','blue'],['approved_unpublished','待登记','mint']];
    const projects = groups.flatMap(([key,label,tone]) => (data.tasks?.[key] || []).map(item => ({
      ...item, label, tone,
      path:(key === 'approved_unpublished' ? '/feedback' : '/script') + '?task=' + encodeURIComponent(item.task_uid) + '&version=' + encodeURIComponent(item.version)
    })));
    const actions = data.actions || [];
    const openAdvice = adviceActions.filter(item => !['done','cancelled'].includes(item.state));
    return {
      records, week, unknownDates, projects,
      weekOutput:knownDates.length || !records.length ? knownDates.filter(item => item.day >= monday && item.day <= businessDate).length : null,
      focusCount:actions.length + openAdvice.length,
      firstAction:actions[0] || null,
      contentTypesKnown:false
    };
  }
  return {summarize, operationsSummary};
})();
if (typeof module !== 'undefined' && module.exports) module.exports = DashboardData;
