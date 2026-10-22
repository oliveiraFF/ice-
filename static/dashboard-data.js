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
  return {summarize};
})();
if (typeof module !== 'undefined' && module.exports) module.exports = DashboardData;
