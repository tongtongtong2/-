
"""Day 2: 线性回归 + 决策树 —— 预测涨跌幅 + 规则选股"""
import numpy as np
from pathlib import Path
import matplotlib
matplotlib.use("Agg")  # 无 GUI 后端，保存图片
import matplotlib.pyplot as plt

# 中文字体设置
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

print("=" * 60)
print("  Day 2: 线性回归 + 决策树")
print("=" * 60)

np.random.seed(42)

# ============================================================
#  PART 1: 线性回归 —— 预测「涨多少」
# ============================================================
print("\n" + "─" * 50)
print("  PART 1: 线性回归 Linear Regression")
print("─" * 50)
print("\n  概念: y = w₁x₁ + w₂x₂ + ... + b")
print("  量化类比: 用多个因子（趋势、波动率、交易量）预测收益率\n")

# ----- 生成模拟数据 -----
n = 200
# 特征: 趋势强度、波动率、交易量变化
trend   = np.random.randn(n) * 2
vol     = np.random.randn(n) * 2
volume  = np.random.randn(n) * 2

# 真实关系: return = 0.8*trend - 0.5*vol + 0.3*volume + 噪声
true_w = np.array([0.8, -0.5, 0.3])
true_b = 0.1
y = X = np.column_stack([trend, vol, volume])
y = X @ true_w + true_b + np.random.randn(n) * 0.5  # 加噪声

print(f"  真实权重: trend={true_w[0]}, vol={true_w[1]}, volume={true_w[2]}, bias={true_b}")
print(f"  数据: {n}条, y范围 [{y.min():.2f}, {y.max():.2f}] → 这就是'收益率预测值'")

# ----- 1A: 手写梯度下降 -----
print("\n--- 1A: 手写梯度下降 ---")

# 初始化: 权重全零
w = np.zeros(3)
b = 0.0
lr = 0.01
epochs = 500
loss_history = []

for epoch in range(epochs):
    # 前向传播: y_pred = X @ w + b
    y_pred = X @ w + b
    error = y_pred - y  # (200,)
    
    # 梯度: dL/dw = (2/n) * X^T @ error
    dw = (2 / n) * X.T @ error
    db = (2 / n) * error.sum()
    
    # 更新参数
    w -= lr * dw
    b -= lr * db
    
    # 记录 MSE loss
    mse = (error ** 2).mean()
    loss_history.append(mse)

print(f"  学习到的权重: trend={w[0]:.3f}, vol={w[1]:.3f}, volume={w[2]:.3f}, bias={b:.3f}")
print(f"  真实值:       trend=0.800, vol=-0.500, volume=0.300, bias=0.100")
print(f"  最终 MSE: {loss_history[-1]:.4f}")

# ----- 1B: sklearn 一行搞定 -----
print("\n--- 1B: sklearn 标准写法 ---")
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)

model = LinearRegression()
model.fit(X_train, y_train)

y_train_pred = model.predict(X_train)
y_test_pred = model.predict(X_test)

print(f"  sklearn 学到的: coef_={model.coef_.round(3)}, intercept_={model.intercept_:.3f}")
print(f"  训练集 R²: {r2_score(y_train, y_train_pred):.3f}")
print(f"  测试集 R²: {r2_score(y_test, y_test_pred):.3f}")
print(f"  训练集 MSE: {mean_squared_error(y_train, y_train_pred):.4f}")
print(f"  测试集 MSE: {mean_squared_error(y_test, y_test_pred):.4f}")

# 画图: 损失下降曲线 + 预测 vs 真实
fig, axes = plt.subplots(1, 3, figsize=(14, 4))

axes[0].plot(loss_history)
axes[0].set_title("梯度下降: MSE 下降曲线")
axes[0].set_xlabel("迭代次数")
axes[0].set_ylabel("MSE")

axes[1].scatter(y_test, y_test_pred, alpha=0.6, edgecolors="k", linewidth=0.3)
axes[1].plot([y_test.min(), y_test.max()], [y_test.min(), y_test.max()], "r--", lw=1.5)
axes[1].set_title(f"预测 vs 真实 (测试集, R²={r2_score(y_test, y_test_pred):.3f})")
axes[1].set_xlabel("真实值")
axes[1].set_ylabel("预测值")

