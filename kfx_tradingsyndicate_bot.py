import MetaTrader5 as mt5
import time
from datetime import datetime

# --- Configuration ---
SYMBOLS = ["XAUUSDm", "GBPUSDm", "USDJPYm", "EURUSDm", "US30m"]
LOT = 0.1
TIMEFRAME = mt5.TIMEFRAME_M1  # 1-minute candles
MAX_SPREAD = 200  # adjust depending on the symbol
MAGIC_NUMBER = 100000
EMA_PERIOD = 200
SL_PIPS = 60  # Stop Loss in pips
TP_PIPS =120   # Take Profit in pips
SUPPORT_RESISTANCE_CANDLES = 10  # Last X candles for Support/Resistance
TRENDLINE_CANDLES = 3  # Number of candles to determine trendline breakouts

# --- Connect to MetaTrader 5 ---
if not mt5.initialize():
    print("MetaTrader 5 initialization failed:", mt5.last_error())
    quit()

print("MetaTrader 5 connected")

# --- Get account info ---
account_info = mt5.account_info()
if account_info is not None:
    print(f"Logged into account: {account_info.login}")
else:
    print("Failed to get account info")
    mt5.shutdown()
    quit()

# --- Helper functions ---

def get_spread(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return (tick.ask - tick.bid) / mt5.symbol_info(symbol).point

def get_candle(symbol):
    candles = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, 2)
    if candles is not None and len(candles) == 2:
        return candles[0], candles[1]
    return None, None

def get_ema(symbol, period=EMA_PERIOD):
    candles = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, period + 1)
    if candles is None or len(candles) < period:
        return None
    closes = [c['close'] for c in candles]
    return sum(closes[-period:]) / period

def get_support_resistance(symbol, candles_count=SUPPORT_
RESISTANCE_CANDLES):
    candles = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, candles_count)
    if candles is None or len(candles) < candles_count:
        return None, None

    highs = [candle['high'] for candle in candles]
    lows = [candle['low'] for candle in candles]
    support = min(lows)
    resistance = max(highs)
    return support, resistance

def get_trendline(symbol, candles_count=TRENDLINE_CANDLES):
    candles = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, candles_count)
    if candles is None or len(candles) < candles_count:
        return None

    highs = [candle['high'] for candle in candles]
    lows = [candle['low'] for candle in candles]

    trend_up = highs[-1] > highs[0] and lows[-1] > lows[0]  # Detect if trend is up
    trend_down = highs[-1] < highs[0] and lows[-1] < lows[0]  # Detect if trend is down

    return trend_up, trend_down

def check_bullish_engulfing(prev, current):
    return current['close'] > current['open'] and prev['close'] < prev['open'] and current['open'] < prev['close'] and current['close'] > prev['open']

def check_bearish_engulfing(prev, current):
    return current['close'] < current['open'] and prev['close'] > prev['open'] and current['open'] > prev['close'] and current['close'] < prev['open']

def is_doji(candle):
    body_size = abs(candle.close - candle.open)
    candle_range = candle.high - candle.low
    upper_wick = candle.high - max(candle.close, candle.open)
    lower_wick = min(candle.close, candle.open) - candle.low
    
    # Refined Doji: small body, balanced wicks
    body_to_range_ratio = body_size / candle_range
    return body_to_range_ratio < 0.1 and upper_wick > body_size and lower_wick > body_size

def is_pin_bar(candle, prev_candle):
    body_size = abs(candle.close - candle.open)
    upper_wick = candle.high - max(candle.close, candle.open)
    lower_wick = min(candle.close, candle.open) - candle.low
    body_to_upper_wick_ratio = upper_wick / body_size
    body_to_lower_wick_ratio = lower_wick / body_size
    
    # Refined Pin Bar: wick at least twice the body size
    if body_size > 0:  # avoid division by zero
        if (upper_wick > body_size * 2 and lower_wick < body_size) or \
           (lower_wick > body_size * 2 and upper_wick < body_size):
            if candle.close > prev_candle.close and lower_wick > upper_wick:  # Bullish Pin Bar (bottom body)
                return "bullish"
            elif candle.close < prev_candle.close and upper_wick > lower_wick:  # Bearish Pin Bar (top body)
                return "bearish"
    return None

def place_order(symbol, order_type, stop_loss, take_profit):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"{symbol}: Failed to get tick data")
        return

    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    deviation = 20
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": LOT,
        "type": order_type,
        "price": price,
        "sl": stop_loss,
        "tp": take_profit,
        "deviation": deviation,
        "magic": MAGIC_NUMBER,
        "comment": "KFX Bot Entry",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Order send failed for {symbol}: {result.comment}")
    else:
        action = "BUY" if order_type == mt5.ORDER_TYPE_BUY else "SELL"
        print(f"{symbol}: {action} executed at {price}")

# --- Main Loop ---
try:
    print("Bot is running... Press Ctrl+C to stop.")

    while True:
        for symbol in SYMBOLS:
            if not mt5.symbol_select(symbol, True):
                print(f"Failed to select {symbol}")
                continue

            spread = get_spread(symbol)
            if spread is None or spread > MAX_SPREAD:
                print(f"{symbol}: Spread too high ({spread})")
                continue

            prev_candle, current_candle = get_candle(symbol)
            if prev_candle is None or current_candle is None:
                print(f"Failed to fetch candles for {symbol}")
                continue

            ema = get_ema(symbol) 
            if ema is None:
                print(f"{symbol}: EMA not available")
                continue

            # Get market structure (support/resistance) and trendline
            support, resistance = get_support_resistance(symbol)
            trend_up, trend_down = get_trendline(symbol)

            # Trend direction logic
            trend = "up" if current_candle['close'] > ema else "down"
            print(f"Trend for {symbol}: {'Up' if trend == 'up' else 'Down'}")

            # Entry logic with trend and structure checks
            if trend == "up" and check_bullish_engulfing(prev_candle, current_candle) and current_candle['close'] > support:
                # Calculate stop loss and take profit
                stop_loss = current_candle['close'] - SL_PIPS * mt5.symbol_info(symbol).point
                take_profit = current_candle['close'] + TP_PIPS * mt5.symbol_info(symbol).point
                place_order(symbol, mt5.ORDER_TYPE_BUY, stop_loss, take_profit)
            elif trend == "down" and check_bearish_engulfing(prev_candle, current_candle) and current_candle['close'] < resistance:
                # Calculate stop loss and take profit
                stop_loss = current_candle['close'] + SL_PIPS * mt5.symbol_info(symbol).point
                take_profit = current_candle['close'] - TP_PIPS * mt5.symbol_info(symbol).point
                place_order(symbol, mt5.ORDER_TYPE_SELL, stop_loss, take_profit)
            else:
                print(f"{symbol}: No valid signal")

        time.sleep(60)

except KeyboardInterrupt:
    print("Bot stopped by user")

finally:
    mt5.shutdown()
    print("MetaTrader 5 disconnected")

