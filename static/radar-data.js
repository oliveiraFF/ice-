const RadarData=(()=>{
  const known=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0;
  function tags(post){return [...new Set([...(post.tags||[]),...[...(post.title||'').matchAll(/#([^#\s@，。！？!?]+)/g)].map(m=>m[1])])];}
  function ageHours(post,now=Date.now()/1000){return known(post.published_at)&&post.published_at>0&&post.published_at<=now?(now-post.published_at)/3600:null;}
  function small(post){return known(post.followers)&&post.followers<10000;}
  function selectOnly(kind,value){return {preset:kind==='common'?value:'all',tag:kind==='tag'?value:'',direction:kind==='direction'?value:''};}
  function sharedTags(posts){const counts=new Map();for(const p of posts)for(const name of tags(p))counts.set(name,(counts.get(name)||0)+1);return [...counts].filter(([,n])=>n>=2).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]));}
  function point(post,maximum,now=Date.now()/1000){
    const hours=ageHours(post,now),unknown=hours===null||!known(post.plays);
    const distance=hours===null?131:hours<=24?20+hours/24*22:hours<=168?42+(hours-24)/144*40:82+Math.min(1,(hours-168)/552)*43;
    let hash=0;for(const c of String(post.external_id||post.id))hash=(hash*31+c.charCodeAt(0))>>>0;
    const angle=(post.platform==='xhs'?-Math.PI/2:Math.PI/2)+.16+(hash%1000)/1000*(Math.PI-.32);
    return {x:160+Math.cos(angle)*distance,y:160+Math.sin(angle)*distance,r:6+(known(post.plays)&&maximum>0?Math.sqrt(post.plays/maximum)*7:0),unknown};
  }
  function filter(posts,f={},now=Date.now()/1000){
    const selected=posts.filter(p=>{const age=ageHours(p,now);return (!f.platform||f.platform==='all'||p.platform===f.platform)&&(!f.minPlays||known(p.plays)&&p.plays>=f.minPlays)&&(!f.days||age!==null&&age<=f.days*24)&&(!f.preset||f.preset==='all'||f.preset==='small'&&small(p)||f.preset==='recent'&&age!==null&&age<=24)&&(!f.tag||tags(p).includes(f.tag))&&(!f.postIds||f.postIds.includes(p.id))&&(!f.query||`${p.title} ${p.author}`.toLowerCase().includes(f.query.toLowerCase()));});
    const score=p=>f.sort==='newest'?p.published_at??-1:f.sort==='velocity'?(ageHours(p,now)!==null&&known(p.likes)?Math.round(p.likes/Math.max(ageHours(p,now),1)):-1):p[f.sort||'plays']??-1;
    return selected.sort((a,b)=>score(b)-score(a)||a.id-b.id);
  }
  function overview(posts){
    const plays=posts.filter(p=>known(p.plays)),eligible=posts.filter(p=>known(p.followers));
    return {total:posts.length,playsKnown:plays.length,plays:plays.length?plays.reduce((sum,p)=>sum+p.plays,0):null,
      highest:Math.max(0,...plays.map(p=>p.plays)),eligible:eligible.length,small:eligible.filter(small).length};
  }
  return {tags,ageHours,small,selectOnly,sharedTags,point,filter,overview};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=RadarData;
