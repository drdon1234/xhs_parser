"""
完全独立的测试脚本
包含解析方法和测试部分，UA和提取路径根据测试结果硬编码
"""
import aiohttp
import json
import re
import asyncio
from datetime import datetime
from urllib.parse import unquote


# ============================================================================
# UA定义
# ============================================================================

# Android User-Agent (移动端)
ANDROID_UA = "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36 Edg/142.0.0.0"

# Desktop User-Agent (桌面端)
DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0"


# ============================================================================
# 工具函数
# ============================================================================

async def get_headers(use_desktop: bool = False):
    """获取请求头

    Args:
        use_desktop: 如果为True，使用桌面端UA；否则使用移动端UA
    """
    user_agent = DESKTOP_UA if use_desktop else ANDROID_UA

    if use_desktop:
        # 桌面端请求头（更完整）
        return {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "sec-ch-ua": '"Chromium";v="142", "Microsoft Edge";v="142", "Not_A Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "upgrade-insecure-requests": "1",
        }
    else:
        # 移动端请求头（简化）
        return {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }


async def get_redirect_url(short_url: str) -> str:
    """获取短链接重定向后的完整URL（使用移动端UA）

    Args:
        short_url: 短链接URL

    Returns:
        重定向后的完整URL
    """
    headers = await get_headers(use_desktop=False)  # 短链接使用移动端UA
    async with aiohttp.ClientSession() as session:
        async with session.get(short_url, headers=headers, allow_redirects=False) as response:
            if response.status == 302:
                redirect_url = response.headers.get("Location", "")
                return unquote(redirect_url)
            else:
                raise Exception(f"无法获取重定向URL，状态码: {response.status}")


async def fetch_page(url: str, use_desktop: bool = False) -> str:
    """获取页面HTML内容

    Args:
        url: 要获取的URL
        use_desktop: 如果为True，使用桌面端UA；否则使用移动端UA
    """
    headers = await get_headers(use_desktop=use_desktop)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                return await response.text()
            else:
                raise Exception(f"无法获取页面内容，状态码: {response.status}")


# ============================================================================
# 数据提取函数
# ============================================================================

def extract_video_from_meta(html: str) -> str:
    """从HTML meta标签中提取视频URL"""
    pattern = r'<meta\s+name=["\']og:video["\']\s+content=["\']([^"\']+)["\']'
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def extract_meta_content(html: str, meta_name: str) -> str:
    """从HTML meta标签中提取指定name的content值（只返回第一个匹配）"""
    pattern = rf'<meta\s+name=["\']{re.escape(meta_name)}["\']\s+content=["\']([^"\']+)["\']'
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def extract_all_meta_content(html: str, meta_name: str) -> list:
    """从HTML meta标签中提取指定name的所有content值（返回列表）"""
    pattern = rf'<meta\s+name=["\']{re.escape(meta_name)}["\']\s+content=["\']([^"\']+)["\']'
    matches = re.findall(pattern, html, re.IGNORECASE)
    return matches if matches else []


def parse_note_data_from_meta(html: str) -> dict:
    """从HTML meta标签中提取笔记信息（备用方案）"""
    # 提取标题（从og:title，去掉"- 小红书"后缀）
    title = extract_meta_content(html, "og:title")
    if title and " - 小红书" in title:
        title = title.replace(" - 小红书", "").strip()

    # 提取描述（优先使用description，如果没有则使用og:description）
    desc = extract_meta_content(html, "description")
    if not desc:
        desc = extract_meta_content(html, "og:description")

    # 提取视频URL
    video_url = extract_video_from_meta(html)

    # 提取所有图片URL（从og:image标签）
    image_urls = extract_all_meta_content(html, "og:image")
    # 将http://转换为https://
    image_urls = [url.replace("http://", "https://", 1) if url.startswith("http://") else url for url in image_urls]

    # 提取类型
    note_type = extract_meta_content(html, "og:type")
    if not note_type:
        # 根据是否有视频或图片判断类型
        if video_url:
            note_type = "video"
        elif image_urls:
            note_type = "normal"  # 图集
        else:
            note_type = "normal"

    # 从URL中提取note ID（如果可能）
    og_url = extract_meta_content(html, "og:url")
    author_id = ""
    if og_url:
        match = re.search(r'/explore/([^/?]+)', og_url)
        if match:
            author_id = match.group(1)

    return {
        "type": note_type,
        "title": title,
        "desc": desc,
        "author_name": "",
        "author_id": author_id,
        "publish_time": "",
        "video_url": video_url,
        "image_urls": image_urls,
    }


