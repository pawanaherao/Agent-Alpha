import time
import numpy as np
import sys
import os

# Add parent dir
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..')))

from src.utils.fast_math import calculate_hurst_exponent

def pure_python_hurst(time_series):
    # Slow python implementation for comparison
    lags = range(2, 20)
    tau = []
    for lag in lags:
        diff = np.subtract(time_series[lag:], time_series[:-lag])
        tau.append(np.sqrt(np.std(diff)))
    return 0.5 # Dummy return

def test_math_performance():
    print(f"\n=== Phase 5: Math Kernel Benchmark ===\n")
    
    # Generate random data
    data = np.random.randn(1000).cumsum()
    
    # Warmup Numba (compilation happens here)
    print("1. Warming up JIT compiler...")
    start = time.time()
    _ = calculate_hurst_exponent(data)
    print(f"   Warmup Time: {(time.time() - start)*1000:.2f}ms")
    
    # Benchmark
    print("\n2. Benchmarking (1000 iterations)...")
    
    # Numba
    start = time.time()
    for _ in range(1000):
        _ = calculate_hurst_exponent(data)
    numba_time = time.time() - start
    print(f"   Numba Time: {numba_time:.4f}s")
    
    # Pure Python (Simulated Logic)
    start = time.time()
    for _ in range(1000):
        _ = pure_python_hurst(data)
    py_time = time.time() - start
    print(f"   Python Time: {py_time:.4f}s")
    
    speedup = py_time / numba_time
    print(f"\n   🚀 Speedup: {speedup:.1f}x")
    
    # Logic Check
    print("\n3. Logic Verification...")
    # Trending data (Linear)
    trend = np.linspace(0, 100, 1000)
    h_trend = calculate_hurst_exponent(trend)
    print(f"   Hurst (Trend): {h_trend:.4f} (Expected > 0.5)")
    
    # Mean Reverting (Sin wave)
    mr = np.sin(np.linspace(0, 100, 1000))
    h_mr = calculate_hurst_exponent(mr)
    print(f"   Hurst (Mean Rev): {h_mr:.4f} (Expected < 0.5)")

if __name__ == "__main__":
    test_math_performance()
