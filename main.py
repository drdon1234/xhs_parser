import aiohttp
import json
import re
from datetime import datetime
from urllib.parse import unquote


# Android User-Agent
ANDROID_UA = "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36 Edg/142.0.0.0"


async def get_headers():
    """获取请求头"""
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
                # 处理URL编码
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


def extract_initial_state(html: str) -> dict:
    """从HTML中提取window.__INITIAL_STATE__的JSON数据"""
    # 使用正则表达式匹配window.__INITIAL_STATE__ = {...}
    # 匹配模式：window.__INITIAL_STATE__ = 后面跟着一个完整的JSON对象
    pattern = r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>'
    match = re.search(pattern, html, re.DOTALL)
    
    if match:
        json_str = match.group(1)
        # 清理JavaScript特有的值
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
    
    # 找到等号后的第一个左大括号
    json_start = html.find('{', start_idx)
    if json_start == -1:
        raise Exception("无法找到JSON开始位置")
    
    # 找到script标签的结束位置，作为搜索的边界
    script_end = html.find('</script>', start_idx)
    if script_end == -1:
        script_end = len(html)
    
    # 使用括号匹配找到完整的JSON对象，考虑字符串中的转义
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
    
    # 清理JavaScript特有的值，使其符合JSON规范
    # 将 undefined 替换为 null
    json_str = re.sub(r'\bundefined\b', 'null', json_str)
    # 处理可能存在的单引号字符串（虽然JSON标准不支持，但有些网站会使用）
    # 这里我们只处理明显的 undefined，其他保持原样
    
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # 如果解析失败，尝试打印错误位置附近的内容用于调试
        error_pos = getattr(e, 'pos', 0)
        start_debug = max(0, error_pos - 200)
        end_debug = min(len(json_str), error_pos + 200)
        error_msg = f"JSON解析失败: {e}\n错误位置: {error_pos}\n附近内容: {json_str[start_debug:end_debug]}"
        raise Exception(error_msg)


def parse_note_data(data: dict) -> dict:
    """从JSON数据中提取所需信息"""
    try:
        note_data = data["noteData"]["data"]["noteData"]
        user_data = note_data["user"]
        
        # 提取笔记类型
        note_type = note_data.get("type", "normal")
        
        # 提取标题
        title = note_data.get("title", "")
        
        # 提取简介（已包含tag）
        desc = note_data.get("desc", "")
        
        # 提取发布者信息
        author_name = user_data.get("nickName", "")
        author_id = user_data.get("userId", "")
        
        # 提取时间戳并转换为Y-M-D格式
        timestamp = note_data.get("time", 0)
        if timestamp:
            # 时间戳是毫秒，需要除以1000
            dt = datetime.fromtimestamp(timestamp / 1000)
            publish_time = dt.strftime("%Y-%m-%d")
        else:
            publish_time = ""
        
        # 根据类型提取不同的媒体URL
        video_url = ""
        image_urls = []
        
        if note_type == "video":
            # 提取视频URL
            # 视频URL可能在多个位置，需要尝试不同的字段
            video_info = note_data.get("video", {})
            if video_info:
                # 尝试从video对象中获取URL
                video_url = video_info.get("media", {}).get("stream", {}).get("h264", [{}])[0].get("masterUrl", "")
                if not video_url:
                    video_url = video_info.get("media", {}).get("stream", {}).get("h264", [{}])[0].get("backupUrl", "")
                if not video_url:
                    video_url = video_info.get("media", {}).get("stream", {}).get("h264", [{}])[0].get("url", "")
            
            # 如果上面的方法没找到，尝试其他可能的字段
            if not video_url:
                stream_info = note_data.get("stream", {})
                if stream_info:
                    video_url = stream_info.get("h264", [{}])[0].get("masterUrl", "")
                    if not video_url:
                        video_url = stream_info.get("h264", [{}])[0].get("backupUrl", "")
                    if not video_url:
                        video_url = stream_info.get("h264", [{}])[0].get("url", "")
            
            # 如果还是没找到，尝试直接查找包含.mp4的URL
            if not video_url:
                # 搜索整个note_data中可能包含视频URL的字段
                def find_video_url(obj, depth=0):
                    if depth > 5:  # 限制递归深度
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
            
            # 如果找到视频URL，确保使用https协议
            if video_url and video_url.startswith("http://"):
                video_url = video_url.replace("http://", "https://", 1)
        else:
            # 提取图集直链
            image_list = note_data.get("imageList", [])
            image_urls = [img.get("url", "") for img in image_list if img.get("url")]
        
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
    except KeyError as e:
        raise Exception(f"数据提取失败，缺少字段: {e}")


def format_output(data: dict):
    """格式化输出到控制台"""
    # 显示内容类型
    content_type = "视频" if data.get('type') == 'video' else "图集"
    print(f"内容类型：{content_type}")
    print(f"\n标题：{data['title']}")
    print(f"\n简介：")
    print(data['desc'])
    print(f"\n发布者用户名：{data['author_name']}(主页id:{data['author_id']})")
    print(f"\n发布时间：{data['publish_time']}")
    
    # 根据类型输出不同的媒体链接
    if data.get('type') == 'video':
        print(f"\n视频直链：")
        if data.get('video_url'):
            print(data['video_url'])
        else:
            print("未找到视频链接")
    else:
        print(f"\n图集直链：")
        for url in data['image_urls']:
            print(url)


def normalize_xhs_url(url: str) -> str:
    """规范化小红书URL，支持短链接和长链接"""
    # 如果是短链接（xhslink.com），需要重定向
    if "xhslink.com" in url:
        return None  # 返回None表示需要重定向
    
    # 如果是长链接，直接使用
    if "www.xiaohongshu.com" in url:
        # 确保URL是完整的（包含协议）
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        return url
    
    # 其他情况，尝试作为完整URL使用
    if url.startswith("http://") or url.startswith("https://"):
        return url
    
    # 默认添加https协议
    return "https://" + url


async def parse_xhs_link(input_url: str):
    """主函数：解析小红书链接"""
    try:
        # 1. 规范化URL，判断是否需要重定向
        normalized_url = normalize_xhs_url(input_url)
        
        if normalized_url is None:
            # 需要重定向（短链接）
            full_url = await get_redirect_url(input_url)
            print(f"重定向URL: {full_url}\n")
        else:
            # 直接使用长链接
            full_url = normalized_url
            print(f"使用URL: {full_url}\n")
        
        # 2. 获取页面内容
        html = await fetch_page(full_url)
        
        # 3. 提取JSON数据
        initial_state = extract_initial_state(html)
        
        # 4. 解析数据
        note_data = parse_note_data(initial_state)
        
        # 5. 格式化输出
        format_output(note_data)
        
    except Exception as e:
        print(f"错误: {e}")


async def main():
    """主入口函数"""
    # 示例：解析提供的短链接
    # 支持三种格式：
    # 1. 短链接：http://xhslink.com/o/xxxxx
    # 2. 长链接（explore）：https://www.xiaohongshu.com/explore/xxxxx
    # 3. 长链接（discovery/item）：https://www.xiaohongshu.com/discovery/item/xxxxx
    short_url = "http://xhslink.com/o/554d8r4UZF2"
    await parse_xhs_link(short_url)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

