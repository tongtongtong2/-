import sys, os
sys.path = [p for p in sys.path if 'Python314' not in p and 'Roaming' not in p and 'python314' not in p.lower()]
venv_root = r'F:\datax\stock-recommendation-platform\.venv'
sys.path.insert(0, venv_root + r'\DLLs')
sys.path.insert(0, venv_root + r'\Lib')
sys.path.insert(0, venv_root + r'\Lib\site-packages')
sys.path.insert(0, r'F:\datax\stock-recommendation-platform')
os.chdir(r'F:\datax\stock-recommendation-platform')
for k in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy","all_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"

import requests
import json

# 腾讯行情接口 - 拉实时价
codes = ["sh601985", "sz002747"]
url = f"http://qt.gtimg.cn/q={','.join(codes)}"
resp = requests.get(url, timeout=10)
resp.encoding = "gbk"
print("=== 腾讯实时行情 ===")
print(resp.text[:2000])

# 也拉一下沪深300判断市场环境
url2 = "http://qt.gtimg.cn/q=sh000300"
resp2 = requests.get(url2, timeout=10)
resp2.encoding = "gbk"
print("\n=== 沪深300 ===")
print(resp2.text[:500])
