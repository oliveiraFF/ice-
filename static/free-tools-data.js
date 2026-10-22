const FreeToolsData = (() => {
  const stop = new Set('的 了 是 我 你 他 她 它 这 那 这个 那个 一个 什么 怎么 吗 呢 啊 呀 吧 都 也 就 很 真 有 没 在 和 与 或 的话 真的 感觉'.split(' '));
  function parseComments(input){
    const text=input.trim();if(text.length>1000000)throw new Error('评论文本最多100万字符');if(!text)return [];
    let rows;
    if(text.startsWith('[')||text.startsWith('{')){let payload;try{payload=JSON.parse(text);}catch{throw new Error('JSON格式不正确，请检查后重试');}rows=Array.isArray(payload)?payload:payload.comments;if(!Array.isArray(rows))throw new Error('JSON需为评论数组，或包含comments数组');}
    else rows=text.split(/\r?\n/);
    if(rows.length>5000)throw new Error('一次最多分析5000条评论');
    return rows.map((row,i)=>{const value=typeof row==='string'?row:row?.text??row?.content;if(typeof value!=='string')throw new Error(`第${i+1}条需要text或content文本`);if(value.length>10000)throw new Error(`第${i+1}条超过1万字符`);return value.trim();}).filter(Boolean);
  }
  function analyzeComments(comments){
    const frequency=new Map(),duplicates=new Map();
    const segmenter=typeof Intl.Segmenter==='function'?new Intl.Segmenter('zh',{granularity:'word'}):null;
    for(const comment of comments){
      const normalized=comment.normalize('NFKC').toLowerCase().replace(/\s+/g,' ').trim();
      if(!duplicates.has(normalized))duplicates.set(normalized,{text:comment,count:0});duplicates.get(normalized).count++;
      const tokens=segmenter?[...segmenter.segment(normalized)].filter(s=>s.isWordLike).map(s=>s.segment):(normalized.match(/[\p{L}\p{N}]+/gu)||[]);
      for(const word of new Set(tokens.filter(w=>w.length>=2&&!stop.has(w)&&!/^\d+$/.test(w))))frequency.set(word,(frequency.get(word)||0)+1);
    }
    return {total:comments.length,unique:duplicates.size,repeated:comments.length-duplicates.size,
      words:[...frequency].map(([word,count])=>({word,count})).sort((a,b)=>b.count-a.count||a.word.localeCompare(b.word,'zh-CN')).slice(0,30),
      duplicates:[...duplicates.values()].filter(r=>r.count>1).sort((a,b)=>b.count-a.count).slice(0,30)};
  }
  function dedupComments(comments){
    const counts=new Map();
    for(const comment of comments||[]){
      const text=String(comment||'').trim();
      if(!text)continue;
      counts.set(text,(counts.get(text)||0)+1);
    }
    return [...counts.entries()].map(([text,count])=>({text,count}));
  }
  function csv(rows){return '\ufeff'+rows.map(row=>row.map(value=>{let text=value===null||value===undefined?'':String(value);if(typeof value==='string'&&/^[\s]*[=+@-]/.test(text))text="'"+text;return /[",\r\n]/.test(text)?'"'+text.replace(/"/g,'""')+'"':text;}).join(',')).join('\r\n');}
  function creators(posts){
    const groups=new Map();for(const post of posts){const key=post.platform+'|'+(post.author||'未知作者');if(!groups.has(key))groups.set(key,{platform:post.platform,name:post.author||'未知作者',posts:[]});groups.get(key).posts.push(post);}
    const sum=(rows,key)=>{const known=rows.filter(p=>p[key]!==null&&p[key]!==undefined);return known.length?known.reduce((n,p)=>n+p[key],0):null;};
    return [...groups.values()].map(g=>({platform:g.platform,name:g.name,count:g.posts.length,plays:sum(g.posts,'plays'),likes:sum(g.posts,'likes')})).sort((a,b)=>(b.plays??-1)-(a.plays??-1));
  }
  return {parseComments,analyzeComments,dedupComments,csv,creators};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=FreeToolsData;