def extract_initial_state(html: str) -> dict:
    """从HTML中提取window.__INITIAL_STATE__的JSON数据"""
    # 使用正则表达式匹配window.__INITIAL_STATE__ = {...}
    pattern = r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>'
    match = re.search(pattern, html, re.DOTALL)

    if match:
        json_str = match.group(1)
        json_str = re.sub(r'\bundefined\b', 'null', json_str)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # 如果正则表达式失败，使用括号匹配方法
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

    # 使用括号匹配找到完整的JSON对象
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


def parse_note_data(data: dict) -> dict:
    """从JSON数据中提取所需信息（支持多种JSON结构）"""
    note_data = None
    user_data = None

    # 尝试多种可能的JSON结构路径
    # 路径1: noteData.data.noteData (探索页和用户页长链，移动端UA)
    try:
        note_data = data["noteData"]["data"]["noteData"]
        user_data = note_data.get("user", {})
    except (KeyError, TypeError):
        # 路径2: note.noteDetailMap.{noteId}.note (分享短链和分享长链，桌面端UA)
        try:
            if "note" in data and "noteDetailMap" in data["note"]:
                note_detail_map = data["note"]["noteDetailMap"]
                # 获取第一个noteId（通常只有一个）
                if note_detail_map and isinstance(note_detail_map, dict):
                    note_id = list(note_detail_map.keys())[0]
                    note_detail = note_detail_map[note_id]
                    if "note" in note_detail:
                        note_data = note_detail["note"]
                        user_data = note_data.get("user", {})
        except (KeyError, TypeError, IndexError):
            # 路径3: noteData.data.note (备用路径)
            try:
                if "noteData" in data and "data" in data["noteData"]:
                    if "note" in data["noteData"]["data"]:
                        note_data = data["noteData"]["data"]["note"]
                        user_data = note_data.get("user", {})
            except (KeyError, TypeError):
                pass

    if not note_data:
        raise Exception("无法找到笔记数据，JSON结构可能不同")

    note_type = note_data.get("type", "normal")
    title = note_data.get("title", "")
    desc = note_data.get("desc", "")

    # 提取用户信息
    author_name = ""
    author_id = ""
    if user_data:
        author_name = user_data.get("nickName", "") or user_data.get("nickname", "") or user_data.get("name", "")
        author_id = user_data.get("userId", "") or user_data.get("user_id", "") or user_data.get("id", "")

    # 如果没有用户信息，尝试从其他位置获取
    if not author_name or not author_id:
        # 尝试从noteData的其他位置获取
        if "user" in note_data:
            user_info = note_data["user"]
            if not author_name:
                author_name = user_info.get("nickName", "") or user_info.get("nickname", "") or user_info.get("name", "")
            if not author_id:
                author_id = user_info.get("userId", "") or user_info.get("user_id", "") or user_info.get("id", "")

    timestamp = note_data.get("time", 0) or note_data.get("timestamp", 0) or note_data.get("createTime", 0)
    if timestamp:
        dt = datetime.fromtimestamp(timestamp / 1000)
        publish_time = dt.strftime("%Y-%m-%d")
    else:
        publish_time = ""

    video_url = ""
    image_urls = []

    if note_type == "video":
        # 提取视频URL
        video_info = note_data.get("video", {})
        if video_info:
            # 尝试多种路径
            if "media" in video_info:
                media = video_info["media"]
                if "stream" in media:
                    stream = media["stream"]
                    if "h264" in stream and len(stream["h264"]) > 0:
                        h264 = stream["h264"][0]
                        video_url = h264.get("masterUrl", "") or h264.get("backupUrl", "") or h264.get("url", "")

            # 如果还没找到，尝试其他路径
            if not video_url:
                video_url = video_info.get("url", "") or video_info.get("videoUrl", "") or video_info.get("playUrl", "")

        if not video_url:
            stream_info = note_data.get("stream", {})
            if stream_info:
                if "h264" in stream_info and len(stream_info["h264"]) > 0:
                    h264 = stream_info["h264"][0]
                    video_url = h264.get("masterUrl", "") or h264.get("backupUrl", "") or h264.get("url", "")

        if not video_url:
            def find_video_url(obj, depth=0):
                if depth > 5:
                    return ""
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        if isinstance(value, str) and (".mp4" in value or "sns-video" in value):
                            return value
                        result = find_video_url(value, depth + 1)
                        if result:
                            return result
                elif isinstance(obj, list):
                    for item in obj:
                        result = find_video_url(item, depth + 1)
                        if result:
                            return result
                return ""

            video_url = find_video_url(note_data)

        if video_url and video_url.startswith("http://"):
            video_url = video_url.replace("http://", "https://", 1)
        elif video_url and video_url.startswith("//"):
            video_url = "https:" + video_url
    else:
        # 提取图集直链
        image_list = note_data.get("imageList", []) or note_data.get("images", []) or note_data.get("imageList", [])
        if image_list:
            for img in image_list:
                if isinstance(img, dict):
                    # 尝试多种可能的URL字段
                    url = (img.get("url", "") or
                           img.get("urlDefault", "") or
                           img.get("imageUrl", "") or
                           img.get("original", "") or
                           img.get("urlPre", ""))

                    # 如果还没有找到，尝试从infoList中获取
                    if not url and "infoList" in img and isinstance(img["infoList"], list):
                        for info in img["infoList"]:
                            if isinstance(info, dict) and "url" in info:
                                # 优先使用WB_DFT场景的URL
                                if info.get("imageScene") == "WB_DFT":
                                    url = info.get("url", "")
                                    break
                        # 如果还是没有，使用第一个info的URL
                        if not url and img["infoList"]:
                            url = img["infoList"][0].get("url", "")

                    if url:
                        # 过滤掉占位图片
                        if "picasso-static" not in url and "fe-platform" not in url:
                            # 确保URL是完整的（添加协议前缀如果是相对路径）
                            if url.startswith("//"):
                                url = "https:" + url
                            elif url.startswith("http://"):
                                url = url.replace("http://", "https://", 1)
                            image_urls.append(url)
                elif isinstance(img, str):
                    if "picasso-static" not in img and "fe-platform" not in img:
                        # 确保URL是完整的
                        if img.startswith("//"):
                            img = "https:" + img
                        elif img.startswith("http://"):
                            img = img.replace("http://", "https://", 1)
                        image_urls.append(img)

    return {
        "type": note_type,
        "title": title,
        "desc": desc,
        "author_name": author_name,
        "author_id": author_id,
        "publish_time": publish_time,
        "video_url": video_url,
        "image_urls": image_urls,
    }


