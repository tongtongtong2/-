"""可插拔评分策略：手工打分 vs LightGBM 排序模型。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np
import pandas as pd

from config import Config


class ScoringStrategy(ABC):
    @abstractmethod
    def score(self, factors: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """给 factors DataFrame 添加 total_score 列并返回。"""


class HandTunedScoring(ScoringStrategy):
    """手工调参的多因子打分（当前默认策略）。"""

    def score(self, factors: pd.DataFrame, **kwargs) -> pd.DataFrame:
        from run_select import score_dataframe
        return score_dataframe(factors, **kwargs)


class MLScoring(ScoringStrategy):
    """LightGBM 排序模型评分。"""

    def __init__(self, model_path: str = None):
        self.model_path = model_path or Config.ML_MODEL_PATH
        self._model = None

    @property
    def model(self):
        if self._model is None:
            import joblib
            self._model = joblib.load(self.model_path)
        return self._model

    def _extract_features(self, df: pd.DataFrame) -> np.ndarray:
        """从因子 DataFrame 提取模型特征。"""
        feature_cols = [
            "ret_5", "ret_10", "ret_20", "ret_60",
            "vol_std", "max_dd", "vol_ratio_5_20",
            "dist_high60", "avg_turnover_20",
            "individual_flow_score", "northbound_score",
            "shareholder_bonus", "sector_flow_factor",
            "history_score",
        ]
        available = [c for c in feature_cols if c in df.columns]
        X = df[available].fillna(0).values
        return X

    def score(self, factors: pd.DataFrame, **kwargs) -> pd.DataFrame:
        df = factors.copy()
        X = self._extract_features(df)
        df["total_score"] = self.model.predict(X)
        return df


def get_scoring_strategy() -> ScoringStrategy:
    """根据配置返回评分策略实例。"""
    if Config.USE_ML_SCORING:
        import os
        if os.path.exists(Config.ML_MODEL_PATH):
            return MLScoring()
        else:
            print(f"  ML模型不存在({Config.ML_MODEL_PATH})，回退到手工打分")
    return HandTunedScoring()
