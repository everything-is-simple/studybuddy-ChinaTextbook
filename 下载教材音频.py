# -*- coding: utf-8 -*-
"""
教材配套音频下载器（英语课文朗读/歌曲/听力 MP3）
-------------------------------------------------
来源: 国家中小学智慧教育平台, 教材详情页"相关音频"
  1. 音频清单(公开): https://s-file-2.ykt.cbern.com.cn/zxx/ndrs/resources/{教材id}/relation_audios.json
  2. 音频为现成 mp3 文件, 存于私有 CDN, 需 ?accessToken=<登录token> 下载
  3. CDN 有请求频率限制: 默认单线程 + 1秒间隔, 失败自动退避重试

Token 获取(有效期约 7 天):
  浏览器登录 basic.smartedu.cn 后, F12 控制台执行:
    localStorage.getItem('ND_UC_AUTH-e5649925-441d-4a53-b525-51a2f1c4e0a8&ncet-xedu&token')
  把 access_token 的值存入本目录 智慧教育token.txt (一行)

用法:
  python 下载教材音频.py            # 下载全部(默认单线程, 稳)
  python 下载教材音频.py --check    # 只校验缺失
  python 下载教材音频.py --threads 2 --delay 0.5
"""
import io, os, re, sys, time, argparse, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import warnings
warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(ROOT, "小学教材")
LOGPATH = os.path.join(ROOT, "下载日志.log")
TOKEN_FILE = os.path.join(ROOT, "智慧教育token.txt")
_lock = threading.Lock()
_n_done = 0

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with _lock:
        with io.open(LOGPATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0 Safari/537.36"})

TEXTBOOKS = [
 ("三年级", "人教版英语PEP三年级上册", "dd6173ba-579a-356e-900c-cb53e152229c"),
 ("三年级", "人教版英语PEP三年级下册", "9eb54ff2-1c7b-4441-abff-c44b714a2302"),
 ("四年级", "人教版英语PEP四年级上册", "be6e00c8-0068-8453-927f-646f6f753a5a"),
 ("四年级", "人教版英语PEP四年级下册", "18b54350-f833-4b5c-a1b9-ebbf02cf4545"),
 ("五年级", "人教版英语PEP五年级上册", "9f1cda77-2dc7-442b-82f1-97243f7ec39d"),
 ("六年级", "人教版英语PEP六年级上册", "9e2878bf-964d-47fb-85ba-937cf61159a5"),
]
REL = "https://s-file-2.ykt.cbern.com.cn/zxx/ndrs/resources/{}/relation_audios.json"

def safe_name(s):
    return re.sub(r'[\\/:*?"<>|\r\n]+', "_", s).strip()

def collect():
    items = []
    for grade, book, tid in TEXTBOOKS:
        d = SESSION.get(REL.format(tid), timeout=30).json()
        for i, a in enumerate(d, 1):
            title = a.get("global_title", {}).get("zh-CN") or a.get("title") or f"audio{i}"
            urls = []
            for ti in a.get("ti_items", []):
                if str(ti.get("ti_storage", "")).endswith(".mp3"):
                    urls = ti.get("ti_storages", [])
                    break
            if urls:
                items.append((grade, book, i, title, urls))
    return items

def download_one(item, token, delay):
    global _n_done
    grade, book, i, title, urls = item
    time.sleep(delay)
    d = os.path.join(BASE, f"小学{grade}", "英语", f"{book}_配套音频")
    os.makedirs(d, exist_ok=True)
    dp = os.path.join(d, f"{i:03d}_{safe_name(title)}.mp3")
    if os.path.exists(dp) and os.path.getsize(dp) > 10000:
        _n_done += 1
        return True, dp
    # 退避重试: 5 次, 每轮轮换主机
    for attempt in range(5):
        for j, raw in enumerate(urls):
            u = raw + ("&" if "?" in raw else "?") + "accessToken=" + token
            try:
                tmp = dp + ".part"
                with SESSION.get(u, stream=True, timeout=(15, 180)) as r:
                    if r.status_code in (403, 429):
                        raise RuntimeError(f"HTTP {r.status_code} 限流")
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 16):
                            f.write(chunk)
                if os.path.getsize(tmp) < 10000:
                    raise RuntimeError(f"文件过小 {os.path.getsize(tmp)}")
                os.replace(tmp, dp)
                _n_done += 1
                if _n_done % 25 == 0:
                    log(f"进度 {_n_done}")
                return True, dp
            except Exception as e:
                err = f"{type(e).__name__} {str(e)[:50]}"
        # 所有主机都失败, 退避
        log(f"[退避{attempt+1}] {i:03d}_{safe_name(title)[:40]} ({err})")
        time.sleep(5 * (attempt + 1) * (attempt + 1))
    return False, dp

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()

    if not os.path.exists(TOKEN_FILE):
        log(f"缺少 {TOKEN_FILE}: 请按脚本头部说明提取登录 token")
        sys.exit(1)
    token = io.open(TOKEN_FILE, encoding="utf-8").read().strip()
    log("=" * 60)
    log("枚举教材音频 ...")
    items = collect()
    log(f"共 {len(items)} 个音频 (线程={args.threads}, 间隔={args.delay}s)")
    if args.check:
        miss = 0
        for grade, book, i, title, urls in items:
            dp = os.path.join(BASE, f"小学{grade}", "英语", f"{book}_配套音频", f"{i:03d}_{safe_name(title)}.mp3")
            if not (os.path.exists(dp) and os.path.getsize(dp) > 10000):
                miss += 1
                log(f"缺失: {dp}")
        log(f"===== 缺失 {miss}/{len(items)} =====")
        return
    results = []
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futs = [ex.submit(download_one, it, token, (idx % args.threads) * 0.5 + args.delay) for idx, it in enumerate(items)]
        for fut in as_completed(futs):
            results.append(fut.result())
    n_ok = sum(1 for ok, _ in results if ok)
    log(f"===== 结果: {n_ok}/{len(results)} 成功 =====")

if __name__ == "__main__":
    main()
