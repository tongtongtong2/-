# AI 工程师学习路线 — MLOps 方向
# 每天和 Hermes 确认进度，完成打 ✅

## 阶段 0: ML 基础速通 (2周)
- [x] 跑通 Titanic 分类模型 → 实际做了手写 k-NN (Day 1)
- [ ] 理解 accuracy/precision/recall/F1
- [ ] 理解过拟合/欠拟合/正则化
- [ ] 理解训练/验证/测试集划分

## 阶段 1: 模型服务化 (2周)
- [ ] FastAPI 包装模型 → POST /predict
- [ ] MLflow 实验追踪 + UI 对比
- [ ] 模型版本管理 (staging → production)

## 阶段 2: 训练流水线 (3周)
- [ ] 构建特征 ETL pipeline
- [ ] 数据验证 (Great Expectations / TFDV)
- [ ] MLflow Model Registry

## 阶段 3: 部署与容器化 (3周)
- [ ] Docker 容器化模型服务
- [ ] BentoML / Triton 推理服务
- [ ] 模型 A/B 测试 (灰度发布)

## 阶段 4: 监控与自动化 (3周)
- [ ] Prometheus + Grafana 模型监控
- [ ] 数据漂移检测 (Evidently AI)
- [ ] CI/CD for ML (GitHub Actions)

## 终极项目: ML 平台 (3周)
- [ ] 数据 pipeline (Spark/Flink)
- [ ] 训练 pipeline (MLflow)
- [ ] 推理服务 (Docker + API)
- [ ] 监控面板 + CI/CD

---
最后更新: 2026-05-26
当前进度: 阶段 0 — 2/4 (Day 1-2 done)

## 第一周进度 (2026-05-25 ~ 2026-05-29)
- [x] Day 1 (Mon): 手写 k-NN 分类器 — 理解训练/测试、准确率、过拟合 (day01_first_model.py)
- [x] Day 2 (Tue): 线性回归 + 决策树 — 手写梯度下降/信息熵 + sklearn (day02_regression_tree.py)
- [ ] Day 3 (Wed): 交叉验证 — K-Fold、GridSearchCV、防止过拟合的工程手段
- [ ] Day 4 (Thu): 真实数据实战 — 用选股因子跑模型，连接回测思路
- [ ] Day 5 (Fri): 阶段 0 小结 — 整理笔记，输出一个完整的选股模型脚本
