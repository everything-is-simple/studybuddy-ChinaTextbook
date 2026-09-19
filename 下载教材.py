# -*- coding: utf-8 -*-
"""
smartedu.cn(国家中小学智慧教育平台)教材下载器
---------------------------------------------
平台: https://basic.smartedu.cn/tchMaterial (免费; 原书PDF直链无需登录)

原理(2026-09 已验证):
  1. 教材全量清单(公开 JSON):
     https://s-file-2.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/version/data_version.json
     -> urls 字段指向 part_100.json ~ part_103.json (s-file-1/s-file-2 两个CDN)
     每条资源带 tag_list: zxxxd(学段) zxxxk(学科) zxxbb(版本) zxxnj(年级) zxxcc(册)
  2. 单本详情(公开 JSON):
     https://s-file-2.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{资源id}.json
     -> ti_items 中 ti_file_flag=="source" & ti_format=="pdf" 的 ti_storages
        = 原书 PDF 直链 (r1/r2/r3-ndr-private.ykt.cbern.com.cn), 无需鉴权
  3. 下载校验: 字节数==ti_size, 文件头 %PDF, pypdf 页数 == 元数据 pagesize

安徽省小学默认目标(44本):
  语文=统编版(人教版)1-6年级  数学=人教版1-6年级
  英语=人教版PEP(三年级起点)3-6年级(安徽1-2年级不开英语)  科学=教科版1-6年级
  注意: 平台英语分 PEP(主编吴欣) 与 精通(主编苗兴伟), 安徽用 PEP, 脚本只选 PEP。

用法:
  python 下载教材.py            # 下载默认安徽小学语数英科 (已有的先校验)
  python 下载教材.py --force    # 忽略本地已有, 全部重新下载
  python 下载教材.py --check    # 只校验不下载
  python 下载教材.py --threads 8
"""
import io, json, os, sys, time, argparse, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))          # H:\studybuddy-ChinaTextbook
BASE = os.path.join(ROOT, "小学教材")                        # 教材专门目录
LOGPATH = os.path.join(ROOT, "下载日志.log")
_lock = threading.Lock()

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with _lock:
        with io.open(LOGPATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")

# ---------------------------------------------------------------- 清单
def fetch_parts():
    r = requests.get(
        "https://s-file-2.ykt.cbern.com.cn/zxx/ndrs/resources/tch_material/version/data_version.json",
        timeout=30)
    urls = r.json()["urls"].split(",")
    out = []
    for u in urls:
        out.extend(requests.get(u, timeout=180).json())
    return out

def tags_of(res):
    return {t["tag_dimension_id"]: t["tag_name"] for t in res.get("tag_list", [])}

def pick_books(res_list):
    """学段=小学, 按 版本/学科/年级/册 选书; 每(年级,册)取 online_time 最新一条"""
    sel = []
    def match(bb, xk, grades):
        out = {}
        for r in res_list:
            t = tags_of(r)
            if t.get("zxxxd") != "小学":
                continue
            if t.get("zxxbb") != bb or t.get("zxxxk") != xk:
                continue
            if t.get("zxxnj") not in grades:
                continue
            key = (t["zxxnj"], t.get("zxxcc", ""))
            cur = out.get(key)
            if cur is None or r.get("online_time", "") > cur.get("online_time", ""):
                out[key] = r
        for k, r in out.items():
            sel.append((xk, k[0], k[1], r))
    g16 = [f"{c}年级" for c in "一二三四五六"]
    match("统编版", "语文", g16)
    match("人教版", "数学", g16)
    match("教科版", "科学", g16)
    # 英语: 人教版 PEP(吴欣); 排除 精通(苗兴伟)/大同
    g36 = [f"{c}年级" for c in "三四五六"]
    out = {}
    for r in res_list:
        t = tags_of(r)
        if t.get("zxxxd") != "小学" or t.get("zxxxk") != "英语":
            continue
        bb = t.get("zxxbb", "")
        if not bb.startswith("人教版") or "苗兴伟" in bb or "大同" in bb:
            continue
        if t.get("zxxnj") not in g36:
            continue
        key = (t["zxxnj"], t.get("zxxcc", ""))
        cur = out.get(key)
        if cur is None or r.get("online_time", "") > cur.get("online_time", ""):
            out[key] = r
    for k, r in out.items():
        sel.append(("英语", k[0], k[1], r))
    return sel

def book_name(subject, res):
    t = tags_of(res)
    g, v = t["zxxnj"], t.get("zxxcc", "")
    if subject == "英语":
        return f"人教版英语PEP{g}{v}.pdf"
    if subject == "科学":
        return f"教科版科学{g}{v}.pdf"
    return f"人教版{subject}{g}{v}.pdf"

def dest_path(subject, res):
    g = tags_of(res)["zxxnj"]
    d = os.path.join(BASE, f"小学{g}", subject)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, book_name(subject, res))

