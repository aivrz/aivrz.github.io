/*!
 * embed-generator.js  （vcode 工具 · 重构版）
 * ========================================================================
 * 接收一条视频链接，自动识别其所属平台，并返回对应的标准 iframe 嵌入
 * 播放器代码，用于在第三方网站中播放。
 *
 * 重构要点（相对旧版）：
 *   1. 声明式平台表（PLATFORMS）：把原先 10+ 个 if/else 分支收敛为
 *      “正则/判定 + 构建函数”的数据驱动结构，新增平台只改表、不动主流程。
 *   2. 抽取公共播放参数拼接（playQs / joinQs），消除各平台重复的
 *      autoplay/muted/loop 拼串代码。
 *   3. UMD 包装：浏览器挂到 window.VideoEmbedGen，Node 走 module.exports，
 *      与 index.html 共用同一份实现，消除“内联脚本又抄一遍”的重复。
 *   4. 腾讯 / Facebook 的易错点（封面页、非视频页）保留为具名守卫函数。
 *
 * 用法（浏览器）：<script src="embed-generator.js"></script>
 *                VideoEmbedGen.generateEmbedCode(url, opts)
 * 用法（Node）：  const { generateEmbedCode } = require('./embed-generator.js');
 *
 * 返回值：{ platform, platform_cn, supported, auto_generate,
 *          embed_url, iframe, restrictions, note }
 * 调研日期：2026-09-12
 * ========================================================================
 */

