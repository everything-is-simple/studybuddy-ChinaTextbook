# -*- coding: utf-8 -*-
"""
基础性作业(官方课后作业册)下载器
---------------------------------
来源: 国家中小学智慧教育平台 basic.smartedu.cn
  课程教学 -> 教师备课授课 -> 基础性作业 (编者: 上海市教委, 免费匿名下载)

原理(2026-09 已验证):
  1. 资源详情(公开 JSON):
     https://s-file-1.ykt.cbern.com.cn/zxx/ndrs/special_edu/resources/details/{资源id}.json
  2. ti_items 中 ti_file_flag=="source" & ti_format=="pdf" 的 ti_storages
     = 作业册 PDF 直链 (r1/r2/r3-ndr.ykt.cbern.com.cn, 匿名可下)
  3. 校验: 字节数==ti_size, %PDF 头, pypdf 页数

用法:
  python 下载基础性作业.py            # 下载小学语数英 3-6 年级共 24 册
  python 下载基础性作业.py --check    # 只校验
  python 下载基础性作业.py --force    # 强制重下
"""
import io, os, sys, time, argparse, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(ROOT, "基础性作业")
LOGPATH = os.path.join(ROOT, "下载日志.log")
_lock = threading.Lock()

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with _lock:
        with io.open(LOGPATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")

# 资源清单: (科目, 册名, 资源id) —— 小学语数英 3-6 年级上下册, 2026-09 枚举自平台
BOOKS = [
 ("语文", "语文作业三年级上册", "62044dd6-2ee9-454e-9db5-66693a302b70"),
 ("语文", "语文作业三年级下册", "81842d6c-ebe7-470c-b377-df4ea0aef43b"),
 ("语文", "语文作业四年级上册", "89db654d-ac61-4d8e-920e-fa9c7ac76e3b"),
 ("语文", "语文作业四年级下册", "83167092-c615-4f6b-8c0a-84d36f8eade7"),
 ("语文", "语文作业五年级上册", "efe4a34c-7012-4291-8e86-00ed9a8f6c6b"),
 ("语文", "语文作业五年级下册", "cd6f442d-fedb-4c3f-9c70-14633ee4010c"),
 ("语文", "语文作业六年级上册", "b3d72b08-adfe-4fd0-b452-78cf3c9d6bb5"),
 ("语文", "语文作业六年级下册", "78859747-6763-40d2-a48b-bab4c5e65af5"),
 ("数学", "数学作业三年级上册", "10c6797d-5400-40c0-a714-587ea96e7e14"),
 ("数学", "数学作业三年级下册", "c27e5413-55fa-405c-8839-ee265563478a"),
 ("数学", "数学作业四年级上册", "95bc6dce-62b6-4891-a524-1127ce77e771"),
 ("数学", "数学作业四年级下册", "f176d569-ce0f-4b32-b0c1-4fb9c630008a"),
 ("数学", "数学作业五年级上册", "5169bb4c-4c2c-4ed5-802d-5c6a6c3e8bc0"),
 ("数学", "数学作业五年级下册", "788672f5-0122-4e41-aee7-13c0be866e55"),
 ("数学", "数学作业六年级上册", "309143ce-0db3-4a0a-83c6-e8d5455abccd"),
 ("数学", "数学作业六年级下册", "abf8391f-afe5-40b1-8dac-331dd59b0757"),
 ("英语", "英语作业三年级上册", "5444e71d-b3a7-4424-ad1d-ede02b70fc06"),
 ("英语", "英语作业三年级下册", "f8b3d602-0dfd-4359-9c20-6022294fd2e3"),
 ("英语", "英语作业四年级上册", "7a0595e5-9e7c-4680-a52d-bcebaa8adcc6"),
 ("英语", "英语作业四年级下册", "a5e5dd4c-9ab5-4f1f-8c43-dc57602f0d2d"),
 ("英语", "英语作业五年级上册", "d8bfcfa8-5646-4fe9-b77d-5d03bbbcb2c8"),
 ("英语", "英语作业五年级下册", "e76e6cdb-e101-4342-b2ee-ceb4767e8958"),
 ("英语", "英语作业六年级上册", "ba855e27-ef9e-41a2-9a44-7089d806cafd"),
 ("英语", "英语作业六年级下册", "1bc88e20-b54f-44bc-9f48-6cb6e77bd47a"),
]

DETAIL = "https://s-file-1.ykt.cbern.com.cn/zxx/ndrs/special_edu/resources/details/{}.json"

def source_info(rid):
    d = requests.get(DETAIL.format(rid), timeout=30).json()
    for ti in d.get("ti_items", []):
        if ti.get("ti_file_flag") == "source" and ti.get("ti_format") == "pdf":
            return ti["ti_storages"], int(ti["ti_size"])
    raise RuntimeError(f"{rid}: 无 source PDF")

def verify_pdf(path, size):
    if not os.path.exists(path):
        return False, "不存在"
    if size and os.path.getsize(path) != size:
        return False, f"大小不符 {os.path.getsize(path)}/{size}"
    with open(path, "rb") as f:
        if f.read(5) != b"%PDF-":
            return False, "非PDF"
    try:
        from pypdf import PdfReader
        return True, f"页数={len(PdfReader(path).pages)}"
    except Exception as e:
        return True, f"页数未知({type(e).__name__})"

def download_one(item, force, check_only):
    subj, name, rid = item
    d = os.path.join(BASE, subj)
    os.makedirs(d, exist_ok=True)
    dp = os.path.join(d, name + ".pdf")
    try:
        urls, size = source_info(rid)
    except Exception as e:
        log(f"[错误] {name}: {e}")
        return False, name
    if os.path.exists(dp) and not force:
        ok, info = verify_pdf(dp, size)
        if ok:
            log(f"[校验] {name}.pdf -> OK {info}")
            return True, name
        log(f"[校验] {name}.pdf -> {info}, 重新下载")
    if check_only and not os.path.exists(dp):
        log(f"[校验] {name}.pdf 缺失")
        return False, name
    tmp = dp + ".part"
    for u in dict.fromkeys(urls):
        host = u.split("/")[2]
        try:
            log(f"[下载] {name}.pdf ({size/1e6:.1f}MB) <- {host}")
            with requests.get(u, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            ok, info = verify_pdf(tmp, size)
            if ok:
                os.replace(tmp, dp)
                log(f"[完成] {name}.pdf {size/1e6:.1f}MB {info}")
                return True, name
            log(f"[重试] {info}")
        except Exception as e:
            log(f"[错误] {host}: {type(e).__name__} {e}")
    if os.path.exists(tmp):
        log(f"[失败] {name}.pdf .part 保留")
    return False, name

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()
    log("=" * 60)
    log(f"基础性作业: 共 {len(BOOKS)} 册待处理")
    results = []
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futs = [ex.submit(download_one, b, args.force, args.check) for b in BOOKS]
        for fut in as_completed(futs):
            results.append(fut.result())
    n_ok = sum(1 for ok, _ in results if ok)
    log(f"===== 结果: {n_ok}/{len(results)} 成功 =====")
    for ok, name in sorted(results):
        log(f"{'✓' if ok else '✗'} {name}")

if __name__ == "__main__":
    main()
