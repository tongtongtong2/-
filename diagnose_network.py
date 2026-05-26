"""网络诊断脚本：隔离 akshare 调用，排除 Flask/多线程/代码层干扰。"""
import os
import sys
import time
import urllib.request

# ---------- 1. 检查代理 ----------
print("=" * 60)
print("1. 代理环境变量")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy", "NO_PROXY", "no_proxy"):
    print(f"   {k} = {os.environ.get(k, '<未设置>')}")

print("\n   系统代理 (urllib.request.getproxies):")
for proto, proxy in sorted(urllib.request.getproxies().items()):
    print(f"   {proto} = {proxy}")

# ---------- 2. 直连测试 ----------
print("\n" + "=" * 60)
print("2. 直连东方财富 API (requests, 无 akshare)")
import requests

url = "https://82.push2.eastmoney.com/api/qt/clist/get"
params = {
    "pn": "1",
    "pz": "20",
    "po": "1",
    "np": "1",
    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    "fltt": "2",
    "invt": "2",
    "fid": "f12",
    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
    "fields": "f2,f12,f14",
}

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

try:
    start = time.time()
    r = requests.get(url, params=params, headers=headers, timeout=30)
    elapsed = time.time() - start
    print(f"   状态码: {r.status_code}")
    print(f"   耗时: {elapsed:.2f}s")
    print(f"   响应长度: {len(r.text)} bytes")
    data = r.json()
    total = data.get("data", {}).get("total", "N/A")
    print(f"   股票总数: {total}")
    print("   >>> 直连成功 <<<")
except Exception as exc:
    print(f"   >>> 直连失败: {exc} <<<")

# ---------- 3. akshare 调用 ----------
print("\n" + "=" * 60)
print("3. 调用 akshare.stock_zh_a_spot_em() (pz=20 仅取少量数据测试)")

# 临时 monkey-patch 减少数据量加速测试
import akshare.utils.func as ak_func
_original_fetch = ak_func.fetch_paginated_data

def _test_fetch(url, base_params, timeout=15):
    params = base_params.copy()
    params["pz"] = "20"  # 只取 20 条，减少数据量
    from akshare.utils.request import request_with_retry
    r = request_with_retry(url, params=params, timeout=30)
    data_json = r.json()
    import pandas as pd
    temp_list = [pd.DataFrame(data_json["data"]["diff"])]
    total_page = min(2, -( -data_json["data"]["total"] // 20))  # 只取 2 页
    for page in range(2, total_page + 1):
        params.update({"pn": str(page)})
        time.sleep(0.8)
        r = request_with_retry(url, params=params, timeout=30)
        temp_list.append(pd.DataFrame(r.json()["data"]["diff"]))
    return pd.concat(temp_list, ignore_index=True)

ak_func.fetch_paginated_data = _test_fetch

try:
    import akshare as ak
    start = time.time()
    df = ak.stock_zh_a_spot_em()
    elapsed = time.time() - start
    print(f"   耗时: {elapsed:.2f}s")
    print(f"   行数: {len(df)}")
    print("   >>> akshare 调用成功 <<<")
except Exception as exc:
    print(f"   >>> akshare 调用失败: {exc} <<<")

ak_func.fetch_paginated_data = _original_fetch
