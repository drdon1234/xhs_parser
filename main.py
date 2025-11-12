"""
小红书链接解析工具
统一使用移动端UA和JSON解析路径
"""
import aiohttp
import json
import re
import asyncio
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
    note_data = None
    user_data = None

    # 路径1: noteData.data.noteData
    try:
        note_data = data["noteData"]["data"]["noteData"]
        user_data = note_data.get("user", {})
    except (KeyError, TypeError):
        # 路径2: note.noteDetailMap.{noteId}.note
        try:
            if "note" in data and "noteDetailMap" in data["note"]:
                note_detail_map = data["note"]["noteDetailMap"]
                if note_detail_map and isinstance(note_detail_map, dict):
                    note_id = list(note_detail_map.keys())[0]
                    note_detail = note_detail_map[note_id]
                    if "note" in note_detail:
                        note_data = note_detail["note"]
                        user_data = note_data.get("user", {})
        except (KeyError, TypeError, IndexError):
            # 路径3: noteData.data.note
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

    if not author_name or not author_id:
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
            if "media" in video_info:
                media = video_info["media"]
                if "stream" in media:
                    stream = media["stream"]
                    if "h264" in stream and len(stream["h264"]) > 0:
                        h264 = stream["h264"][0]
                        video_url = h264.get("masterUrl", "") or h264.get("backupUrl", "") or h264.get("url", "")

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
        image_list = note_data.get("imageList", []) or note_data.get("images", [])
        if image_list:
            for img in image_list:
                if isinstance(img, dict):
                    url = (img.get("url", "") or
                           img.get("urlDefault", "") or
                           img.get("imageUrl", "") or
                           img.get("original", "") or
                           img.get("urlPre", ""))

                    if not url and "infoList" in img and isinstance(img["infoList"], list):
                        for info in img["infoList"]:
                            if isinstance(info, dict) and "url" in info:
                                if info.get("imageScene") == "WB_DFT":
                                    url = info.get("url", "")
                                    break
                        if not url and img["infoList"]:
                            url = img["infoList"][0].get("url", "")

                    if url:
                        if "picasso-static" not in url and "fe-platform" not in url:
                            if url.startswith("//"):
                                url = "https:" + url
                            elif url.startswith("http://"):
                                url = url.replace("http://", "https://", 1)
                            image_urls.append(url)
                elif isinstance(img, str):
                    if "picasso-static" not in img and "fe-platform" not in img:
                        if img.startswith("//"):
                            img = "https:" + img
                        elif img.startswith("http://"):
                            img = img.replace("http://", "https://", 1)
                        image_urls.append(img)

    desc = clean_topic_tags(desc)
    
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


# ============================================================================
# 测试部分
# ============================================================================

TEST_LINKS = [
    {
        "name": "视频分享短链",
        "url": "http://xhslink.com/o/67cBgM4yF9z",
    },
    {
        "name": "图集分享短链",
        "url": "http://xhslink.com/o/AOHR9EgF5kp",
    },
    {
        "name": "视频分享长链",
        "url": "https://www.xiaohongshu.com/discovery/item/6911c27f0000000003018875?source=webshare&xhsshare=pc_web&xsec_token=ABdFQJUhxKcZsFTj638F7Q905jLk-jViDfdTPzdcgla5E=&xsec_source=pc_share",
    },
    {
        "name": "图集分享长链",
        "url": "https://www.xiaohongshu.com/discovery/item/690636a7000000000401066c?source=webshare&xhsshare=pc_web&xsec_token=ABwNAVDOGOYhd1A5VzWRcQyT20ve6fNPJnHyeM5zHP42A=&xsec_source=pc_share",
    },
    {
        "name": "探索页视频长链",
        "url": "https://www.xiaohongshu.com/explore/69091715000000000700ad79?xsec_token=AB9ZqpaV0h9imneex7Gx1dFsVvzyoFTw3TJOl4tt5NuLo=&xsec_source=pc_feed",
    },
    {
        "name": "探索页图集长链",
        "url": "https://www.xiaohongshu.com/explore/6907f979000000000401317f?xsec_token=ABiZT5aRD-tPnsJdVwxXfT8wOs-Tx4cOh75vG0MzoX8M8=&xsec_source=pc_feed",
    },
    {
        "name": "用户页视频长链",
        "url": "https://www.xiaohongshu.com/explore/69042124000000000703324f?xsec_token=ABfFHBtP2TYoz4iO13woOD88e3wq8qWzu2q-Sd_0j-uj8=&xsec_source=pc_user",
    },
    {
        "name": "用户页图集长链",
        "url": "https://www.xiaohongshu.com/explore/68ffb78300000000040057b8?xsec_token=ABFk4Ly_Yf-T4eLaWCmZgzykZBAgMDGkHtTm1zNw-RR5Q=&xsec_source=pc_user",
    }
]


def safe_print(text: str):
    """安全打印文本，处理编码问题"""
    try:
        print(text)
    except UnicodeEncodeError:
        try:
            encoded = text.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            print(encoded)
        except:
            print(text.encode('ascii', errors='replace').decode('ascii'))


async def test_single_link(link_info: dict, index: int, total: int):
    """测试单个链接"""
    print("=" * 80)
    print(f"【测试链接 {index}/{total}】{link_info['name']}")
    print("=" * 80)
    print()
    print(f"URL: {link_info['url']}")
    print()

    try:
        note_data = await parse_xhs_link(link_info['url'])

        note_type = note_data.get('type', '')
        content_type = "视频" if note_type == 'video' else "图集"

        safe_print("提取结果:")
        safe_print(f"内容类型：{content_type}")
        safe_print(f"\n标题：{note_data.get('title', '')}")
        safe_print(f"\n简介：")
        safe_print(note_data.get('desc', ''))
        safe_print(f"\n发布者用户名：{note_data.get('author_name', '')}(主页id:{note_data.get('author_id', '')})")
        safe_print(f"\n发布时间：{note_data.get('publish_time', '')}")

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
            "has_media": has_media
        }
    except Exception as e:
        print(f"[错误] 解析失败: {e}")
        return {
            "success": False,
            "has_media": False,
            "error": str(e)
        }


async def test_all_links():
    """测试所有链接"""
    print("=" * 80)
    print("测试")
    print("=" * 80)
    print()
    print()

    results = []
    for i, link_info in enumerate(TEST_LINKS, 1):
        result = await test_single_link(link_info, i, len(TEST_LINKS))
        result["name"] = link_info["name"]
        results.append(result)
        print()

    # 输出测试总结
    print("=" * 80)
    print("测试总结")
    print("=" * 80)
    print()

    total = len(results)
    success_count = sum(1 for r in results if r.get('success') and r.get('has_media'))
    error_count = sum(1 for r in results if not r.get('success'))

    print(f"总测试数: {total}")
    print(f"成功获取媒体直链: {success_count}/{total}")
    print(f"测试异常: {error_count}/{total}")
    print()


if __name__ == "__main__":
    asyncio.run(test_all_links())
