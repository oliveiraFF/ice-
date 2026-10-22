/* Local directory filters. Feature labels are inferred from route names, not supplied by TikHub. */
const MarketData = (() => {
  const features = ['Comment','Download','Followers','Hashtag','Interaction','Likes','Live','Music','Post','Search','Shop','Trending','User Info','User Posts','Utility','Other'];
  function featureOf(row) {
    const route = row.path.toLowerCase(), name = route.split('/').pop();
    if (/comment|reply|danmaku/.test(name)) return 'Comment';
    if (/download|play_url|play_address/.test(name)) return 'Download';
    if (/live|webcast|livestream/.test(route)) return 'Live';
    if (/followers|followings|follower_list|following_list/.test(name)) return 'Followers';
    if (/hashtag|challenge/.test(name)) return 'Hashtag';
    if (/music|song|lyric|album/.test(name)) return 'Music';
    if (/shop|goods|product|ecommerce/.test(route)) return 'Shop';
    if (/search|suggest/.test(name)) return 'Search';
    if (/billboard|trending|hot_|ranking|rank_list/.test(route)) return 'Trending';
    if (/like|digg/.test(name)) return 'Likes';
    if (/interaction|share_count|collect|favorite/.test(name)) return 'Interaction';
    if (/user_posts|user_post|post_videos|user_videos|user_video_list|user_feed/.test(name)) return 'User Posts';
    if (/user_info|user_profile|creator_info|author_info|profile_info/.test(name)) return 'User Info';
    if (/video|aweme|note|post|item_detail/.test(name)) return 'Post';
    if (/tikhub|health|captcha|ios_shortcut|hybrid/.test(route)) return 'Utility';
    return 'Other';
  }
  function matches(row, filters, managed = {}) {
    const f = filters;
    if (f.q && !`${row.title} ${row.path} ${row.platform_name} ${row.platform}`.toLowerCase().includes(f.q.toLowerCase())) return false;
    if (f.platform && row.platform !== f.platform || f.feature && featureOf(row) !== f.feature || f.type && row.category !== f.type || f.method && row.method !== f.method) return false;
    if (f.cost === 'zero' && row.price !== '0' || f.cost === 'paid' && !(Number(row.price) > 0) || f.cost === 'unknown' && row.price !== null) return false;
    if (f.credit && Boolean(row.free_credit) !== (f.credit === 'yes') || f.discount && Boolean(row.discount) !== (f.discount === 'yes')) return false;
    if (f.managed && !managed[row.id]) return false;
    return true;
  }
  return {features, featureOf, matches};
})();
if (typeof module !== 'undefined' && module.exports) module.exports = MarketData;