axes[2].scatter(y_train, y_train_pred, alpha=0.6, s=20, label="训练集")
axes[2].scatter(y_test, y_test_pred, alpha=0.8, s=30, label="测试集")
axes[2].plot([y.min(), y.max()], [y.min(), y.max()], "r--", lw=1)
axes[2].set_title("训练集 vs 测试集")
axes[2].set_xlabel("真实值"); axes[2].set_ylabel("预测值")
axes[2].legend()

plt.tight_layout()
plt.savefig(str(Path(__file__).parent / "day02_linear_regression.png"), dpi=100)
plt.close()
print(f"\n  图表已保存: {Path(__file__).parent}/day02_linear_regression.png")


# ============================================================
#  PART 2: 决策树 —— 基于规则选股
# ============================================================
print("\n\n" + "─" * 50)
print("  PART 2: 决策树 Decision Tree")
print("─" * 50)
print("\n  概念: 一系列 if-else 规则把数据分成纯的子集")
print("  量化类比: 'PE<15 且 ROE>10% → 买入' 这样的规则链\n")

# ----- 生成模拟数据（股票分类） -----
n = 300
pe = np.random.uniform(5, 50, n)     # 市盈率
roe = np.random.uniform(2, 25, n)    # ROE
momentum = np.random.uniform(-20, 40, n)  # 动量

# 标签规则: PE<20 且 ROE>10 且 动量>10 → 好股(1)
y_cls = ((pe < 20) & (roe > 10) & (momentum > 10)).astype(int)
X_cls = np.column_stack([pe, roe, momentum])
feature_names = ["PE", "ROE", "动量"]

print(f"  规则: PE<20 且 ROE>10 且 动量>10 → 好股")
print(f"  好股: {y_cls.sum()}/{n} ({y_cls.sum()/n:.0%}), 差股: {n-y_cls.sum()}/{n}")

# ----- 2A: 手写信息熵和最佳分割点 -----
print("\n--- 2A: 手写信息熵 + 查找最佳分割点 ---")

def entropy(y):
    """信息熵: 混乱度指标，越纯越低"""
    _, counts = np.unique(y, return_counts=True)
    probs = counts / len(y)
    return -np.sum(probs * np.log2(probs + 1e-10))

def information_gain(X_col, y, split_val):
    """分割后的信息增益 = 父熵 - 加权子熵"""
    left_mask = X_col <= split_val
    right_mask = ~left_mask
    if left_mask.sum() == 0 or right_mask.sum() == 0:
        return 0
    
    parent_ent = entropy(y)
    left_ent = entropy(y[left_mask])
    right_ent = entropy(y[right_mask])
    
    w_left = left_mask.sum() / len(y)
    w_right = right_mask.sum() / len(y)
    
    return parent_ent - (w_left * left_ent + w_right * right_ent)

# 在 PE 特征上找最佳分割点
print("\n  在 PE 上搜索最佳分割点:")
best_gain = 0
best_split = 0
for split_val in np.linspace(10, 40, 100):
    gain = information_gain(X_cls[:, 0], y_cls, split_val)
    if gain > best_gain:
        best_gain = gain
        best_split = split_val
        # 找到后继续，确保全局最优

print(f"    最佳分割点: PE = {best_split:.1f}")
print(f"    信息增益:   {best_gain:.3f} bits")
print(f"    分割前熵:   {entropy(y_cls):.3f} bits")
print(f"    分割后:    左子集{(X_cls[:,0]<=best_split).sum()}条, 右子集{(X_cls[:,0]>best_split).sum()}条")

# 对三个特征分别算最佳分割点
print("\n  各特征最佳分割点:")
for i, name in enumerate(feature_names):
    best_g, best_s = 0, 0
    lo, hi = X_cls[:, i].min(), X_cls[:, i].max()
    for s in np.linspace(lo, hi, 100):
        g = information_gain(X_cls[:, i], y_cls, s)
        if g > best_g:
            best_g, best_s = g, s
    print(f"    {name:6s}: 分割点={best_s:.1f}, 信息增益={best_g:.3f}")

# ----- 2B: sklearn 决策树 + 可视化 -----
print("\n--- 2B: sklearn 决策树 ---")
from sklearn.tree import DecisionTreeClassifier, plot_tree

X_tr, X_te, y_tr, y_te = train_test_split(X_cls, y_cls, test_size=0.3, random_state=42)

