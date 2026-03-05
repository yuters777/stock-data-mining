"""
Re-run Variant A' with LIVE earnings filter.

Same config as run_phase3_variant_a_prime.py but with static earnings
calendar loaded, saving results to results/phase3_25ticker_earnings_fix/.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Monkey-patch the results dir BEFORE importing the run module
import backtester.run_phase3_variant_a_prime as run_mod

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'results', 'phase3_25ticker_earnings_fix')
os.makedirs(RESULTS_DIR, exist_ok=True)
run_mod.RESULTS_DIR = RESULTS_DIR

if __name__ == '__main__':
    run_mod.main()
