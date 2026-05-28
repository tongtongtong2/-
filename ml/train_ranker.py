"""LightGBM 排序模型训练脚本。

用法：python -m ml.train_ranker [--days 180] [--output models/lgbm_ranker.pkl]

从 SQLite 历史数据构建特征矩阵，用 10 日前向收益率作为标签训练 LightGBM 排序模型。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_feature_store(db_path: str, start_date: str, end_date: str) -> pd.DataFrame:
    """从 SQLite daily_bars 构建全量特征矩阵。

    每行 = (stock_code, trade_date, features..., forward_ret_10d)
    """
    import sqlite3
    conn = sqlite3.connect(db_path)

    print(f"  加载日线数据 {start_date} ~ {end_date}...")
    bars = pd.read_sql_query(
        "SELECT stock_code, trade_date, open, high, low, close, volume "
        "FROM daily_bars WHERE trade_date BETWEEN ? AND ? ORDER BY stock_code, trade_date",
        conn, params=(start_date, end_date)
    )
    conn.close()

    if bars.empty:
        print("  无数据")
        return pd.DataFrame()

    print(f"  共 {len(bars)} 条日线，{bars['stock_code'].nunique()} 只股票")

    all_features = []
    grouped = bars.groupby("stock_code")

    for code, group in grouped:
        df = group.sort_values("trade_date").reset_index(drop=True)
        if len(df) < 80:
            continue

        closes = df["close"].values.astype(float)
        volumes = df["volume"].values.astype(float)
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)

        for i in range(70, len(df) - 10):
            c = closes[:i+1]
            v = volumes[:i+1]
            h = highs[:i+1]
            lo = lows[:i+1]

            last = c[-1]
            if last <= 0:
                continue

            ma5 = np.mean(c[-5:])
            ma10 = np.mean(c[-10:])
            ma20 = np.mean(c[-20:])
            ma60 = np.mean(c[-60:])

            ret_5 = last / c[-6] - 1 if c[-6] > 0 else 0
            ret_10 = last / c[-11] - 1 if c[-11] > 0 else 0
            ret_20 = last / c[-21] - 1 if c[-21] > 0 else 0
            ret_60 = last / c[-61] - 1 if c[-61] > 0 else 0

            daily_ret = np.diff(c[-21:]) / c[-21:-1]
            vol_std = np.std(daily_ret)

            peak = np.maximum.accumulate(c[-20:])
            dd = (c[-20:] / peak) - 1
            max_dd = np.min(dd)

            avg5v = np.mean(v[-5:])
            avg20v = np.mean(v[-20:])
            vol_ratio = avg5v / avg20v if avg20v > 0 else 1.0

            high60 = np.max(c[-60:])
            dist_high60 = (high60 - last) / high60 if high60 > 0 else 0

            avg_turnover = avg20v * np.mean(c[-20:])

            # ATR
            prev_c = c[-15:-1]
            tr = np.maximum(
                h[-14:] - lo[-14:],
                np.maximum(np.abs(h[-14:] - prev_c), np.abs(lo[-14:] - prev_c))
            )
            atr = np.mean(tr) / last if last > 0 else 0

            # 均线多头
            ma_bullish = 1.0 if (ma5 > ma10 > ma20 > ma60) else 0.0

            # 10日前向收益率（标签）
            forward_close = closes[i + 10] if i + 10 < len(closes) else closes[-1]
            forward_ret = forward_close / last - 1

            all_features.append({
                "stock_code": code,
                "trade_date": df.iloc[i]["trade_date"],
                "ret_5": ret_5,
                "ret_10": ret_10,
                "ret_20": ret_20,
                "ret_60": ret_60,
                "vol_std": vol_std,
                "max_dd": max_dd,
                "vol_ratio_5_20": vol_ratio,
                "dist_high60": dist_high60,
                "avg_turnover_20": avg_turnover,
                "atr_pct": atr,
                "ma_bullish": ma_bullish,
                "bias_ma20": last / ma20 - 1 if ma20 > 0 else 0,
                "forward_ret_10d": forward_ret,
            })

    result = pd.DataFrame(all_features)
    print(f"  构建特征矩阵: {len(result)} 样本")
    return result


def train_model(features_df: pd.DataFrame, output_path: str):
    """训练 LightGBM 排序模型。"""
    import lightgbm as lgb
    import joblib

    if features_df.empty:
        print("  特征矩阵为空，无法训练")
        return None

    feature_cols = [
        "ret_5", "ret_10", "ret_20", "ret_60",
        "vol_std", "max_dd", "vol_ratio_5_20",
        "dist_high60", "avg_turnover_20", "atr_pct",
        "ma_bullish", "bias_ma20",
    ]

    df = features_df.dropna(subset=feature_cols + ["forward_ret_10d"]).copy()
    # 标签：10日收益率 > 5% 为正样本
    df["label"] = (df["forward_ret_10d"] > 0.05).astype(int)

    # 时间序列分割：前80%训练，后20%验证
    dates = sorted(df["trade_date"].unique())
    split_idx = int(len(dates) * 0.8)
    train_dates = set(dates[:split_idx])
    val_dates = set(dates[split_idx:])

    train_df = df[df["trade_date"].isin(train_dates)]
    val_df = df[df["trade_date"].isin(val_dates)]

    print(f"  训练集: {len(train_df)} 样本 ({len(train_dates)} 天)")
    print(f"  验证集: {len(val_df)} 样本 ({len(val_dates)} 天)")
    print(f"  正样本比例: 训练 {train_df['label'].mean():.3f}, 验证 {val_df['label'].mean():.3f}")

    X_train = train_df[feature_cols].values
    y_train = train_df["label"].values
    X_val = val_df[feature_cols].values
    y_val = val_df["label"].values

    # LightGBM 排序模型（LambdaRank）
    # 按日期分组，每天的股票作为一个 query group
    train_groups = train_df.groupby("trade_date").size().values
    val_groups = val_df.groupby("trade_date").size().values

    train_data = lgb.Dataset(X_train, label=y_train, group=train_groups,
                             feature_name=feature_cols)
    val_data = lgb.Dataset(X_val, label=y_val, group=val_groups,
                           feature_name=feature_cols, reference=train_data)

    params = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "ndcg_eval_at": [5, 10],
        "learning_rate": 0.05,
        "num_leaves": 63,
        "min_data_in_leaf": 50,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
    }

    print("\n  开始训练 LightGBM LambdaRank...")
    callbacks = [lgb.log_evaluation(50)]
    model = lgb.train(
        params, train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=callbacks,
    )

    # 评估
    val_pred = model.predict(X_val)
    # 按日期计算 top-10 命中率
    val_df = val_df.copy()
    val_df["pred_score"] = val_pred
    hit_rates = []
    for dt, grp in val_df.groupby("trade_date"):
        if len(grp) < 10:
            continue
        top10 = grp.nlargest(10, "pred_score")
        hit_rate = top10["label"].mean()
        hit_rates.append(hit_rate)

    avg_hit = np.mean(hit_rates) if hit_rates else 0
    print(f"\n  验证集 Top-10 平均命中率: {avg_hit:.3f}")
    print(f"  （即模型选出的前10只票中，平均 {avg_hit*100:.1f}% 在未来10天涨幅>5%）")

    # 特征重要性
    importance = model.feature_importance(importance_type="gain")
    feat_imp = sorted(zip(feature_cols, importance), key=lambda x: -x[1])
    print("\n  特征重要性 (gain):")
    for name, imp in feat_imp:
        print(f"    {name:20s}: {imp:.0f}")

    # 保存模型
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    joblib.dump(model, output_path)
    print(f"\n  模型已保存: {output_path}")

    return model


def main():
    parser = argparse.ArgumentParser(description="训练 LightGBM 选股排序模型")
    parser.add_argument("--days", type=int, default=180, help="使用最近N天数据训练")
    parser.add_argument("--output", type=str, default="models/lgbm_ranker.pkl", help="模型输出路径")
    parser.add_argument("--db", type=str, default=None, help="SQLite数据库路径")
    args = parser.parse_args()

    db_path = args.db or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "backtest", "data", "market_data.db"
    )

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    print("=" * 60)
    print(f"  LightGBM 选股排序模型训练")
    print(f"  数据范围: {start_date} ~ {end_date}")
    print("=" * 60)

    features = build_feature_store(db_path, start_date, end_date)
    if features.empty:
        print("  无法构建特征，退出")
        sys.exit(1)

    train_model(features, args.output)


if __name__ == "__main__":
    main()