(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) module.exports = factory();
  else root.VideoEmbedGen = factory();
})(typeof self !== 'undefined' ? self : this, function () {

  /* ---------- 基础工具 ---------- */
  function buildIframe(embedUrl, width, height, extraAttrs) {
    extraAttrs = extraAttrs || '';
    return '<iframe src="' + embedUrl + '" width="' + width + '" height="' + height +
      '" frameborder="0" allowfullscreen ' +
      'allow="accelerometer; autoplay; clipboard-write; encrypted-media; ' +
      'gyroscope; picture-in-picture; web-share" ' + extraAttrs + '></iframe>';
  }

  function makeResult(platform, cn, supported, autoGen, embedUrl, width, height,
                      restrictions, note, extraAttrs) {
    return {
      platform: platform, platform_cn: cn, supported: supported, auto_generate: autoGen,
      embed_url: embedUrl,
      iframe: embedUrl ? buildIframe(embedUrl, width, height, extraAttrs) : null,
      restrictions: restrictions, note: note
    };
  }

  // 公共播放参数拼接：自动播放 / 静音 / 循环
  function playQs(o) {
    var q = [];
    if (o.autoplay) q.push('autoplay=1');
    if (o.muted) q.push('mute=1');
    if (o.loop) q.push('loop=1');
    return q;
  }
  function joinQs(q) { return q.length ? '?' + q.join('&') : ''; }

  /* ---------- 易错点守卫（具名函数，便于测试与复用） ---------- */

  // 腾讯视频：区分 /x/page/<vid> 与 /x/cover/<cid>/<vid>，拦截封面/合集页
  function tencentVid(url) {
    try {
      var u = new URL(url);
      var q = u.searchParams.get('vid');
      if (q) return { vid: q, warn: null };
      var parts = u.pathname.replace(/\/+$/, '').split('/').filter(Boolean);
      if (parts.length >= 2 && parts[0] === 'x' && parts[1] === 'cover') {
        if (parts.length < 4) return { vid: null, warn: '该链接是腾讯视频的封面/合集页（非单个视频），无法嵌入。请打开具体某一集/视频，复制其播放页地址（形如 v.qq.com/x/cover/<cid>/<vid>.html）后再生成。' };
        var seg = parts[3].split('.')[0];
      } else if (parts.length >= 2 && parts[0] === 'x' && parts[1] === 'page') {
        var seg = parts[parts.length - 1].split('.')[0];
      } else {
        return { vid: null, warn: null };
      }
      if (/^[a-zA-Z0-9]+$/.test(seg)) return { vid: seg, warn: null };
      return { vid: null, warn: '从链接中提取到的视频 ID 格式不正确。' };
    } catch (e) {
      return { vid: null, warn: null };
    }
  }

  // Facebook：仅视频页（/videos/、/watch、/reel、fb.watch）才生成
  function isFacebookVideo(url) {
    if (url.indexOf('fb.watch') !== -1) return true;
    return /facebook\.com\/(?:[^\/]+\/)?(?:videos|reel|watch)(?:[\/?]|$)/.test(url);
  }

  function notVideoFacebook() {
    return {
      platform: 'Facebook', platform_cn: 'Facebook', supported: true, auto_generate: false,
      embed_url: null, iframe: null,
      restrictions: 'Facebook 支持视频嵌入，但当前链接不是可嵌入的视频地址（可能是照片、主页、个人或公开帖子，而非 /videos/、/watch、/reel 视频页）。',
      note: '请使用 Facebook 视频页链接，形如 facebook.com/<用户名>/videos/<id>/ 、facebook.com/watch/?v=<id> 或 facebook.com/reel/<id>/（fb.watch 短链亦可），并确保该视频为“公开”。'
    };
  }

  /* ---------- 平台声明表（数据驱动，新增平台只改这里） ---------- */
  var PLATFORMS = [
    {
      key: 'YouTube', cn: 'YouTube',
      re: /(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/|live\/|v\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/,
      build: function (m, o) {
        var host = o.privacy_enhanced ? 'www.youtube-nocookie.com' : 'www.youtube.com';
        var q = playQs(o); if (o.start) q.push('start=' + o.start);
        return makeResult('YouTube', 'YouTube', true, true,
          'https://' + host + '/embed/' + m[1] + joinQs(q), o.width, o.height,
          '上传者可在 YouTube Studio 关闭“允许嵌入”；年龄限制视频在外站会被重定向回 YouTube；面向儿童的内容需自我申报；自动播放必须静音；使用 IFrame Player API 时需正确设置 HTTP Referer，否则报错 153。',
          '官方分享→“嵌入”可直接复制，也支持 oEmbed。本工具可从 watch / youtu.be / shorts 链接自动生成。');
      }
    },
    {
      key: 'Vimeo', cn: 'Vimeo',
      re: /vimeo\.com\/(?:video\/)?(\d+)/,
      build: function (m, o) {
        var q = playQs(o); if (o.start) q.push('#t=' + o.start + 's');
        return makeResult('Vimeo', 'Vimeo', true, true,
          'https://player.vimeo.com/video/' + m[1] + joinQs(q), o.width, o.height,
          '上传者可在隐私设置中限制嵌入范围（Anywhere / Nowhere / 指定域名，最多 50 个）；“自定义 URL”视频不可嵌入；隐藏控件、播放器配色等高级参数需 Plus 及以上付费套餐。',
          '官方分享→Embed 可复制，支持 oEmbed。本工具从 vimeo.com/<id> 自动生成。');
      }
    },
    {
      key: 'Bilibili', cn: '哔哩哔哩',
      re: /bilibili\.com\/video\/(BV[0-9A-Za-z]+)/,
      build: function (m, o) {
        var params = ['bvid=' + m[1], 'page=' + o.page, 'high_quality=1', 'danmaku=0'];
        if (o.autoplay) params.push('autoplay=1');
        if (o.muted) params.push('mute=1');
        if (o.start) params.push('t=' + o.start);
        return makeResult('Bilibili', '哔哩哔哩', true, true,
          'https://player.bilibili.com/player.html?' + params.join('&'), o.width, o.height,
          '视频需开启“允许嵌入”；部分视频需携带正确 Referer；high_quality 仅在视频本身支持时生效；弹幕默认开启（danmaku=0 关闭）；移动端需自行做响应式适配。B 站嵌入无广告。',
          '官方分享→“嵌入代码”可复制。本工具可从 BV 号链接自动生成。');
      }
    },
    {
      key: 'Tencent', cn: '腾讯视频',
      test: function (url) { return url.indexOf('v.qq.com') !== -1; },
      build: function (m, o, url) {
        var tv = tencentVid(url);
        if (tv.vid) {
          return makeResult('Tencent', '腾讯视频', true, true,
            'https://v.qq.com/txp/iframe/player.html?vid=' + tv.vid, o.width, o.height,
            '视频须在后台开启“允许外链播放”；vid 区分大小写；部分老视频已下线或设为仅 App 内播放，会返回 404/空白；广告无法由嵌入方控制（旧 iframe 路径可去广告，但可能失效）。',
            '官方分享→“嵌入代码/通用代码”可复制，其中 src 里的 vid 即视频 ID。本工具从 v.qq.com 链接提取 vid 自动生成；若仍提示 vid 非法，多半是复制到了封面/合集页，请改用具体视频地址，或直接使用官方分享代码。');
        }
        return { platform: 'Tencent', platform_cn: '腾讯视频', supported: true, auto_generate: false,
          embed_url: null, iframe: null,
          restrictions: tv.warn || '未能从链接中识别腾讯视频 ID。',
          note: '请复制具体视频播放页地址（v.qq.com/x/page/<vid>.html 或 v.qq.com/x/cover/<cid>/<vid>.html），或使用官方分享→嵌入代码里的 vid。' };
      }
    },
    {
      key: 'Youku', cn: '优酷',
      re: /v\.youku\.com\/v_show\/id_([\w=]+)\.html/,
      build: function (m, o) {
        return makeResult('Youku', '优酷', true, true,
          'https://player.youku.com/embed/' + m[1], o.width, o.height,
          '优酷已停止公开 HTML5 嵌入，仅提供受限的 iframe 分享代码；视频须开启“允许第三方网站嵌入”；不支持自动播放（移动端无效）；旧版 Flash 播放器已停用；未开启权限则返回空白。',
          '官方分享→“通用代码”可复制（仅限开启嵌入权限的视频）。本工具从 v_show/id_ 链接提取 ID 自动生成。');
      }
    },
    {
      key: 'iQiyi', cn: '爱奇艺',
      re: /iqiyi\.com\/(?:v_|w_|a_|l_)?([\w]+)\.html/,
      build: function (m, o) {
        return makeResult('iQiyi', '爱奇艺', true, false,
          'https://www.iqiyi.com/player.html?vid=' + m[1], o.width, o.height,
          '爱奇艺嵌入限制最多：自动从 URL 拼装播放器地址不可靠，强烈建议使用官方分享→“通用代码/嵌入代码”复制的 iframe；部分视频仅支持电脑端、移动端无法播放；很多版权/付费内容禁止外链。',
          '官方分享面板提供“通用代码”。注意：从 URL 自动生成的 player.html 地址不一定可用，请以官方分享代码为准。');
      }
    },
    {
      key: 'Douyin', cn: '抖音',
      re: /douyin\.com\/(?:video\/)?(\d{10,})/,
      build: function (m, o) {
        return makeResult('Douyin', '抖音', true, false,
          'https://open.douyin.com/player/video?vid=' + m[1] + '&autoplay=' + (o.autoplay ? 1 : 0),
          o.width, o.height,
          '视频必须为“公开”状态（非公开返回 28003004 错误）；iframe 未做自适应，需自行设置宽高与样式；父级容器宽度 < 730px 时会被强制按竖版渲染；需设置 referrerpolicy="unsafe-url"。',
          '抖音开放平台提供“通过 VideoID 获取 IFrame 代码”接口；本工具从 douyin.com/video/<id> 生成（短链 v.douyin.com 需先在浏览器打开取得视频 ID）。',
          'referrerpolicy="unsafe-url"');
      }
    },
    {
      key: 'TikTok', cn: 'TikTok',
      re: /tiktok\.com\/@[\w.-]+\/video\/(\d+)/,
      build: function (m, o) {
        return makeResult('TikTok', 'TikTok', true, true,
          'https://www.tiktok.com/embed/v2/' + m[1] + '?lang=en-US', o.width, o.height,
          '仅公开视频可被嵌入；视频被删除后嵌入自动失效；自动播放受浏览器策略限制（需静音）；官方嵌入为 blockquote + script，本工具提供等效 iframe；每嵌入一个视频都会加载约 120KB 的 TikTok SDK，过多会拖慢页面。',
          '官方分享→Embed 可复制，WordPress/Webflow/Squarespace/Ghost 等支持 oEmbed（直接粘贴 URL 自动转换）。本工具从 /video/<id> 链接生成等效 iframe。');
      }
    },
    {
      key: 'Facebook', cn: 'Facebook',
      test: function (url) { return url.indexOf('facebook.com') !== -1 || url.indexOf('fb.watch') !== -1; },
      build: function (m, o, url) {
        if (!isFacebookVideo(url)) return notVideoFacebook();
        var href = encodeURIComponent(url);
        return makeResult('Facebook', 'Facebook', true, true,
          'https://www.facebook.com/plugins/video.php?href=' + href + '&show_text=0&width=' + o.width,
          o.width, o.height,
          '被嵌入的帖子/视频必须是“公开”的；隐私、好友分组、年龄限制、地区限制或已删除的内容不会渲染；需通过 Facebook 官方插件端点（plugins/video.php），原始 URL 作为 href 参数；加载会引入 Facebook 追踪 Cookie。',
          '官方 ⋯→“嵌入”可复制标准 iframe；多数 CMS 直接粘贴 URL 也能自动转换。本工具仅对 Facebook 视频页（/videos/、/watch、/reel、fb.watch）生成官方插件 iframe，非视频链接会提示改用视频地址。');
      }
    },
    {
      key: 'Dailymotion', cn: 'Dailymotion',
      re: /dailymotion\.com\/(?:video\/|embed\/|#\/video\/)([a-zA-Z0-9]+)|dai\.ly\/([a-zA-Z0-9]+)/,
      build: function (m, o) {
        var id = m[1] || m[2];
        return makeResult('Dailymotion', 'Dailymotion', true, true,
          'https://www.dailymotion.com/embed/video/' + id + joinQs(playQs(o)), o.width, o.height,
          '上传者可在隐私设置中限制可嵌入的域名；部分内容受地区版权限制；免费账户嵌入可能带平台水印/广告。',
          '官方分享→“嵌入”可复制，支持 oEmbed。本工具从 dailymotion.com/video/<id> 或 dai.ly/<id> 短链自动生成。');
      }
    },
    {
      key: 'WeChatChannels', cn: '微信视频号',
      test: function (url) { return url.indexOf('channels.weixin.qq.com') !== -1 || url.indexOf('weixin.qq.com') !== -1; },
      build: function () {
        return { platform: 'WeChatChannels', platform_cn: '微信视频号', supported: false, auto_generate: false,
          embed_url: null, iframe: null,
          restrictions: '微信视频号基本不支持在第三方网站中用 iframe 嵌入：官方页面设置了 X-Frame-Options: DENY/SAMEORIGIN，外部浏览器无法直接嵌套播放；其播放依赖微信环境内的 JS-SDK（wx.config / wx.ready）与播放凭证，无法在普通网页复现。',
          note: '可行替代：在网页放视频号封面 + 跳转链接，或仅在微信公众号 / 小程序内使用。本工具无法为视频号生成可用的外站嵌入代码。' };
      }
    },
    {
      key: 'M1905', cn: '1905电影网',
      test: function (url) { return url.indexOf('1905.com') !== -1; },
      build: function () {
        return { platform: 'M1905', platform_cn: '1905电影网', supported: false, auto_generate: false,
          embed_url: null, iframe: null,
          restrictions: '1905 电影网（CCTV6 电影网）不提供标准的第三方网站 iframe 嵌入功能：视频播放页没有“分享→嵌入代码”入口；其播放地址由后端动态签名接口（getVideoinfo.php，带 nonce/expiretime/sha1 signature）生成并含防盗链，无法像 YouTube / B 站那样用固定 iframe 地址稳定嵌入；跨域与 Referer 校验会拦截外部嵌套。',
          note: '可行替代：在网页放视频封面 + 跳转链接到 1905 原播放页；或确认拥有版权后下载视频自行托管（HTML5 <video>）。本工具无法为 1905 生成可用的外站嵌入代码。' };
      }
    }
  ];

  /* ---------- 主流程：遍历平台表，命中即构建 ---------- */
  function generateEmbedCode(url, opts) {
    opts = opts || {};
    var o = {
      width: opts.width || 560, height: opts.height || 315,
      autoplay: !!opts.autoplay, muted: !!opts.muted, loop: !!opts.loop,
      start: parseInt(opts.start || 0, 10), page: parseInt(opts.page || 1, 10),
      privacy_enhanced: !!opts.privacy_enhanced
    };
    url = (url || '').trim();
    for (var i = 0; i < PLATFORMS.length; i++) {
      var p = PLATFORMS[i];
      var m = p.re ? url.match(p.re) : (p.test && p.test(url) ? [url] : null);
      if (m) return p.build(m, o, url);
    }
    return { platform: null, platform_cn: '未知', supported: false, auto_generate: false,
      embed_url: null, iframe: null,
      restrictions: '未能识别该链接所属的视频平台，或该平台不支持标准 iframe 嵌入。受支持平台：YouTube / Vimeo / Bilibili / 腾讯视频 / 优酷 / 爱奇艺 / 抖音 / TikTok / Facebook / Dailymotion。',
      note: '如为微信视频号，则外部 iframe 嵌入不受支持。' };
  }

  return { generateEmbedCode: generateEmbedCode, buildIframe: buildIframe, makeResult: makeResult, PLATFORMS: PLATFORMS };
});
