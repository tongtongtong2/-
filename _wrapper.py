import sys, os
sys.path = [p for p in sys.path if 'Python314' not in p and 'Roaming' not in p and 'python314' not in p.lower()]
venv_root = r'F:\datax\stock-recommendation-platform\.venv'
sys.path.insert(0, venv_root + r'\DLLs')
sys.path.insert(0, venv_root + r'\Lib')
sys.path.insert(0, venv_root + r'\Lib\site-packages')
sys.path.insert(0, r'F:\datax\stock-recommendation-platform')
os.chdir(r'F:\datax\stock-recommendation-platform')
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"

from config import Config
import pymysql

conn = pymysql.connect(host=Config.MYSQL_HOST, port=Config.MYSQL_PORT, user=Config.MYSQL_USER, password=Config.MYSQL_PASSWORD, database=Config.MYSQL_DATABASE, charset='utf8mb4')
cur = conn.cursor()

cur.execute("SELECT stock_code, stock_name, recommend_date, recommend_price, price_status, status, close_price, final_return, source, shares FROM stock_recommendations WHERE recommend_date >= '2026-05-24' ORDER BY recommend_date DESC, stock_code")
rows = cur.fetchall()
print("=== RECENT RECOMMENDATIONS (2026-05-24+) ===")
for r in rows:
    print(f"  {r[0]} {r[1]:8s} | {r[2]} | rec:{r[3]} | close:{r[6]} | ret:{r[7]} | {r[4]}/{r[5]} | {r[8]}/{r[9]}股")

cur.execute("SELECT stock_code, stock_name, recommend_date, recommend_price, price_status, status, close_price, final_return, source, shares FROM stock_recommendations WHERE recommend_date = '2026-05-26' ORDER BY stock_code")
rows = cur.fetchall()
print("\n=== TODAY (2026-05-26) ===")
if rows:
    for r in rows:
        print(f"  {r[0]} {r[1]:8s} | rec:{r[3]} | close:{r[6]} | ret:{r[7]} | {r[4]}/{r[5]} | {r[8]}/{r[9]}股")
else:
    print("  (no records)")

cur.close()
conn.close()
