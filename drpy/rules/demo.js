// 自维护 drpy 规则示例
// 数据源: 本仓库自托管 JSON (drpy/rules/demo_data.json)，每日校验器会真实请求并执行下面的解析代码。
// 照着这个结构，把 host/url/解析代码换成目标站点的即可。新规则放到 drpy/rules/ 下，文件名即 key。
var rule = {
    title: '自维护示例',
    host: 'https://cdn.jsdelivr.net',
    homeUrl: '/gh/evenbsies/tvbox-sub@main/drpy/rules/demo_data.json',
    url: '/gh/evenbsies/tvbox-sub@main/drpy/rules/demo_data.json?page=fypage',
    class_name: '全部',
    class_url: 'all',
    detailUrl: '/gh/evenbsies/tvbox-sub@main/drpy/rules/demo_data.json?id=fyid',
    searchUrl: '/gh/evenbsies/tvbox-sub@main/drpy/rules/demo_data.json?keyword=**',
    searchable: 1,
    quickSearch: 1,
    headers: {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36'
    },
    timeout: 10000,
    // 首页推荐: 解析 JSON list -> {url,title,img,desc}
    推荐: 'js:let d=[];let jo=JSON.parse(request(input)).list||[];jo.forEach(it=>{d.push({url:it.vod_id,title:it.vod_name,img:it.vod_pic,desc:it.vod_remarks})});setResult(d);',
    // 分类列表: 同推荐
    一级: 'js:let d=[];let jo=JSON.parse(request(input)).list||[];jo.forEach(it=>{d.push({url:it.vod_id,title:it.vod_name,img:it.vod_pic,desc:it.vod_remarks})});setResult(d);',
    // 详情: 按 id 找到条目，返回 VOD 对象（含剧集播放地址）
    二级: 'js:let id=(input.match(/id=([^&]+)/)||[])[1]||"";let jo=JSON.parse(request(rule.host+rule.homeUrl)).list||[];let it=jo.find(x=>String(x.vod_id)===id)||jo[0]||{};let vod={vod_id:it.vod_id||id,vod_name:it.vod_name||"",vod_pic:it.vod_pic||"",vod_remarks:it.vod_remarks||"",vod_content:it.vod_content||"",vod_play_from:"示例线路",vod_play_url:it.vod_play_url||""};setResult(vod);',
    // 搜索: input 里 ** 会被替换成关键词，这里按关键词过滤
    搜索: 'js:let kw=(input.match(/keyword=([^&]*)/)||[])[1]||"";kw=decodeURIComponent(kw);let jo=JSON.parse(request(rule.host+rule.homeUrl)).list||[];let d=[];jo.forEach(it=>{if(!kw||String(it.vod_name).indexOf(kw)>-1){d.push({url:it.vod_id,title:it.vod_name,img:it.vod_pic,desc:it.vod_remarks})}});setResult(d);',
    // 播放: input 是 "第01集$<url>" 或直接 url，取出真实地址直连播放
    lazy: 'js:let u=input;if(u.indexOf("$")>-1){u=u.split("$")[1]}input={parse:0,url:u};',
};
