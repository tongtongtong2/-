
"""Day 1: 手写 k-NN 分类器 —— 用模拟数据理解 ML 核心概念"""
import numpy as np

print("=" * 55)
print("  Day 1: 手写 k-NN 分类器")
print("=" * 55)

# ===== 1. 生成模拟数据 =====
np.random.seed(42)
n = 500  # 500 个样本

# 两个因子（类比你的五因子里的两个）
# 因子A: 趋势强度（越高越好）
# 因子B: 波动率（越低越好）
trend = np.random.randn(n) * 2      # 趋势因子
vol = np.random.randn(n) * 2        # 波动率因子

# 标签: 趋势高 + 波动低 = 好股(1), 否则(0)
score = trend * 1.5 - vol * 1.0 + np.random.randn(n) * 0.5
y = (score > 0).astype(int)

X = np.column_stack([trend, vol])
print(f"数据: {n}条 | 好股: {y.sum()} | 差股: {n-y.sum()}")

# ===== 2. 切训练/测试（回测/样本外）=====
shuffle = np.random.permutation(n)
split = int(n * 0.7)
X_train, X_test = X[shuffle[:split]], X[shuffle[split:]]
y_train, y_test = y[shuffle[:split]], y[shuffle[split:]]
print(f"训练集: {len(X_train)}(70%) | 测试集: {len(X_test)}(30%)")

# ===== 3. 手写 k-NN =====
def knn_predict(X_train, y_train, X_test, k=5):
    preds = []
    for x in X_test:
        distances = np.sqrt(((X_train - x) ** 2).sum(axis=1))
        nearest = y_train[np.argsort(distances)[:k]]
        preds.append(np.bincount(nearest).argmax())
    return np.array(preds)

y_pred = knn_predict(X_train, y_train, X_test, k=5)
acc = (y_pred == y_test).mean()

# ===== 4. 评估 =====
tp = ((y_pred==1) & (y_test==1)).sum()
tn = ((y_pred==0) & (y_test==0)).sum()
fp = ((y_pred==1) & (y_test==0)).sum()
fn = ((y_pred==0) & (y_test==1)).sum()

print(f"\n准确率: {acc:.1%} ({ (y_pred==y_test).sum()}/{len(y_test)})")
print(f"\n混淆矩阵:")
print(f"              预测差    预测好")
print(f"  实际差        {tn:>3}       {fp:>3}")
print(f"  实际好        {fn:>3}       {tp:>3}")
print(f"\n  精确率(选对): {tp/(tp+fp):.1%}  |  召回率(不遗漏): {tp/(tp+fn):.1%}")

# ===== 5. 测试不同 k 值（防止过拟合） =====
print(f"\n不同 k 值的准确率:")
for k in [1, 3, 5, 7, 11, 21, 51]:
    pred = knn_predict(X_train, y_train, X_test, k=k)
    a = (pred == y_test).mean()
    bar = "|" * int(a * 50)
    print(f"  k={k:>2}  {a:.1%} {bar}")
print("  k=1 过拟合(太敏感) | k=51 欠拟合(太迟钝) | k=5~11 较好")

print("\n" + "=" * 55)
print("  关键理解:")
print("  特征(X)     = 你的五因子 → 机器学习自动找规律")
print("  标签(y)     = 好股/差股 → 止盈/止损二分类")
print("  k-NN        = '找最相似的 k 只股票，预测涨跌'")
print("  训练/测试    = 回测优化 / 样本外验证")
print("  过拟合       = k 太小，噪音当规律，实盘翻车")
print("=" * 55)
