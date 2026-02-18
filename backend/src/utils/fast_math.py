import numpy as np
from numba import jit

@jit(nopython=True)
def calculate_hurst_exponent(time_series):
    """
    Calculate the Hurst Exponent to determine time series memory.
    H < 0.5: Mean Reverting
    H = 0.5: Random Walk (Brownian)
    H > 0.5: Trending
    
    Optimized with Numba JIT for C-speed.
    """
    lags = range(2, 20)
    tau = [np.sqrt(np.std(np.subtract(time_series[lag:], time_series[:-lag]))) for lag in lags]
    
    # Polyfit logic in pure numpy/numba
    # Log-Log plot
    y = np.log(np.array(tau))
    x = np.log(np.array(list(lags)))
    
    # Linear regression: y = mx + c
    A = np.vstack((x, np.ones(len(x)))).T
    # Numba doesn't support np.linalg.lstsq perfectly in nopython mode sometimes,
    # so we implement simple linear regression manually for speed
    
    n = len(x)
    sum_x = np.sum(x)
    sum_y = np.sum(y)
    sum_xy = np.sum(x * y)
    sum_xx = np.sum(x * x)
    
    slope = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x * sum_x)
    
    return slope * 2.0  # Hurst = slope * 2 (approx for variogram method)

@jit(nopython=True)
def calculate_garman_klass_volatility(open_price, high, low, close):
    """
    Garman-Klass Volatility Estimator.
    Far more efficient than standard Close-to-Close deviation.
    """
    period = len(close)
    log_hl = np.log(high / low) ** 2
    log_co = np.log(close / open_price) ** 2
    
    factor = 0.5 * log_hl - (2 * np.log(2) - 1) * log_co
    
    return np.sqrt(np.sum(factor) / period)

@jit(nopython=True)
def calculate_rsi_fast(prices, period=14):
    """
    JIT-compiled RSI calculation.
    """
    deltas = np.diff(prices)
    seed = deltas[:period+1]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i - 1] 
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta

        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down
        rsi[i] = 100. - 100. / (1. + rs)
        
    return rsi