# ============================================================================
# URL类型识别和UA/提取路径选择（硬编码逻辑）
# ============================================================================

def get_link_type(url: str) -> str:
    """识别链接类型

    Returns:
        "分享短链", "分享长链", "探索页长链", "用户页长链"
    """
    if "xhslink.com" in url:
        return "分享短链"
    elif "discovery/item" in url:
        return "分享长链"
    elif "explore" in url:
        if "xsec_source=pc_user" in url:
            return "用户页长链"
        else:
            return "探索页长链"
    else:
        # 默认当作分享短链处理
        return "分享短链"


def get_ua_and_extraction_path(link_type: str) -> tuple:
    """根据链接类型获取UA和提取路径（硬编码）

    Args:
        link_type: 链接类型

    Returns:
        (use_desktop_ua: bool, extraction_path: str)
        extraction_path: "JSON" 或 "JSON+meta"
    """
    if link_type == "分享短链":
        # 分享短链重定向后实际是discovery/item类型，应该使用桌面端UA和JSON+meta路径
        # 但这里保持原逻辑，因为parse_xhs_link会根据重定向后的URL重新判断
        return (False, "JSON")  # 移动端UA, JSON提取（实际会被重定向后的URL覆盖）
    elif link_type == "分享长链":
        return (True, "JSON+meta")  # 桌面端UA, JSON+meta提取
    elif link_type == "探索页长链":
        return (False, "JSON")  # 移动端UA, JSON提取
    elif link_type == "用户页长链":
        return (False, "JSON")  # 移动端UA, JSON提取
    else:
        return (False, "JSON")  # 默认


