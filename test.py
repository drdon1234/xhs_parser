"""
小红书链接解析器测试脚本
"""
import asyncio
from parser import parse_xhs_link


# ============================================================================
# 测试数据
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


# ============================================================================
# 测试函数
# ============================================================================

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

