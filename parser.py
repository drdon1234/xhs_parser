"""
小红书链接解析器
统一使用移动端UA和JSON解析路径
"""
import aiohttp
import json
import re
from datetime import datetime
from urllib.parse import unquote, urlparse, parse_qs, urlencode, urlunparse


# ============================================================================
# UA定义
# ============================================================================

ANDROID_UA = "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36 Edg/142.0.0.0"


# ============================================================================
# 工具函数
# ============================================================================

def clean_share_url(url: str) -> str:
    """清理分享长链URL，删除source和xhsshare参数"""
    if "discovery/item" not in url:
        return url
    
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    query_params.pop('source', None)
    query_params.pop('xhsshare', None)
    
    flat_params = {}
    for key, value_list in query_params.items():
        flat_params[key] = value_list[0] if value_list and value_list[0] else ''
    
    new_query = urlencode(flat_params)
    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)


async def get_headers():
    """获取移动端请求头"""
    return {
        "User-Agent": ANDROID_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


async def get_redirect_url(short_url: str) -> str:
    """获取短链接重定向后的完整URL"""
    headers = await get_headers()
    async with aiohttp.ClientSession() as session:
        async with session.get(short_url, headers=headers, allow_redirects=False) as response:
            if response.status == 302:
                redirect_url = response.headers.get("Location", "")
                return unquote(redirect_url)
            else:
                raise Exception(f"无法获取重定向URL，状态码: {response.status}")


async def fetch_page(url: str) -> str:
    """获取页面HTML内容"""
    headers = await get_headers()
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                return await response.text()
            else:
                raise Exception(f"无法获取页面内容，状态码: {response.status}")


# ============================================================================
# 数据提取函数
# ============================================================================

def extract_initial_state(html: str) -> dict:
    """从HTML中提取window.__INITIAL_STATE__的JSON数据"""
    pattern = r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>'
    match = re.search(pattern, html, re.DOTALL)

    if match:
        json_str = match.group(1)
        json_str = re.sub(r'\bundefined\b', 'null', json_str)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    start_marker = 'window.__INITIAL_STATE__'
    start_idx = html.find(start_marker)
    if start_idx == -1:
        raise Exception("无法找到window.__INITIAL_STATE__数据")

    json_start = html.find('{', start_idx)
    if json_start == -1:
        raise Exception("无法找到JSON开始位置")

    script_end = html.find('</script>', start_idx)
    if script_end == -1:
        script_end = len(html)

    brace_count = 0
    json_end = json_start
    in_string = False
    escape_next = False
    in_single_quote = False

    search_end = min(script_end, len(html))
    for i in range(json_start, search_end):
        char = html[i]

        if escape_next:
            escape_next = False
            continue

        if char == '\\':
            escape_next = True
            continue

        if char == '"' and not escape_next and not in_single_quote:
            in_string = not in_string
            continue

        if char == "'" and not escape_next and not in_string:
            in_single_quote = not in_single_quote
            continue

        if not in_string and not in_single_quote:
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break

    if brace_count != 0:
        raise Exception("无法找到完整的JSON对象")

    json_str = html[json_start:json_end]
    json_str = re.sub(r'\bundefined\b', 'null', json_str)

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        error_pos = getattr(e, 'pos', 0)
        start_debug = max(0, error_pos - 200)
        end_debug = min(len(json_str), error_pos + 200)
        error_msg = f"JSON解析失败: {e}\n错误位置: {error_pos}\n附近内容: {json_str[start_debug:end_debug]}"
        raise Exception(error_msg)


def clean_topic_tags(text: str) -> str:
    """清理简介中的话题标签，将#标签[话题]#格式改为#标签"""
    if not text:
        return text
    pattern = r'#([^#\[]+)\[话题\]#'
    return re.sub(pattern, r'#\1', text)


def parse_note_data(data: dict) -> dict:
    """从JSON数据中提取所需信息"""
    # 统一使用 noteData.data.noteData 路径
    try:
        note_data = data["noteData"]["data"]["noteData"]
        user_data = note_data.get("user", {})
    except (KeyError, TypeError):
        raise Exception("无法找到笔记数据，JSON结构可能不同")

    note_type = note_data.get("type", "normal")
    title = note_data.get("title", "")
    desc = note_data.get("desc", "")

    # 提取用户信息：统一使用 user.nickName 和 user.userId
    author_name = ""
    author_id = ""
    if user_data:
        author_name = user_data.get("nickName", "")
        author_id = user_data.get("userId", "")

    # 提取时间戳：统一使用 time 字段
    timestamp = note_data.get("time", 0)
    if timestamp:
        dt = datetime.fromtimestamp(timestamp / 1000)
        publish_time = dt.strftime("%Y-%m-%d")
    else:
        publish_time = ""

    video_url = ""
    image_urls = []

    if note_type == "video":
        # 提取视频URL：统一使用 video.media.stream.h264[0].masterUrl
        video_info = note_data.get("video", {})
        if video_info and "media" in video_info:
            media = video_info["media"]
            if "stream" in media:
                stream = media["stream"]
                if "h264" in stream and len(stream["h264"]) > 0:
                    h264 = stream["h264"][0]
                    video_url = h264.get("masterUrl", "")

        if video_url and video_url.startswith("http://"):
            video_url = video_url.replace("http://", "https://", 1)
        elif video_url and video_url.startswith("//"):
            video_url = "https:" + video_url
    else:
        # 提取图集直链：统一使用 imageList[].url（元素为dict类型）
        image_list = note_data.get("imageList", [])
        if image_list:
            for img in image_list:
                if isinstance(img, dict):
                    url = img.get("url", "")
                    if url:
                        if "picasso-static" not in url and "fe-platform" not in url:
                            if url.startswith("//"):
                                url = "https:" + url
                            elif url.startswith("http://"):
                                url = url.replace("http://", "https://", 1)
                            image_urls.append(url)

    desc = clean_topic_tags(desc)
    
    # 准备返回数据
    result = {
        "type": note_type,
        "title": title,
        "desc": desc,
        "author_name": author_name,
        "author_id": author_id,
        "publish_time": publish_time,
        "video_url": video_url,
        "image_urls": image_urls,
    }
    
    return result


# ============================================================================
# 解析函数
# ============================================================================

async def parse_xhs_link(input_url: str) -> dict:
    """解析小红书链接（主函数）"""
    # 1. 判断是否为短链接，如果是则获取重定向URL
    if "xhslink.com" in input_url:
        full_url = await get_redirect_url(input_url)
    else:
        full_url = input_url
        if not full_url.startswith("http://") and not full_url.startswith("https://"):
            full_url = "https://" + full_url

    # 2. 清理分享长链URL（删除source和xhsshare参数）
    full_url = clean_share_url(full_url)

    # 3. 获取页面内容并解析
    html = await fetch_page(full_url)
    initial_state = extract_initial_state(html)
    note_data = parse_note_data(initial_state)

    return note_data