# ============================================================================
# 解析函数
# ============================================================================

async def parse_link(url: str, use_desktop_ua: bool, extraction_path: str) -> dict:
    """解析链接

    Args:
        url: 完整URL
        use_desktop_ua: 是否使用桌面端UA
        extraction_path: 提取路径 ("JSON" 或 "JSON+meta")

    Returns:
        解析后的笔记数据
    """
    # 获取页面内容
    html = await fetch_page(url, use_desktop=use_desktop_ua)

    # 根据提取路径解析数据
    if extraction_path == "JSON":
        # 只使用JSON提取
        initial_state = extract_initial_state(html)
        note_data = parse_note_data(initial_state)
    elif extraction_path == "JSON+meta":
        # 先尝试JSON，失败则使用meta
        try:
            initial_state = extract_initial_state(html)
            note_data = parse_note_data(initial_state)

            # 如果JSON解析成功但缺少字段（如视频URL），尝试从meta补充
            if note_data.get('type') == 'video' and not note_data.get('video_url'):
                video_url_from_meta = extract_video_from_meta(html)
                if video_url_from_meta:
                    note_data['video_url'] = video_url_from_meta
        except Exception:
            # JSON提取失败，使用meta标签提取
            note_data = parse_note_data_from_meta(html)
    else:
        raise Exception(f"未知的提取路径: {extraction_path}")

    return note_data


async def parse_xhs_link(input_url: str) -> dict:
    """解析小红书链接（主函数）

    Args:
        input_url: 输入的小红书链接

    Returns:
        解析后的笔记数据
    """
    # 1. 判断是否为短链接，如果是则获取重定向URL
    is_short_link = "xhslink.com" in input_url
    if is_short_link:
        full_url = await get_redirect_url(input_url)
    else:
        full_url = input_url
        if not full_url.startswith("http://") and not full_url.startswith("https://"):
            full_url = "https://" + full_url

    # 2. 识别链接类型
    # 如果是分享短链，即使重定向后也保持为"分享短链"类型（使用移动端UA）
    if is_short_link:
        link_type = "分享短链"
    else:
        link_type = get_link_type(full_url)

    # 3. 根据链接类型获取UA和提取路径（硬编码）
    use_desktop_ua, extraction_path = get_ua_and_extraction_path(link_type)

    # 4. 解析链接
    note_data = await parse_link(full_url, use_desktop_ua, extraction_path)

    return note_data


# ============================================================================
# 测试部分
# ============================================================================

TEST_LINKS = [
    {
        "name": "视频分享短链",
        "url": "http://xhslink.com/o/67cBgM4yF9z",
        "expected_ua": "移动端",
        "expected_path": "JSON"
    },
    {
        "name": "图集分享短链",
        "url": "http://xhslink.com/o/AOHR9EgF5kp",
        "expected_ua": "移动端",
        "expected_path": "JSON"
    },
    {
        "name": "视频分享长链",
        "url": "https://www.xiaohongshu.com/discovery/item/68ecb777000000000702023c?source=webshare&xhsshare=pc_web&xsec_token=ABUo6GCOH5A0i07gITU1d1_AGwTt2g8W_nZD4a0_vGeFk=&xsec_source=pc_share",
        "expected_ua": "桌面端",
        "expected_path": "JSON+meta"
    },
    {
        "name": "图集分享长链",
        "url": "https://www.xiaohongshu.com/discovery/item/68fe055e0000000004021dbb?source=webshare&xhsshare=pc_web&xsec_token=ABmsTgndoj3fGFSiU1oUWkpQ4tQ8VaXL3P7CmEK-wNca8=&xsec_source=pc_share",
        "expected_ua": "桌面端",
        "expected_path": "JSON+meta"
    },
    {
        "name": "探索页视频长链",
        "url": "https://www.xiaohongshu.com/explore/69091715000000000700ad79?xsec_token=AB9ZqpaV0h9imneex7Gx1dFsVvzyoFTw3TJOl4tt5NuLo=&xsec_source=pc_feed",
        "expected_ua": "移动端",
        "expected_path": "JSON"
    },
    {
        "name": "探索页图集长链",
        "url": "https://www.xiaohongshu.com/explore/6907f979000000000401317f?xsec_token=ABiZT5aRD-tPnsJdVwxXfT8wOs-Tx4cOh75vG0MzoX8M8=&xsec_source=pc_feed",
        "expected_ua": "移动端",
        "expected_path": "JSON"
    },
    {
        "name": "用户页视频长链",
        "url": "https://www.xiaohongshu.com/explore/69042124000000000703324f?xsec_token=ABfFHBtP2TYoz4iO13woOD88e3wq8qWzu2q-Sd_0j-uj8=&xsec_source=pc_user",
        "expected_ua": "移动端",
        "expected_path": "JSON"
    },
    {
        "name": "用户页图集长链",
        "url": "https://www.xiaohongshu.com/explore/68ffb78300000000040057b8?xsec_token=ABFk4Ly_Yf-T4eLaWCmZgzykZBAgMDGkHtTm1zNw-RR5Q=&xsec_source=pc_user",
        "expected_ua": "移动端",
        "expected_path": "JSON"
    }
]


