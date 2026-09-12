#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
embed_generator.py  （vcode 工具 · 重构版）
========================================================================
接收一条视频链接，自动识别其所属平台，并返回对应的标准 iframe 嵌入
播放器代码，用于在第三方网站中播放。

重构要点（相对旧版）：
  1. 声明式平台表（PLATFORMS）：把原先 10+ 个 if/else 分支收敛为
     “match(url) + build(url, o)”的数据驱动结构，新增平台只改表、不动主流程。
  2. 抽取公共播放参数拼接（_play_qs），消除各平台重复的
     autoplay/muted/loop 拼串代码。
  3. 与前端 embed-generator.js 保持“同一套平台表”的语义，便于两端同步维护。
  4. 腾讯 / Facebook 的易错点（封面页、非视频页）保留为具名守卫函数。

用法：
    from embed_generator import generate_embed_code
    res = generate_embed_code("https://www.youtube.com/watch?v=abcdEFGhijk")
    print(res["iframe"])

返回值（dict）：
    platform / platform_cn / supported / auto_generate /
    embed_url / iframe / restrictions / note
调研日期：2026-09-12
========================================================================
"""

import re
from urllib.parse import quote


def _build_iframe(embed_url, width, height, extra_attrs=""):
    return (
        f'<iframe src="{embed_url}" width="{width}" height="{height}" '
        f'frameborder="0" allowfullscreen '
        f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; '
        f'gyroscope; picture-in-picture; web-share" {extra_attrs}></iframe>'
    )


def _result(platform, cn, supported, auto_gen, embed_url, width, height,
            restrictions, note, extra_attrs=""):
    return {
        "platform": platform,
        "platform_cn": cn,
        "supported": supported,
        "auto_generate": auto_gen,
        "embed_url": embed_url,
        "iframe": _build_iframe(embed_url, width, height, extra_attrs) if embed_url else None,
        "restrictions": restrictions,
        "note": note,
    }


def _play_qs(autoplay, muted, loop):
    q = []
    if autoplay:
        q.append("autoplay=1")
    if muted:
        q.append("mute=1")
    if loop:
        q.append("loop=1")
    return q


# ----------------------------------------------------------------------
# 易错点守卫（具名函数，便于测试与复用）
# ----------------------------------------------------------------------

def _tencent_vid(url):
    """从 v.qq.com 链接提取腾讯视频 vid。返回 (vid, warning)。

    合法格式：/x/page/<vid>.html、/x/cover/<cid>/<vid>.html（两级），
             或 ?vid=<vid> 查询参数（官方分享代码常见写法）。
    陷阱：/x/cover/<cid>.html 是封面/合集页，其 <cid> 不是可嵌入的 vid。
    """
    from urllib.parse import urlparse, parse_qs
    u = urlparse(url)
    # 查询参数分支（与前端 embed-generator.js 的 tencentVid 保持一致）
    qs = parse_qs(u.query)
    if 'vid' in qs and qs['vid'][0]:
        seg = qs['vid'][0]
        if re.fullmatch(r'[a-zA-Z0-9]+', seg):
            return seg, None
        return None, "从链接中提取到的视频 ID 格式不正确。"
    parts = [p for p in u.path.rstrip('/').split('/') if p]
    if len(parts) >= 2 and parts[0] == 'x' and parts[1] == 'cover':
        if len(parts) < 4:
            return None, ("该链接是腾讯视频的封面/合集页（非单个视频），无法嵌入。"
                          "请打开具体某一集/视频，复制其播放页地址"
                          "（形如 v.qq.com/x/cover/<cid>/<vid>.html）后再生成。")
        seg = parts[3].split('.')[0]
    elif len(parts) >= 2 and parts[0] == 'x' and parts[1] == 'page':
        seg = parts[-1].split('.')[0]
    else:
        return None, None
    if re.fullmatch(r'[a-zA-Z0-9]+', seg):
        return seg, None
    return None, "从链接中提取到的视频 ID 格式不正确。"


def _is_facebook_video(url):
    if 'fb.watch' in url:
        return True
    return bool(re.search(r'facebook\.com/(?:[^/]+/)?(?:videos|reel|watch)(?:[/?]|$)', url))


# ----------------------------------------------------------------------
# 各平台 build 函数（输入 url 与归一化参数 o，返回结果 dict）
# ----------------------------------------------------------------------

def _yt(url, o):
    host = "www.youtube-nocookie.com" if o["privacy_enhanced"] else "www.youtube.com"
    q = _play_qs(o["autoplay"], o["muted"], o["loop"])
    if o["start"]:
        q.append("start=%d" % o["start"])
    embed = "https://%s/embed/%s%s" % (host, o["vid"], ("?" + "&".join(q)) if q else "")
    return _result("YouTube", "YouTube", True, True, embed, o["width"], o["height"],
                   "上传者可在 YouTube Studio 关闭“允许嵌入”；年龄限制视频在外站会被重定向回 YouTube；"
                   "面向儿童的内容需自我申报；自动播放必须静音；使用 IFrame Player API 时需正确设置 HTTP Referer，否则报错 153。",
                   "官方分享→“嵌入”可直接复制，也支持 oEmbed。本工具可从 watch / youtu.be / shorts 链接自动生成。")


def _vimeo(url, o):
    q = _play_qs(o["autoplay"], o["muted"], o["loop"])
    if o["start"]:
        q.append("#t=%ds" % o["start"])
    embed = "https://player.vimeo.com/video/%s%s" % (o["vid"], ("?" + "&".join(q)) if q else "")
    return _result("Vimeo", "Vimeo", True, True, embed, o["width"], o["height"],
                   "上传者可在隐私设置中限制嵌入范围（Anywhere / Nowhere / 指定域名，最多 50 个）；"
                   "“自定义 URL”视频不可嵌入；隐藏控件、播放器配色等高级参数需 Plus 及以上付费套餐。",
                   "官方分享→Embed 可复制，支持 oEmbed。本工具从 vimeo.com/<id> 自动生成。")


def _bilibili(url, o):
    params = ["bvid=%s" % o["vid"], "page=%d" % o["page"], "high_quality=1", "danmaku=0"]
    if o["autoplay"]:
        params.append("autoplay=1")
    if o["muted"]:
        params.append("mute=1")
    if o["start"]:
        params.append("t=%d" % o["start"])
    embed = "https://player.bilibili.com/player.html?" + "&".join(params)
    return _result("Bilibili", "哔哩哔哩", True, True, embed, o["width"], o["height"],
                   "视频需开启“允许嵌入”；部分视频需携带正确 Referer；high_quality 仅在视频本身支持时生效；"
                   "弹幕默认开启（danmaku=0 关闭）；移动端需自行做响应式适配。B 站嵌入无广告。",
                   "官方分享→“嵌入代码”可复制。本工具可从 BV 号 / av 号链接自动生成。")


def _tencent(url, o):
    tvid, twarn = _tencent_vid(url)
    if tvid:
        embed = "https://v.qq.com/txp/iframe/player.html?vid=" + tvid
        return _result("Tencent", "腾讯视频", True, True, embed, o["width"], o["height"],
                       "视频须在后台开启“允许外链播放”；vid 区分大小写；部分老视频已下线或设为仅 App 内播放，会返回 404/空白；"
                       "广告无法由嵌入方控制（旧 iframe 路径可去广告，但可能失效）。",
                       "官方分享→“嵌入代码/通用代码”可复制，其中 src 里的 vid 即视频 ID。本工具从 v.qq.com 链接提取 vid 自动生成；"
                       "若仍提示 vid 非法，多半是复制到了封面/合集页，请改用具体视频地址，或直接使用官方分享代码。")
    return {"platform": "Tencent", "platform_cn": "腾讯视频", "supported": True,
            "auto_generate": False, "embed_url": None, "iframe": None,
            "restrictions": twarn or "未能从链接中识别腾讯视频 ID。",
            "note": "请复制具体视频播放页地址（v.qq.com/x/page/<vid>.html 或 "
                    "v.qq.com/x/cover/<cid>/<vid>.html），或使用官方分享→嵌入代码里的 vid。"}


def _youku(url, o):
    return _result("Youku", "优酷", True, True, "https://player.youku.com/embed/" + o["vid"],
                   o["width"], o["height"],
                   "优酷已停止公开 HTML5 嵌入，仅提供受限的 iframe 分享代码；视频须开启“允许第三方网站嵌入”；"
                   "不支持自动播放（移动端无效）；旧版 Flash 播放器已停用；未开启权限则返回空白。",
                   "官方分享→“通用代码”可复制（仅限开启嵌入权限的视频）。本工具从 v_show/id_ 链接提取 ID 自动生成。")


def _iqiyi(url, o):
    return _result("iQiyi", "爱奇艺", True, False, "https://www.iqiyi.com/player.html?vid=" + o["vid"],
                   o["width"], o["height"],
                   "爱奇艺嵌入限制最多：自动从 URL 拼装播放器地址不可靠，强烈建议使用官方分享→“通用代码/嵌入代码”复制的 iframe；"
                   "部分视频仅支持电脑端、移动端无法播放；很多版权/付费内容禁止外链。",
                   "官方分享面板提供“通用代码”。注意：从 URL 自动生成的 player.html 地址不一定可用，请以官方分享代码为准。")


def _douyin(url, o):
    embed = "https://open.douyin.com/player/video?vid=%s&autoplay=%d" % (o["vid"], 1 if o["autoplay"] else 0)
    return _result("Douyin", "抖音", True, False, embed, o["width"], o["height"],
                   "视频必须为“公开”状态（非公开返回 28003004 错误）；iframe 未做自适应，需自行设置宽高与样式；"
                   "父级容器宽度 < 730px 时会被强制按竖版渲染；需设置 referrerpolicy=\"unsafe-url\"。",
                   "抖音开放平台提供“通过 VideoID 获取 IFrame 代码”接口；本工具从 douyin.com/video/<id> 生成"
                   "（短链 v.douyin.com 需先在浏览器打开取得视频 ID）。",
                   extra_attrs='referrerpolicy="unsafe-url"')


def _tiktok(url, o):
    return _result("TikTok", "TikTok", True, True,
                   "https://www.tiktok.com/embed/v2/%s?lang=en-US" % o["vid"], o["width"], o["height"],
                   "仅公开视频可被嵌入；视频被删除后嵌入自动失效；自动播放受浏览器策略限制（需静音）；"
                   "官方嵌入为 blockquote + script，本工具提供等效 iframe；每嵌入一个视频都会加载约 120KB 的 TikTok SDK，过多会拖慢页面。",
                   "官方分享→Embed 可复制，WordPress/Webflow/Squarespace/Ghost 等支持 oEmbed（直接粘贴 URL 自动转换）。"
                   "本工具从 /video/<id> 链接生成等效 iframe。")


def _facebook(url, o):
    if not _is_facebook_video(url):
        return {"platform": "Facebook", "platform_cn": "Facebook", "supported": True,
                "auto_generate": False, "embed_url": None, "iframe": None,
                "restrictions": "Facebook 支持视频嵌入，但当前链接不是可嵌入的视频地址"
                                "（可能是照片、主页、个人或公开帖子，而非 /videos/、/watch、/reel 视频页）。",
                "note": "请使用 Facebook 视频页链接，形如 facebook.com/<用户名>/videos/<id>/ 、"
                        "facebook.com/watch/?v=<id> 或 facebook.com/reel/<id>/（fb.watch 短链亦可），并确保该视频为“公开”。"}
    href = quote(url, safe='')
    embed = "https://www.facebook.com/plugins/video.php?href=%s&show_text=0&width=%d" % (href, o["width"])
    return _result("Facebook", "Facebook", True, True, embed, o["width"], o["height"],
                   "被嵌入的帖子/视频必须是“公开”的；隐私、好友分组、年龄限制、地区限制或已删除的内容不会渲染；"
                   "需通过 Facebook 官方插件端点（plugins/video.php），原始 URL 作为 href 参数；加载会引入 Facebook 追踪 Cookie。",
                   "官方 ⋯→“嵌入”可复制标准 iframe；多数 CMS 直接粘贴 URL 也能自动转换。"
                   "本工具仅对 Facebook 视频页（/videos/、/watch、/reel、fb.watch）生成官方插件 iframe，非视频链接会提示改用视频地址。")


def _dailymotion(url, o):
    q = _play_qs(o["autoplay"], o["muted"], o["loop"])
    embed = "https://www.dailymotion.com/embed/video/%s%s" % (o["vid"], ("?" + "&".join(q)) if q else "")
    return _result("Dailymotion", "Dailymotion", True, True, embed, o["width"], o["height"],
                   "上传者可在隐私设置中限制可嵌入的域名；部分内容受地区版权限制；免费账户嵌入可能带平台水印/广告。",
                   "官方分享→“嵌入”可复制，支持 oEmbed。本工具从 dailymotion.com/video/<id> 或 dai.ly/<id> 自动生成。")


def _wechat(url, o):
    return {"platform": "WeChatChannels", "platform_cn": "微信视频号", "supported": False,
            "auto_generate": False, "embed_url": None, "iframe": None,
            "restrictions": "微信视频号基本不支持在第三方网站中用 iframe 嵌入：官方页面设置了 "
                            "X-Frame-Options: DENY/SAMEORIGIN，外部浏览器无法直接嵌套播放；"
                            "其播放依赖微信环境内的 JS-SDK（wx.config / wx.ready）与播放凭证，无法在普通网页复现。",
            "note": "可行替代：在网页放视频号封面 + 跳转链接，或仅在微信公众号 / 小程序内使用。本工具无法为视频号生成可用的外站嵌入代码。"}


def _m1905(url, o):
    return {"platform": "M1905", "platform_cn": "1905电影网", "supported": False,
            "auto_generate": False, "embed_url": None, "iframe": None,
            "restrictions": "1905 电影网（CCTV6 电影网）不提供标准的第三方网站 iframe 嵌入功能：视频播放页没有“分享→嵌入代码”入口；"
                            "其播放地址由后端动态签名接口（getVideoinfo.php，带 nonce/expiretime/sha1 signature）生成并含防盗链，"
                            "无法像 YouTube / B 站那样用固定 iframe 地址稳定嵌入；跨域与 Referer 校验会拦截外部嵌套。",
            "note": "可行替代：在网页放视频封面 + 跳转链接到 1905 原播放页；或确认拥有版权后下载视频自行托管（HTML5 <video>）。"
                    "本工具无法为 1905 生成可用的外站嵌入代码。"}


# ----------------------------------------------------------------------
# 平台声明表（数据驱动，新增平台只改这里）
# match: 返回 True/False 表示该 url 是否属于本平台
# build: 返回结果 dict（可从 o 取 vid 等已提取字段）
# ----------------------------------------------------------------------
PLATFORMS = [
    {"key": "YouTube", "cn": "YouTube",
     "match": lambda u: bool(re.search(r'(?:youtube\.com/(?:watch\?v=|embed/|shorts/|live/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})', u)),
     "build": _yt, "arg": "vid"},
    {"key": "Vimeo", "cn": "Vimeo",
     "match": lambda u: bool(re.search(r'vimeo\.com/(?:video/)?(\d+)', u)),
     "build": _vimeo, "arg": "vid"},
    {"key": "Bilibili", "cn": "哔哩哔哩",
     "match": lambda u: bool(re.search(r'bilibili\.com/video/(BV[0-9A-Za-z]+)', u)),
     "build": _bilibili, "arg": "vid"},
    {"key": "Tencent", "cn": "腾讯视频",
     "match": lambda u: 'v.qq.com' in u,
     "build": _tencent},
    {"key": "Youku", "cn": "优酷",
     "match": lambda u: bool(re.search(r'v\.youku\.com/v_show/id_([\w=]+)\.html', u)),
     "build": _youku, "arg": "vid"},
    {"key": "iQiyi", "cn": "爱奇艺",
     "match": lambda u: bool(re.search(r'iqiyi\.com/(?:v_|w_|a_|l_)?([\w]+)\.html', u)),
     "build": _iqiyi, "arg": "vid"},
    {"key": "Douyin", "cn": "抖音",
     "match": lambda u: bool(re.search(r'douyin\.com/(?:video/)?(\d{10,})', u)),
     "build": _douyin, "arg": "vid"},
    {"key": "TikTok", "cn": "TikTok",
     "match": lambda u: bool(re.search(r'tiktok\.com/@[\w.-]+/video/(\d+)', u)),
     "build": _tiktok, "arg": "vid"},
    {"key": "Facebook", "cn": "Facebook",
     "match": lambda u: 'facebook.com' in u or 'fb.watch' in u,
     "build": _facebook},
    {"key": "Dailymotion", "cn": "Dailymotion",
     "match": lambda u: bool(re.search(r'dailymotion\.com/(?:video/|embed/|#/video/)([a-zA-Z0-9]+)', u)
                              or re.search(r'dai\.ly/([a-zA-Z0-9]+)', u)),
     "build": _dailymotion, "arg": "vid"},
    {"key": "WeChatChannels", "cn": "微信视频号",
     "match": lambda u: 'channels.weixin.qq.com' in u or 'weixin.qq.com' in u,
     "build": _wechat},
    {"key": "M1905", "cn": "1905电影网",
     "match": lambda u: '1905.com' in u,
     "build": _m1905},
]


def generate_embed_code(url, width=560, height=315, autoplay=False, muted=False,
                        loop=False, start=0, page=1, privacy_enhanced=False):
    """根据视频链接返回标准嵌入播放器代码（数据驱动主流程）。"""
    url = (url or "").strip()
    o = {
        "width": width, "height": height,
        "autoplay": autoplay, "muted": muted, "loop": loop,
        "start": int(start or 0), "page": int(page or 1),
        "privacy_enhanced": privacy_enhanced,
    }
    for spec in PLATFORMS:
        if spec["match"](url):
            # 提取各平台正则里的 ID，注入到 o 供 build 使用
            if "arg" in spec:
                m = re.search(_PATTERNS[spec["key"]], url)
                if m:
                    o[spec["arg"]] = m.group(1)
            return spec["build"](url, o)
    return {"platform": None, "platform_cn": "未知", "supported": False, "auto_generate": False,
            "embed_url": None, "iframe": None,
            "restrictions": "未能识别该链接所属的视频平台，或该平台不支持标准 iframe 嵌入。"
                            "受支持平台：YouTube / Vimeo / Bilibili / 腾讯视频 / 优酷 / 爱奇艺 / 抖音 / TikTok / Facebook / Dailymotion。",
            "note": "如为微信视频号，则外部 iframe 嵌入不受支持。"}


# 与 PLATFORMS 中 match 对应的“取 ID 正则”（仅带 arg 的平台需要）
_PATTERNS = {
    "YouTube": r'(?:youtube\.com/(?:watch\?v=|embed/|shorts/|live/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})',
    "Vimeo": r'vimeo\.com/(?:video/)?(\d+)',
    "Bilibili": r'bilibili\.com/video/(BV[0-9A-Za-z]+)',
    "Youku": r'v\.youku\.com/v_show/id_([\w=]+)\.html',
    "iQiyi": r'iqiyi\.com/(?:v_|w_|a_|l_)?([\w]+)\.html',
    "Douyin": r'douyin\.com/(?:video/)?(\d{10,})',
    "TikTok": r'tiktok\.com/@[\w.-]+/video/(\d+)',
    "Dailymotion": r'(?:dailymotion\.com/(?:video/|embed/|#/video/)|dai\.ly/)([a-zA-Z0-9]+)',
}


if __name__ == "__main__":
    samples = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.bilibili.com/video/BV1xx411c7mu",
        "https://v.qq.com/x/cover/mzc00200glm30th/u00336fqv1a.html",
        "https://v.qq.com/x/cover/mzc00200glm30th",
        "https://www.facebook.com/zuck/videos/10156039228741123/",
        "https://www.facebook.com/photo.php?fbid=123",
        "https://www.douyin.com/video/7357934509125389631",
        "https://www.tiktok.com/@user/video/7415240528377154821",
        "https://www.dailymotion.com/video/x8a1b2c",
        "https://channels.weixin.qq.com/p/c1d2e3f4",
    ]
    for s in samples:
        r = generate_embed_code(s)
        print("=" * 70)
        print("输入:", s)
        print("平台:", r["platform_cn"], "| 支持嵌入:", r["supported"], "| 生成:", bool(r["iframe"]))
        if r.get("iframe"):
            print("代码:", r["iframe"])
        else:
            print("说明:", r["restrictions"])
