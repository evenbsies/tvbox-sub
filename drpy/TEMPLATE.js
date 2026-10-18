// ============ drpy 自维护规则模板 ============
// 复制这份文件到 drpy/rules/ 下改名（如 mysite.js），按注释填。
// 每日任务会自动校验：node 语法、必填字段、host 可达、解析代码冒烟测试。
//
// 两种写法：
//   1) "js:" 代码块 —— 最灵活，下面模板用的就是这种。可用宿主 API：
//        request(url) / post(url,{body,headers})  发请求（返回文本）
//        setResult(d)        交结果：列表用数组，详情用 VOD 对象
//        input               当前输入（列表页URL / 详情页URL / 搜索URL / 播放标识）
//        rule                本规则对象（可取 rule.host 等）
//        MOBILE_UA / PC_UA   常用 UA 常量
//        log(x)              调试输出
//   2) "jq:"/"json:" 选择器串 —— 简单站点可用，但复杂逻辑还是用 js:。
//      例： 一级: 'jq:.list-item&&a&&href;.list-item&&img&&src;.list-item&&.title&&Text'
//      格式：'选择器&&取属性;...'，多条目用 pdfa 语义，具体看 drpy 文档。
//
// URL 占位符（引擎会自动替换）：
//   fypage     列表页码； fyfilter  筛选条件； fyid  详情 id； **  搜索关键词

var rule = {
    // ---- 站点信息（必填）----
    title: '我的站点',                    // TVBox 里显示的名字
    host: 'https://example.com',          // 站点根地址（校验器会测它通不通）

    // ---- 列表（推荐/一级）----
    homeUrl: '/api/recommend',            // 推荐页：input = host + homeUrl
    url: '/api/list?page=fypage&type=fyfilter',  // 分类列表页
    class_name: '电影&电视剧',            // 分类名，& 分隔
    class_url: 'movie&tv',                // 分类 id，& 分隔，与 class_name 一一对应
    filterable: 0,                        // 1=启用筛选（需配 filter/filter_url）

    // ---- 详情 ----
    detailUrl: '/api/detail?id=fyid',    // input = host + detailUrl（fyid 替换后）

    // ---- 搜索 ----
    searchUrl: '/api/search?wd=**',       // ** 会被替换成关键词
    searchable: 1,                        // 0=关 1=聚合搜 2=只搜本站
    quickSearch: 1,

    headers: { 'User-Agent': 'Mozilla/5.0' },
    timeout: 10000,
    limit: 6,                             // 详情页最多取的集数？（引擎相关，保持默认）
    play_parse: true,                     // 播放地址需要嗅探时为 true，直连 m3u8 可 false

    // ---- 解析代码（核心）----
    // 推荐：input 为推荐页 URL，输出 [{url,title,img,desc}]
    推荐: 'js:let d=[];let jo=JSON.parse(request(input));(jo.list||[]).forEach(it=>{d.push({url:it.id,title:it.name,img:it.pic,desc:it.note})});setResult(d);',

    // 一级：input 为分类列表 URL（含 fypage 页码），输出同上
    一级: 'js:let d=[];let jo=JSON.parse(request(input));(jo.list||[]).forEach(it=>{d.push({url:it.id,title:it.name,img:it.pic,desc:it.note})});setResult(d);',

    // 二级：input 为详情页 URL，输出 VOD 对象。
    //   vod_play_from 多线路用 $$$ 分隔；vod_play_url 内剧集用 # 分隔、"名$地址" 格式。
    二级: 'js:let jo=JSON.parse(request(input)).data||{};let eps=(jo.episodes||[]).map(e=>e.name+"$"+e.url).join("#");let vod={vod_id:jo.id,vod_name:jo.name,vod_pic:jo.pic,vod_content:jo.desc||"",vod_play_from:"线路1",vod_play_url:eps};setResult(vod);',

    // 搜索：input 为搜索 URL（关键词已替换 **），输出同列表
    搜索: 'js:let d=[];let jo=JSON.parse(request(input));(jo.list||[]).forEach(it=>{d.push({url:it.id,title:it.name,img:it.pic,desc:it.note})});setResult(d);',

    // 播放解析：input 为剧集标识（如 "第1集$http://..." 或 id），
    //   最终必须执行 input={parse:0,url:"真实播放地址"}（直连）或 {parse:1,url:...}（需嗅探）。
    lazy: 'js:let u=input;if(u.indexOf("$")>-1){u=u.split("$").pop()}input={parse:0,url:u};',
};
