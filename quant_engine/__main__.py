"""允许 python -m quant_engine 运行"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from run_backtest import main
main()