# ---------------------------------------------------------------- 详情
def source_info(rid):
    """返回 (主机列表, 对应URL列表, 期望字节数, 页数, 详情URL)
    CDN 主机规则(2026-09 实测):
      r1-ndr(公共)   部分书可匿名 GET (多为上册)
      r1-ndr-private 仅 HEAD, GET 需登录 token
      r1-ndr-oversea 匿名 GET + Range 可用  <-- 首选
    """
    u = f"https://s-file-2.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{rid}.json"
    d = requests.get(u, timeout=30).json()
    for ti in d.get("ti_items", []):
        if ti.get("ti_file_flag") == "source" and ti.get("ti_format") == "pdf":
            pagesize = None
            for req in ti.get("custom_properties", {}).get("requirements", []):
                if req.get("name") == "pagesize":
                    pagesize = int(req["value"])
            urls, hosts = [], []
            for s in ti["ti_storages"]:
                host = s.split("/")[2]
                variants = []
                if "-private" in host:
                    variants = [host.replace("-private", "-oversea"), host.replace("-private", ""), host]
                else:
                    variants = [host]
                for v in variants:
                    if v not in hosts:
                        hosts.append(v)
                        urls.append(s.replace(host, v))
            return hosts, urls, int(ti["ti_size"]), pagesize, u
    raise RuntimeError(f"{rid}: 详情中没有 source/pdf 项")

# ---------------------------------------------------------------- 校验
def verify_pdf(path, size, pagesize):
    if not os.path.exists(path):
        return False, "文件不存在"
    actual = os.path.getsize(path)
    if size and actual != size:
        return False, f"大小不符 {actual}/{size}"
    with open(path, "rb") as f:
        if f.read(5) != b"%PDF-":
            return False, "非PDF"
    try:
        from pypdf import PdfReader
        p = len(PdfReader(path).pages)
        note = f"页数={p}"
        if pagesize and p != pagesize:
            note += f"(元数据{pagesize})"
        return True, note
    except Exception as e:
        return True, f"页数未知({type(e).__name__})"

# ---------------------------------------------------------------- 下载
def download_one(item, force, check_only):
    subject, g, v, res = item
    rid = res["id"]
    dp = dest_path(subject, res)
    label = os.path.basename(dp)
    if os.path.exists(dp) and not force and not check_only:
        _, _, size, pagesize, _ = source_info(rid)
        ok, info = verify_pdf(dp, size, pagesize)
        if ok:
            log(f"[校验] {label} -> OK {info}")
            return True, label, subject, g
        log(f"[校验] {label} -> 与线上新版不符({info}), 重新下载覆盖")
    if check_only and not os.path.exists(dp):
        log(f"[校验] {label} 缺失(跳过下载, --check 模式)")
        return False, label + " 缺失", subject, g
    hosts, urls, size, pagesize, _ = source_info(rid)
    tmp = dp + ".part"
    log(f"[下载] {label} ({size/1e6:.1f}MB, {pagesize}页)")
    for i, host in enumerate(hosts):
        u = urls[i]
        try:
            # 断点续传
            pos = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            if os.path.exists(tmp) and pos >= size:
                os.remove(tmp)
                pos = 0
            headers = {}
            if pos:
                headers["Range"] = f"bytes={pos}-"
            with requests.get(u, stream=True, timeout=120, headers=headers) as r:
                if pos and r.status_code == 206:
                    mode = "ab"
                else:
                    mode = "wb"
                    pos = 0
                r.raise_for_status()
                with open(tmp, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            ok, info = verify_pdf(tmp, size, pagesize)
            if ok:
                os.replace(tmp, dp)
                log(f"[完成] {label} {size/1e6:.1f}MB {info}")
                return True, label, subject, g
            log(f"[重试] {host}: {info}")
        except Exception as e:
            log(f"[错误] {host}: {type(e).__name__} {e}")
            if os.path.exists(tmp):
                log(f"       .part 保留 {os.path.getsize(tmp)} 字节, 可重跑续传")
    return False, label, subject, g

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验不下载")
    ap.add_argument("--force", action="store_true", help="强制重新下载")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true", help="只打印选书清单, 不下载")
    args = ap.parse_args()

    log("=" * 64)
    log("拉取平台教材清单 ...")
    res_list = fetch_parts()
    log(f"清单共 {len(res_list)} 条资源")
    books = pick_books(res_list)
    names = ", ".join(book_name(s, r) for s, g, v, r in sorted(books, key=lambda x: (x[2], x[3]["id"])))
    log(f"选定 {len(books)} 本: {names}")
    order = {"语文": 0, "数学": 1, "英语": 2, "科学": 3}
    gnum = {"一年级": 1, "二年级": 2, "三年级": 3, "四年级": 4, "五年级": 5, "六年级": 6}
    if args.dry_run:
        for s, g, v, r in sorted(books, key=lambda x: (order[x[0]], gnum.get(x[1], 9), x[2])):
            log(f"  {s} | {g}{v} | id={r['id']} | online={r.get('online_time','')[:10]} | {r.get('title','')}")
        return

    results = []
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futs = {ex.submit(download_one, b, args.force, args.check): b for b in books}
        for fut in as_completed(futs):
            results.append(fut.result())

    n_ok = sum(1 for ok, *_ in results if ok)
    log(f"===== 结果: {n_ok}/{len(results)} 成功 =====")
    for ok, label, subject, g in sorted(results, key=lambda x: (order.get(x[2], 9), gnum.get(x[3], 9), x[1])):
        log(f"{'✓' if ok else '✗'} {label}")

if __name__ == "__main__":
    main()
