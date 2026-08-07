"""IP 地理定位服务 — 基于 ip2region xdb 离线数据库

首次启动自动从 GitHub 下载 ip2region.xdb（约 11MB），之后使用本地缓存。
内网 IP / 解析失败均返回空字符串，不阻塞登录流程。

使用方式：
    from ip_service import ip_to_location
    loc = await ip_to_location("114.114.114.114")
    # → {"country": "中国", "province": "江苏省", "city": "南京市"}
"""

import logging
import os
import socket
import struct
import time
from pathlib import Path

import httpx

logger = logging.getLogger("ip_service")

# ---- 配置 ----
_XDB_PATH = Path(
    os.environ.get("IP2REGION_DB",
                   os.path.join(os.path.dirname(os.path.abspath(__file__)), "ip2region.xdb"))
)
_XDB_DOWNLOAD_URL = (
    "https://raw.githubusercontent.com/lionsoul2014/ip2region/master/data/ip2region.xdb"
)

# 内网/保留地址段（int 形式）
_PRIVATE_RANGES = [
    (0x0A000000, 0x0AFFFFFF),   # 10.0.0.0/8
    (0xAC100000, 0xAC1FFFFF),   # 172.16.0.0/12
    (0xC0A80000, 0xC0A8FFFF),   # 192.168.0.0/16
    (0x7F000000, 0x7FFFFFFF),   # 127.0.0.0/8
    (0xA9FE0000, 0xA9FEFFFF),   # 169.254.0.0/16
]

# ---- xdb 搜索器 ----
_HEADER_SIZE = 256
_SEGMENT_INDEX_SIZE = 14   # start_ip(4) + end_ip(4) + data_ptr(4) + data_len(2)


class _Ip2Region:
    """ip2region xdb 搜索器 —— 线程安全"""

    def __init__(self, db_path: str):
        self._f = open(db_path, "rb")
        self._f.seek(0)
        header = self._f.read(_HEADER_SIZE)
        # Header layout (256 bytes):
        #   0-1:   version (uint16)
        #   2-3:   reserved
        #   4-7:   first index ptr (uint32 LE)
        #   8-11:  index start ptr (uint32 LE)  ← 区索引起始
        #   12-15: index end ptr (uint32 LE)    ← 区索引结束
        #   16-19: total file size (uint32 LE)
        self._index_start = struct.unpack_from("<I", header, 8)[0]
        self._index_end = struct.unpack_from("<I", header, 12)[0]
        self._total_blocks = (self._index_end - self._index_start) // _SEGMENT_INDEX_SIZE

    @staticmethod
    def _ip2int(ip: str) -> int:
        try:
            return struct.unpack("!I", socket.inet_aton(ip.strip()))[0]
        except OSError:
            return 0

    def search(self, ip: str) -> str:
        """返回原始 region 字符串: "中国|0|江苏省|南京市|0" 或空"""
        ip_int = self._ip2int(ip)
        if ip_int == 0:
            return ""

        low, high = 0, self._total_blocks - 1
        data_ptr, data_len = 0, 0

        while low <= high:
            mid = (low + high) // 2
            offset = self._index_start + mid * _SEGMENT_INDEX_SIZE
            self._f.seek(offset)
            buf = self._f.read(_SEGMENT_INDEX_SIZE)
            seg_start = struct.unpack_from("<I", buf, 0)[0]
            seg_end = struct.unpack_from("<I", buf, 4)[0]
            seg_ptr = struct.unpack_from("<I", buf, 8)[0]
            seg_len = struct.unpack_from("<H", buf, 12)[0]

            if ip_int < seg_start:
                high = mid - 1
            elif ip_int > seg_end:
                low = mid + 1
            else:
                data_ptr, data_len = seg_ptr, seg_len
                break

        if data_len == 0:
            return ""

        self._f.seek(data_ptr)
        return self._f.read(data_len).decode("utf-8", errors="ignore")

    def close(self):
        self._f.close()


# ---- 全局搜索器 ----
_searcher: _Ip2Region | None = None


def _is_private_ip(ip: str) -> bool:
    try:
        ip_int = struct.unpack("!I", socket.inet_aton(ip.strip()))[0]
    except OSError:
        return True
    return any(lo <= ip_int <= hi for lo, hi in _PRIVATE_RANGES)


def _verify_xdb(path: Path) -> bool:
    try:
        if not path.exists():
            return False
        if path.stat().st_size < _HEADER_SIZE:
            return False
        with open(path, "rb") as f:
            header = f.read(_HEADER_SIZE)
        recorded = struct.unpack_from("<I", header, 16)[0]
        return recorded == path.stat().st_size
    except Exception:
        return False


async def _download_xdb():
    """下载 ip2region.xdb（~11 MB）"""
    global _searcher

    if _verify_xdb(_XDB_PATH):
        logger.info(f"ip2region.xdb ready ({_XDB_PATH.stat().st_size / 1024 / 1024:.1f} MB)")
        _searcher = _Ip2Region(str(_XDB_PATH))
        return

    logger.info("Downloading ip2region.xdb (~11 MB) from GitHub...")
    _XDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(_XDB_DOWNLOAD_URL, follow_redirects=True)
            response.raise_for_status()
            _XDB_PATH.write_bytes(response.content)
    except Exception as e:
        logger.warning(f"Failed to download ip2region.xdb: {e}")
        _XDB_PATH.unlink(missing_ok=True)
        return

    elapsed = time.time() - start
    if not _verify_xdb(_XDB_PATH):
        _XDB_PATH.unlink(missing_ok=True)
        logger.warning("Downloaded ip2region.xdb failed verification")
        return

    logger.info(f"ip2region.xdb downloaded in {elapsed:.1f}s "
                f"({_XDB_PATH.stat().st_size / 1024 / 1024:.1f} MB)")
    _searcher = _Ip2Region(str(_XDB_PATH))


async def ip_to_location(ip: str) -> dict[str, str]:
    """将 IPv4 地址解析为地理位置

    返回 {"country": "中国", "province": "江苏省", "city": "南京市"}
    内网 IP / 解析失败均返回空字符串
    """
    global _searcher

    empty = {"country": "", "province": "", "city": ""}
    ip = (ip or "").strip()
    if not ip:
        return empty
    if ":" in ip:  # IPv6 不支持
        return empty
    if _is_private_ip(ip):
        return {"country": "内网", "province": "", "city": ""}

    if _searcher is None:
        try:
            await _download_xdb()
        except Exception as e:
            logger.warning(f"ip2region init failed: {e}")
            return empty

    if _searcher is None:
        return empty

    try:
        region = _searcher.search(ip)
    except Exception as e:
        logger.warning(f"ip2region search failed for {ip}: {e}")
        return empty

    if not region:
        return empty

    # 解析 "国家|区域|省份|城市|ISP"
    parts = region.split("|")
    result = {"country": "", "province": "", "city": ""}
    if len(parts) >= 1 and parts[0] and parts[0] != "0":
        result["country"] = parts[0].strip()
    if len(parts) >= 3 and parts[2] and parts[2] != "0":
        result["province"] = parts[2].strip()
    if len(parts) >= 4 and parts[3] and parts[3] != "0":
        result["city"] = parts[3].strip()
    return result