# 不同 max_depth 对比（防止过拟合）
for depth in [2, 3, 5, None]:
    dt = DecisionTreeClassifier(max_depth=depth, random_state=42)
    dt.fit(X_tr, y_tr)
    train_acc = dt.score(X_tr, y_tr)
    test_acc = dt.score(X_te, y_te)
    depth_str = str(depth) if depth else "无限制"
    warning = " ⚠️ 过拟合!" if (train_acc - test_acc > 0.1) else ""
    bar = "█" * int(test_acc * 30) + "░" * (30 - int(test_acc * 30))
    print(f"  max_depth={depth_str:4s}  训练:{train_acc:.1%}  测试:{test_acc:.1%}  {bar}{warning}")

# 最终模型: max_depth=3（剪枝防止过拟合）
dt_final = DecisionTreeClassifier(max_depth=3, random_state=42)
dt_final.fit(X_tr, y_tr)

print(f"\n  最终模型 (max_depth=3) 测试准确率: {dt_final.score(X_te, y_te):.1%}")
print(f"  特征重要性: PE={dt_final.feature_importances_[0]:.3f}, "
      f"ROE={dt_final.feature_importances_[1]:.3f}, "
      f"动量={dt_final.feature_importances_[2]:.3f}")

# 可视化决策树
fig, ax = plt.subplots(figsize=(14, 6))
plot_tree(dt_final, feature_names=feature_names,
          class_names=["差股", "好股"], filled=True,
          rounded=True, fontsize=10, ax=ax)
ax.set_title("决策树可视化 (max_depth=3)", fontsize=14)
plt.tight_layout()
plt.savefig(str(Path(__file__).parent / "day02_decision_tree.png"), dpi=120)
plt.close()
print(f"  决策树图表已保存: {Path(__file__).parent}/day02_decision_tree.png")

# 额外可视化: 特征空间分割（PE vs ROE）
fig, ax = plt.subplots(figsize=(8, 6))
# 实际好股 vs 差股
ax.scatter(X_te[y_te==0, 0], X_te[y_te==0, 1], c="red", alpha=0.4, s=30, label="实际差股")
ax.scatter(X_te[y_te==1, 0], X_te[y_te==1, 1], c="green", alpha=0.4, s=30, label="实际好股")
# 预测错误标出来
y_pred = dt_final.predict(X_te)
wrong = y_pred != y_te
if wrong.sum() > 0:
    ax.scatter(X_te[wrong, 0], X_te[wrong, 1], c="black", s=60, marker="x", 
               linewidths=2, label=f"预测错({wrong.sum()}个)")

ax.set_xlabel("PE"); ax.set_ylabel("ROE")
ax.set_title(f"决策树分类结果\n测试准确率: {dt_final.score(X_te, y_te):.1%}, 深度=3")
ax.legend()
plt.tight_layout()
plt.savefig("F:/datax/learning/day02_feature_space.png", dpi=100)
plt.close()
print("  特征空间图表已保存: F:/datax/learning/day02_feature_space.png")


# ============================================================
#  小结
# ============================================================
print("\n\n" + "=" * 60)
print("  Day 2 小结")
print("=" * 60)
print("""
  线性回归:
    - 预测连续值（涨跌幅、收益率），不是分类
    - 核心: 最小化 MSE，用梯度下降或正规方程求解
    - sklearn: LinearRegression().fit(X, y) 一行搞定
    - 评估指标: MSE / RMSE / R²
  
  决策树:
    - if-else 规则链，天然可解释
    - 核心: 信息熵/基尼不纯度 → 选最佳分割点
    - 过拟合控制: max_depth 剪枝（关键！）
    - sklearn: DecisionTreeClassifier(max_depth=3).fit(X, y)
  
  量化应用:
    - 线性回归 → 多因子选股，预测预期收益
    - 决策树 → 发现可解释的选股规则，类似策略回测参数优化
  
  Day 3 预告: 交叉验证 —— 为什么你的回测可能骗了你
""")

print("\n  ✅ Day 2 完成! 生成了 3 张图表:")
print("     - day02_linear_regression.png  (回归拟合效果)")
print("     - day02_decision_tree.png      (决策树结构)")
print("     - day02_feature_space.png      (特征空间分类)")