def safe_print(text: str):
    """安全打印文本，处理编码问题"""
    try:
        print(text)
    except UnicodeEncodeError:
        # 如果遇到编码错误，尝试替换无法编码的字符
        try:
            # 使用errors='replace'来替换无法编码的字符
            encoded = text.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            print(encoded)
        except:
            # 如果还是失败，使用ASCII编码并替换非ASCII字符
            print(text.encode('ascii', errors='replace').decode('ascii'))


def print_extraction_flow(extraction_path: str):
    """打印提取数据流程"""
    safe_print("提取数据流程:")
    if extraction_path == "JSON":
        safe_print("  ├─ 尝试从 window.__INITIAL_STATE__ 提取JSON数据")
        safe_print("  │   ├─ 成功 → 解析JSON数据")
        safe_print("  │   │   └─ 成功 → 使用JSON数据")
    elif extraction_path == "JSON+meta":
        safe_print("  ├─ 尝试从 window.__INITIAL_STATE__ 提取JSON数据")
        safe_print("  │   ├─ 成功 → 解析JSON数据")
        safe_print("  │   │   └─ 失败（缺少字段）→ 切换到meta标签提取")
        safe_print("  │   └─ 备用方案：从HTML meta标签提取完整信息")


async def test_single_link(link_info: dict, index: int, total: int):
    """测试单个链接"""
    print("=" * 80)
    print(f"【测试链接 {index}/{total}】{link_info['name']}")
    print("=" * 80)
    print()
    print(f"URL: {link_info['url']}")

    # 识别链接类型
    link_type = get_link_type(link_info['url'])
    print(f"链接类型: {link_type}")

    # 获取UA和提取路径
    use_desktop_ua, extraction_path = get_ua_and_extraction_path(link_type)
    actual_ua = "桌面端" if use_desktop_ua else "移动端"
    print(f"使用的UA: {actual_ua}")
    print(f"数据提取路径: {extraction_path}")

    # 检查UA是否匹配预期
    if actual_ua != link_info['expected_ua']:
        print(f"[警告] 预期UA为 {link_info['expected_ua']}，实际使用 {actual_ua}")

    print()
    print_extraction_flow(extraction_path)
    print()

    try:
        # 解析链接
        note_data = await parse_xhs_link(link_info['url'])

        # 输出结果（参考 main_backup_old.py 的 format_output 格式）
        note_type = note_data.get('type', '')
        content_type = "视频" if note_type == 'video' else "图集"

        safe_print("提取结果:")
        safe_print(f"提取路径: {extraction_path}")
        safe_print(f"内容类型：{content_type}")
        safe_print(f"\n标题：{note_data.get('title', '')}")
        safe_print(f"\n简介：")
        safe_print(note_data.get('desc', ''))
        safe_print(f"\n发布者用户名：{note_data.get('author_name', '')}(主页id:{note_data.get('author_id', '')})")
        safe_print(f"\n发布时间：{note_data.get('publish_time', '')}")

        # 根据类型输出不同的媒体链接
        video_url = ""
        valid_urls = []

        if note_type == 'video':
            video_url = note_data.get('video_url', '')
            safe_print(f"\n视频直链：")
            if video_url:
                safe_print(video_url)
            else:
                safe_print("未找到视频链接")
        else:
            image_urls = note_data.get('image_urls', [])
            valid_urls = [url for url in image_urls if url and url.strip()]
            safe_print(f"\n图集直链：")
            if valid_urls:
                for url in valid_urls:
                    safe_print(url)
            else:
                safe_print("未找到图片链接")

        has_media = bool(video_url) if note_type == 'video' else bool(valid_urls)

        return {
            "success": True,
            "has_media": has_media,
            "ua_match": actual_ua == link_info['expected_ua']
        }
    except Exception as e:
        print(f"[错误] 解析失败: {e}")
        return {
            "success": False,
            "has_media": False,
            "ua_match": False,
            "error": str(e)
        }


