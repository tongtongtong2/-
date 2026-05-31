
"""
策略引擎 - 多策略命中评估（无需yaml依赖，手动解析）
"""
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class StrategyHit:
    name: str
    display_name: str
    confidence: float
    buy_zone: str = ""
    details: list = field(default_factory=list)

def _parse_yaml_simple(text: str) -> dict:
    """Simple YAML parser for our strategy format (no PyYAML dependency)"""
    result = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # Convert numeric values
            try:
                if "." in val:
                    val = float(val)
                else:
                    val = int(val)
            except (ValueError, TypeError):
                pass
            result[key] = val
    return result

class StrategyEngine:
    def __init__(self, strategies_dir: str = None):
        if strategies_dir is None:
            strategies_dir = Path(__file__).parent / "strategies"
        self.strategies_dir = Path(strategies_dir)
        self.strategies = self._load_strategies()

    def _load_strategies(self) -> List[dict]:
        strategies = []
        for f in sorted(self.strategies_dir.glob("*.yaml")):
            with open(f, encoding="utf-8") as fp:
                text = fp.read()
            s = _parse_yaml_simple(text)
            s["_file"] = f.name
            strategies.append(s)
        return strategies

    def evaluate(self, stock_data: dict) -> Dict:
        hits = []
        total_bonus = 0
        for s in self.strategies:
            hit = self._check_strategy(s, stock_data)
            if hit:
                hits.append(hit)
                total_bonus += s.get("score_bonus", 0)
        return {
            "hit_count": len(hits),
            "hit_strategies": [h.display_name for h in hits],
            "hit_details": hits,
            "total_bonus": total_bonus,
        }

    def _check_strategy(self, s: dict, data: dict) -> Optional[StrategyHit]:
        name = s.get("name", "")
        if name == "bull_trend_health":
            return self._check_bull_trend(data, s)
        elif name == "shrink_pullback":
            return self._check_shrink_pullback(data, s)
        elif name == "ma_golden_cross":
            return self._check_ma_golden_cross(data, s)
        elif name == "bottom_volume":
            return self._check_bottom_volume(data, s)
        elif name == "volume_breakout":
            return self._check_volume_breakout(data, s)
        return None

    def _check_bull_trend(self, data: dict, s: dict) -> Optional[StrategyHit]:
        details = []
        passed = 0
        ma5, ma10, ma20 = data.get("ma5", 0), data.get("ma10", 0), data.get("ma20", 0)
        if ma5 >= ma10 >= ma20:
            passed += 1; details.append("均线多头排列")
        else:
            details.append("均线非多头")
        if data.get("ma20_slope", 0) > 0:
            passed += 1; details.append("MA20向上")
        price = data.get("close", 0)
        ma60 = data.get("ma60", 1)
        if price > ma60:
            passed += 1; details.append(f"站上MA60({price/ma60-1:+.1%})")
        if passed >= 2:
            return StrategyHit(name=s["name"], display_name=s.get("display_name","多头趋势"),
                confidence=min(100, passed*33), buy_zone=f"MA20({ma20:.2f})上方", details=details)
        return None

    def _check_shrink_pullback(self, data: dict, s: dict) -> Optional[StrategyHit]:
        details = []; score = 0
        price = data.get("close", 0)
        ma5, ma10, ma20 = data.get("ma5", 1), data.get("ma10", 1), data.get("ma20", 1)
        if ma5 >= ma10 >= ma20:
            score += 30; details.append("多头排列")
        else:
            details.append("非多头排列")
        d5 = abs(price - ma5) / ma5
        d10 = abs(price - ma10) / ma10
        if d5 < 0.02:
            score += 35; details.append(f"回踩MA5({d5:.1%})")
        elif d10 < 0.03:
            score += 25; details.append(f"回踩MA10({d10:.1%})")
        else:
            details.append(f"距MA5{d5:.1%} 距MA10{d10:.1%}")
        vr = data.get("vol_ratio_5_20", 1.0)
        if vr < 0.7:
            score += 20; details.append(f"缩量(量比{vr:.2f})")
        else:
            details.append(f"量比{vr:.2f}")
        chg = data.get("change_pct", 0)
        if chg > -0.5:
            score += 10; details.append("未大幅下跌")
        if score >= 60:
            return StrategyHit(name=s["name"], display_name=s.get("display_name","缩量回踩"),
                confidence=score, buy_zone=f"MA5({ma5:.2f})~MA10({ma10:.2f})", details=details)
        return None

    def _check_ma_golden_cross(self, data: dict, s: dict) -> Optional[StrategyHit]:
        details = []; score = 0
        days = data.get("ma5_cross_ma10_days", 99)
        if days is not None and days <= 3:
            score += 40; details.append(f"MA5金叉MA10({days}天前)")
        else:
            details.append("无近期金叉")
        vr = data.get("vol_ratio_5_20", 1.0)
        if vr > 1.0:
            score += 20; details.append(f"放量确认(量比{vr:.2f})")
        price, ma5 = data.get("close", 0), data.get("ma5", 1)
        if abs(price / ma5 - 1) < 0.05:
            score += 15; details.append("未过度延伸")
        if score >= 40:
            return StrategyHit(name=s["name"], display_name=s.get("display_name","均线金叉"),
                confidence=score, buy_zone=f"MA5({ma5:.2f})附近", details=details)
        return None

    def _check_bottom_volume(self, data: dict, s: dict) -> Optional[StrategyHit]:
        details = []; score = 0
        dd = abs(data.get("dist_from_high_60d", 0))
        if dd > 0.15:
            score += 30; details.append(f"从高点回落{dd*100:.1f}%")
        else:
            details.append(f"回撤仅{dd*100:.1f}%")
        # 使用趋势量比（5日/20日）而非实时量比，避免单日脉冲误判
        vr_trend = data.get("vol_ratio_5_20", 1.0)
        vr_spot = data.get("volume_ratio", 1.0)
        if vr_trend > 1.5 or vr_spot > 2.5:
            score += 30
            tag = f"趋势量比{vr_trend:.1f}" if vr_trend > 1.5 else f"实时量比{vr_spot:.1f}"
            details.append(f"放量({tag})")
        else:
            details.append(f"量比{vr_trend:.1f}(趋势)/{vr_spot:.1f}(实时)")
        if data.get("change_pct", 0) > 0:
            score += 20; details.append("收阳")
        if score >= 40:
            return StrategyHit(name=s["name"], display_name=s.get("display_name","底部放量"),
                confidence=score, buy_zone="近期低点附近", details=details)
        return None

    def _check_volume_breakout(self, data: dict, s: dict) -> Optional[StrategyHit]:
        details = []; score = 0
        dist = abs(data.get("dist_from_high_20d", 999))
        if dist < 0.01:
            score += 30; details.append("接近20日高点")
        else:
            details.append(f"距20日高点{dist:.1%}")
        vr = data.get("volume_ratio", 1.0)
        if vr > 2.0:
            score += 30; details.append(f"放量{vr:.1f}倍")
        else:
            details.append(f"量比{vr:.1f}")
        price, high, low = data.get("close", 0), data.get("high", 0), data.get("low", 0)
        if high != low:
            cp = (price - low) / (high - low)
            if cp > 0.7:
                score += 20; details.append(f"强势收盘({cp:.0%})")
        if score >= 50:
            return StrategyHit(name=s["name"], display_name=s.get("display_name","放量突破"),
                confidence=score, buy_zone="突破位附近", details=details)
        return None