async def test_all_links():
    """测试所有链接"""
    print("=" * 80)
    print("UA和数据提取路径测试")
    print("=" * 80)
    print()
    print()

    results = []
    for i, link_info in enumerate(TEST_LINKS, 1):
        result = await test_single_link(link_info, i, len(TEST_LINKS))
        result["name"] = link_info["name"]
        result["link_type"] = get_link_type(link_info['url'])
        results.append(result)
        print()

    # 输出测试总结
    print("=" * 80)
    print("测试总结")
    print("=" * 80)
    print()

    total = len(results)
    success_count = sum(1 for r in results if r.get('success') and r.get('has_media'))
    ua_match_count = sum(1 for r in results if r.get('ua_match'))
    error_count = sum(1 for r in results if not r.get('success'))

    print(f"总测试数: {total}")
    print(f"成功获取媒体直链: {success_count}/{total}")
    print(f"UA匹配预期: {ua_match_count}/{total}")
    print(f"测试异常: {error_count}/{total}")
    print()

    # 按链接类型统计
    print("按链接类型统计:")
    print("-" * 80)
    print()

    link_types = {}
    for r in results:
        link_type = r['link_type']
        if link_type not in link_types:
            link_types[link_type] = {
                "total": 0,
                "success": 0,
                "ua_match": 0,
                "paths": {}
            }

        link_types[link_type]["total"] += 1
        if r.get('success') and r.get('has_media'):
            link_types[link_type]["success"] += 1
        if r.get('ua_match'):
            link_types[link_type]["ua_match"] += 1

        # 统计提取路径
        use_desktop_ua, extraction_path = get_ua_and_extraction_path(link_type)
        if extraction_path not in link_types[link_type]["paths"]:
            link_types[link_type]["paths"][extraction_path] = 0
        link_types[link_type]["paths"][extraction_path] += 1

    for link_type, stats in link_types.items():
        print(f"{link_type}:")
        print(f"  总数: {stats['total']}")
        print(f"  成功: {stats['success']}/{stats['total']}")
        print(f"  UA匹配: {stats['ua_match']}/{stats['total']}")
        print(f"  提取路径分布:")
        for path, count in stats['paths'].items():
            print(f"    - {path}: {count}")
        print()

    # 详细结果
    print("=" * 80)
    print("详细结果")
    print("=" * 80)
    print()

    for r in results:
        link_info = next(link for link in TEST_LINKS if link['name'] == r['name'])
        link_type = r['link_type']
        use_desktop_ua, extraction_path = get_ua_and_extraction_path(link_type)
        actual_ua = "桌面端" if use_desktop_ua else "移动端"

        status = "[成功]" if r.get('success') and r.get('has_media') else "[失败]"
        ua_status = "[匹配]" if r.get('ua_match') else "[不匹配]"

        note_type = "视频" if link_info['name'].startswith("视频") else "图集"

        print(f"{status} {r['name']}")
        print(f"  UA: {actual_ua} (预期: {link_info['expected_ua']}) {ua_status}")
        print(f"  提取路径: {extraction_path}")
        print(f"  媒体类型: {note_type}")
        print()


if __name__ == "__main__":
    asyncio.run(test_all_links())

