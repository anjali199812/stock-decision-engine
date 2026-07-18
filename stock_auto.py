#!/usr/bin/env python3
"""
Automated Stock Decision Framework
User types any ticker -- script fetches all data and outputs BUY / WATCH / SKIP
Short-term: ATR-based entry tiers  |  Long-term: % pullback + 6-step Playbook
Run: python3 stock_auto.py
"""

import sys
import warnings
warnings.filterwarnings('ignore')

try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
except ImportError:
    print('\n  Missing libraries. Run: pip install yfinance pandas numpy')
    sys.exit(1)

DIVIDER  = '─' * 62
DIVIDER2 = '═' * 62


# ── DATA FETCHING ──────────────────────────────────────────────────────────────

def fetch(ticker):
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info

        if not info or (info.get('regularMarketPrice') is None and info.get('currentPrice') is None):
            return None, f'Ticker "{ticker}" not found. Check the spelling.'

        hist = stock.history(period='1y', auto_adjust=True)
        if hist.empty or len(hist) < 20:
            return None, f'Not enough price history for "{ticker}".'

        price = float(info.get('currentPrice') or info.get('regularMarketPrice') or hist['Close'].iloc[-1])

        # ATR (14-day) -- for short-term tiers
        high     = hist['High']
        low      = hist['Low']
        prev_cls = hist['Close'].shift(1)
        tr  = pd.concat([high - low,
                         (high - prev_cls).abs(),
                         (low  - prev_cls).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().dropna().iloc[-1])

        wk52_high = float(info.get('fiftyTwoWeekHigh') or hist['High'].max())
        wk52_low  = float(info.get('fiftyTwoWeekLow')  or hist['Low'].min())

        # Short-term tiers: ATR-based from 52-week high
        st_tier1 = round(wk52_high - 1.0 * atr, 2)
        st_tier2 = round(wk52_high - 2.5 * atr, 2)
        st_tier3 = round(wk52_high - 5.0 * atr, 2)

        # Long-term tiers: % pullback from 52-week high
        lt_tier1 = round(wk52_high * 0.92, 2)   # 8% below peak  -- Tier 1
        lt_tier2 = round(wk52_high * 0.82, 2)   # 18% below peak -- Tier 2
        lt_tier3 = round(wk52_high * 0.72, 2)   # 28% below peak -- Tier 3

        # Volume
        vol_20d   = float(hist['Volume'].tail(20).mean())
        vol_5d    = float(hist['Volume'].tail(5).mean())
        vol_ratio = round(vol_5d / vol_20d, 2) if vol_20d > 0 else 1.0

        # Price momentum (4-week)
        price_4wk     = float(hist['Close'].iloc[-20]) if len(hist) >= 20 else price
        momentum_pct  = round((price - price_4wk) / price_4wk * 100, 1)

        # Moving averages
        ma_50d   = float(hist['Close'].tail(50).mean())
        ma_200d  = float(hist['Close'].tail(200).mean()) if len(hist) >= 200 else None

        def safe(key):
            val = info.get(key)
            try:
                return float(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        return {
            'name':             info.get('longName') or info.get('shortName') or ticker,
            'sector':           info.get('sector') or info.get('quoteType') or 'N/A',
            'price':            price,
            'atr':              round(atr, 2),
            'wk52_high':        wk52_high,
            'wk52_low':         wk52_low,
            # Short-term tiers (ATR-based)
            'st_tier1':         st_tier1,
            'st_tier2':         st_tier2,
            'st_tier3':         st_tier3,
            # Long-term tiers (% pullback)
            'lt_tier1':         lt_tier1,
            'lt_tier2':         lt_tier2,
            'lt_tier3':         lt_tier3,
            'vol_ratio':        vol_ratio,
            'momentum_pct':     momentum_pct,
            'ma_50d':           round(ma_50d, 2),
            'ma_200d':          round(ma_200d, 2) if ma_200d else None,
            'peg':              safe('pegRatio'),
            'forward_pe':       safe('forwardPE'),
            'trailing_pe':      safe('trailingPE'),
            'revenue_growth':   safe('revenueGrowth'),
            'earnings_growth':  safe('earningsGrowth'),
            'eps':              safe('trailingEps'),
            'beta':             safe('beta'),
            'gross_margin':     safe('grossMargins'),
            'dividend_yield':   safe('dividendYield'),
            'market_cap':       safe('marketCap'),
        }, None

    except Exception as e:
        return None, f'Could not fetch data: {e}'


# ── HORIZON SELECTION ──────────────────────────────────────────────────────────

def ask_horizon():
    print()
    print(DIVIDER)
    print('  INVESTMENT HORIZON')
    print(DIVIDER)
    print('\n  Are you looking at this as a short-term or long-term investment?')
    print()
    print('    [1] Short-term trading')
    print('        Holding for weeks to months. Focus: price momentum, ATR entry,')
    print('        volume confirmation. Tool: ATR-based buy limit tiers.')
    print()
    print('    [2] Long-term investing')
    print('        Holding for 1 year or more. Focus: business quality, valuation,')
    print('        margin of safety. Tool: % pullback from peak (6-step Playbook).')
    print()
    while True:
        raw = input('  Your choice (1 or 2): ').strip()
        if raw in ('1', '2'):
            mode = 'short' if raw == '1' else 'long'
            break
        print('  Please enter 1 or 2.')

    # Duration
    print()
    if mode == 'short':
        print('  How long do you plan to hold this position?')
        durations = [
            '1 to 4 weeks   -- quick trade, tight stop loss needed',
            '1 to 3 months  -- medium swing trade',
            '3 to 6 months  -- longer swing, fundamentals still secondary',
        ]
    else:
        print('  How long do you plan to hold this position?')
        durations = [
            '6 months to 1 year  -- short long-term, check quarterly',
            '1 to 3 years        -- medium long-term, standard holding period',
            '3 to 5 years        -- long conviction hold',
            '5 years or more     -- buy and hold, compounding focus',
        ]

    for i, d in enumerate(durations, 1):
        print(f'    [{i}] {d}')
    while True:
        raw = input('  Your choice: ').strip()
        if raw.isdigit() and 1 <= int(raw) <= len(durations):
            duration = durations[int(raw) - 1].split('--')[0].strip()
            break
        print(f'  Please enter a number between 1 and {len(durations)}.')

    return mode, duration


# ── SCORING ────────────────────────────────────────────────────────────────────

def score_short(d):
    """
    Short-term scoring (10 pts max).
    Emphasises: price momentum, ATR-based entry zone, volume.
    Business quality and valuation are secondary but still checked.
    """
    score   = 0
    factors = []

    # Business Quality (max 3 pts)
    rg = d['revenue_growth']
    if rg is None:
        factors.append(('Revenue Growth', 0, 1, 'N/A', '?'))
    elif rg >= 0.05:
        score += 1
        factors.append(('Revenue Growth', 1, 1, f'+{rg*100:.1f}% YoY -- growing', '+'))
    else:
        factors.append(('Revenue Growth', 0, 1, f'{rg*100:.1f}% YoY -- weak or declining', '-'))

    eps = d['eps']
    if eps is None:
        factors.append(('Profitability (EPS)', 0, 1, 'N/A', '?'))
    elif eps > 0:
        score += 1
        factors.append(('Profitability (EPS)', 1, 1, f'EPS ${eps:.2f} -- profitable', '+'))
    else:
        factors.append(('Profitability (EPS)', 0, 1, f'EPS ${eps:.2f} -- loss-making', '-'))

    gm = d['gross_margin']
    if gm is None:
        factors.append(('Gross Margin', 0, 1, 'N/A -- common for ETFs', '?'))
    elif gm >= 0.40:
        score += 1
        factors.append(('Gross Margin', 1, 1, f'{gm*100:.0f}% -- strong margins', '+'))
    else:
        factors.append(('Gross Margin', 0, 1, f'{gm*100:.0f}% -- low margin', '-'))

    # Valuation (max 2 pts) -- secondary for short-term
    peg = d['peg']
    if peg is None:
        factors.append(('PEG Ratio', 0, 1, 'N/A', '?'))
    elif peg <= 2.0:
        score += 1
        factors.append(('PEG Ratio', 1, 1, f'{peg:.2f} -- fair or cheap', '+'))
    else:
        factors.append(('PEG Ratio', 0, 1, f'{peg:.2f} -- expensive', '-'))

    fpe = d['forward_pe']; tpe = d['trailing_pe']
    if fpe and tpe and fpe < tpe:
        score += 1
        factors.append(('Earnings Direction', 1, 1,
                         f'Fwd P/E {fpe:.1f}x < Trail {tpe:.1f}x -- earnings growing', '+'))
    elif fpe and tpe:
        factors.append(('Earnings Direction', 0, 1,
                         f'Fwd P/E {fpe:.1f}x > Trail {tpe:.1f}x -- earnings shrinking', '-'))
    else:
        factors.append(('Earnings Direction', 0, 1, 'N/A', '?'))

    # Entry Timing -- ATR-based tiers (max 4 pts)
    price = d['price']
    t1 = d['st_tier1']; t2 = d['st_tier2']; t3 = d['st_tier3']
    if price <= t3:
        score += 3
        factors.append(('Price Zone (ATR)', 3, 3,
                         f'${price:.2f} -- Tier 3, deep pullback from 52wk high', '+'))
    elif price <= t2:
        score += 2
        factors.append(('Price Zone (ATR)', 2, 3,
                         f'${price:.2f} -- Tier 2, moderate pullback from 52wk high', '+'))
    elif price <= t1:
        score += 1
        factors.append(('Price Zone (ATR)', 1, 3,
                         f'${price:.2f} -- Tier 1, small pullback from 52wk high', '~'))
    else:
        pct = round((d['wk52_high'] - price) / d['wk52_high'] * 100, 1)
        factors.append(('Price Zone (ATR)', 0, 3,
                         f'${price:.2f} -- only {pct}% below 52wk high, above all tiers', '-'))

    vr = d['vol_ratio']
    if vr >= 1.10:
        score += 1
        factors.append(('Volume Trend', 1, 1, f'{vr:.2f}x avg -- activity picking up', '+'))
    elif vr >= 0.80:
        factors.append(('Volume Trend', 0, 1, f'{vr:.2f}x avg -- normal, no strong signal', '~'))
    else:
        factors.append(('Volume Trend', 0, 1, f'{vr:.2f}x avg -- low activity', '-'))

    return score, 10, factors


def score_long(d):
    """
    Long-term scoring (10 pts max).
    Based on the 6-step Long-Term Investor's Playbook.
    Emphasises: fundamentals, valuation (PEG), margin of safety (% pullback).
    Volume and ATR are irrelevant at this horizon.
    """
    score   = 0
    factors = []

    # Step 1: Business Quality (max 4 pts)
    rg = d['revenue_growth']
    if rg is None:
        factors.append(('Revenue Growth YoY', 0, 1, 'N/A -- check financials manually', '?'))
    elif rg >= 0.05:
        score += 1
        factors.append(('Revenue Growth YoY', 1, 1, f'+{rg*100:.1f}% -- business is expanding', '+'))
    else:
        factors.append(('Revenue Growth YoY', 0, 1, f'{rg*100:.1f}% -- weak, limited tailwind', '-'))

    eps = d['eps']
    if eps is None:
        factors.append(('Profitability (EPS)', 0, 1, 'N/A', '?'))
    elif eps > 0:
        score += 1
        factors.append(('Profitability (EPS)', 1, 1, f'EPS ${eps:.2f} -- company is profitable', '+'))
    else:
        factors.append(('Profitability (EPS)', 0, 1, f'EPS ${eps:.2f} -- loss-making', '-'))

    gm = d['gross_margin']
    if gm is None:
        factors.append(('Gross Margin (Moat)', 0, 1, 'N/A -- common for ETFs and banks', '?'))
    elif gm >= 0.40:
        score += 1
        factors.append(('Gross Margin (Moat)', 1, 1,
                         f'{gm*100:.0f}% -- high margin, likely competitive moat', '+'))
    else:
        factors.append(('Gross Margin (Moat)', 0, 1,
                         f'{gm*100:.0f}% -- low margin, limited pricing power', '-'))

    eg = d['earnings_growth']
    if eg is None:
        factors.append(('Earnings Growth', 0, 1, 'N/A', '?'))
    elif eg > 0:
        score += 1
        factors.append(('Earnings Growth', 1, 1,
                         f'+{eg*100:.1f}% -- profits growing, long-term compounding in place', '+'))
    else:
        factors.append(('Earnings Growth', 0, 1,
                         f'{eg*100:.1f}% -- profits shrinking, investigate before buying', '-'))

    # Step 2: Valuation -- PEG is the core long-term metric (max 3 pts)
    peg = d['peg']
    if peg is None:
        factors.append(('PEG Ratio (core metric)', 0, 2,
                         'N/A -- ETF or pre-profit company, cannot calculate', '?'))
    elif peg < 1.0:
        score += 2
        factors.append(('PEG Ratio (core metric)', 2, 2,
                         f'{peg:.2f} -- UNDERVALUED relative to growth rate', '+'))
    elif peg <= 2.0:
        score += 1
        factors.append(('PEG Ratio (core metric)', 1, 2,
                         f'{peg:.2f} -- fairly valued, acceptable long-term entry', '~'))
    else:
        factors.append(('PEG Ratio (core metric)', 0, 2,
                         f'{peg:.2f} -- expensive, paying above what growth justifies', '-'))

    fpe = d['forward_pe']; tpe = d['trailing_pe']
    if fpe and tpe and fpe < tpe:
        score += 1
        factors.append(('Earnings Trajectory', 1, 1,
                         f'Fwd P/E {fpe:.1f}x < Trail {tpe:.1f}x -- earnings expected to grow', '+'))
    elif fpe and tpe:
        factors.append(('Earnings Trajectory', 0, 1,
                         f'Fwd P/E {fpe:.1f}x > Trail {tpe:.1f}x -- earnings expected to shrink', '-'))
    else:
        factors.append(('Earnings Trajectory', 0, 1, 'N/A', '?'))

    # Step 5: Entry zone -- % pullback from 52-week high (max 2 pts)
    # Long-term investors care about margin of safety, not daily ATR
    # Thresholds: <8% below peak = near high (no margin of safety)
    #             8-18%  = Tier 1 -- reasonable
    #             18-28% = Tier 2 -- good margin of safety
    #             >28%   = Tier 3 -- strong margin of safety
    price     = d['price']
    peak      = d['wk52_high']
    pullback  = round((peak - price) / peak * 100, 1)

    if pullback >= 28:
        score += 2
        factors.append(('Entry Zone (% pullback)', 2, 2,
                         f'{pullback}% below 52wk high -- Tier 3, strong margin of safety', '+'))
    elif pullback >= 8:
        score += 1
        factors.append(('Entry Zone (% pullback)', 1, 2,
                         f'{pullback}% below 52wk high -- Tier 1-2, reasonable entry', '~'))
    else:
        factors.append(('Entry Zone (% pullback)', 0, 2,
                         f'Only {pullback}% below 52wk high -- near peak, limited margin of safety', '-'))

    # Long-term trend: price vs 200-day MA (max 1 pt)
    ma200 = d['ma_200d']
    if ma200 is None:
        factors.append(('200-day MA Trend', 0, 1, 'N/A -- less than 1 year of data', '?'))
    elif price > ma200:
        score += 1
        factors.append(('200-day MA Trend', 1, 1,
                         f'Price ${price:.2f} is ABOVE 200-day MA ${ma200:.2f} -- long-term uptrend intact', '+'))
    else:
        factors.append(('200-day MA Trend', 0, 1,
                         f'Price ${price:.2f} is BELOW 200-day MA ${ma200:.2f} -- in long-term downtrend', '-'))

    return score, 10, factors


# ── OUTPUT HELPERS ─────────────────────────────────────────────────────────────

def fmt_cap(cap):
    if cap is None: return 'N/A'
    if cap >= 1e12: return f'${cap/1e12:.1f}T'
    if cap >= 1e9:  return f'${cap/1e9:.1f}B'
    return f'${cap/1e6:.0f}M'

def fmt_pct(val):
    return f'{val*100:.1f}%' if val is not None else 'N/A'

def wk52_label(price, low, high):
    if high == low: return 'N/A'
    pct = (price - low) / (high - low) * 100
    if pct >= 85: return f'{pct:.0f}% of range -- near 52wk HIGH (limited upside)'
    if pct <= 20: return f'{pct:.0f}% of range -- near 52wk LOW (potential value zone)'
    return f'{pct:.0f}% of 52wk range -- middle of range (neutral)'

def position_guide(beta):
    if beta is None: return 'Unknown -- use 8-10% as safe default'
    if beta < 0.5:  return '15-20% of portfolio (very low volatility)'
    if beta < 0.8:  return '12-15% of portfolio (low volatility)'
    if beta < 1.3:  return '10-12% of portfolio (moderate volatility)'
    if beta < 1.8:  return '8-10%  of portfolio (high volatility)'
    if beta < 2.5:  return '5-8%   of portfolio (very high volatility)'
    return '3-5%   of portfolio (speculative)'


# ── REPORT PRINTING ────────────────────────────────────────────────────────────

def print_report(ticker, d, score, max_pts, factors, mode, duration):
    mode_label = 'SHORT-TERM TRADING' if mode == 'short' else 'LONG-TERM INVESTING'

    print()
    print(DIVIDER2)
    print(f'  STOCK DECISION: {ticker.upper()}  --  {mode_label}')
    print(DIVIDER2)

    print(f'\n  {d["name"]}')
    print(f'  Sector        : {d["sector"]}')
    print(f'  Market Cap    : {fmt_cap(d["market_cap"])}')
    print(f'  Current Price : ${d["price"]:.2f}')
    print(f'  52-wk Range   : ${d["wk52_low"]:.2f} -- ${d["wk52_high"]:.2f}')
    print(f'  52-wk Position: {wk52_label(d["price"], d["wk52_low"], d["wk52_high"])}')
    beta_str = f'{d["beta"]:.2f}' if d["beta"] else 'N/A'
    print(f'  Beta          : {beta_str}')
    dy = d['dividend_yield']
    dy_str = f'{dy*100:.2f}%' if dy and dy < 0.5 else (f'{dy:.2f}%' if dy else 'None')
    print(f'  Dividend Yield: {dy_str}')
    print(f'  Holding plan  : {duration}')

    # Scoring guide
    print()
    print(DIVIDER)
    if mode == 'long':
        print('  SCORING GUIDE  [LONG-TERM INVESTING -- 10 pts total]')
        print(DIVIDER)
        print('  STEP 1: BUSINESS QUALITY                                  4 pts max')
        print('  Revenue Growth YoY  1pt  Is the company selling more each year?')
        print('                           Pass: >5% annual growth. Fail: flat or declining.')
        print('  Profitability (EPS) 1pt  Is the company making money after all costs?')
        print('                           Pass: EPS > 0. Fail: reporting a loss.')
        print('  Gross Margin        1pt  After making its product, how much profit remains?')
        print('                           Pass: >40%. High margin = competitive advantage (moat).')
        print('  Earnings Growth     1pt  Are profits growing year over year?')
        print('                           Pass: positive. Fail: profits shrinking.')
        print()
        print('  STEP 2: VALUATION                                         3 pts max')
        print('  PEG Ratio           2pt  Are you paying a fair price for the growth rate?')
        print('                           Formula: P/E divided by earnings growth rate.')
        print('                           <1.0 = undervalued (2pts), 1-2 = fair (1pt), >2 = expensive (0pt).')
        print('  Earnings Trajectory 1pt  Will next year\'s earnings be higher than this year\'s?')
        print('                           Pass: Forward P/E < Trailing P/E (earnings growing).')
        print()
        print('  STEP 5: ENTRY ZONE                                        2 pts max')
        print('  Entry Zone          2pt  How far is price below its 52-week high?')
        print('                           >28% below peak = 2pts (strong discount, best entry).')
        print('                           8-28% below peak = 1pt (reasonable entry).')
        print('                           <8% below peak  = 0pt (near all-time high, no discount).')
        print()
        print('  LONG-TERM TREND                                           1 pt max')
        print('  200-day MA          1pt  Is the stock in a long-term uptrend or downtrend?')
        print('                           Pass: price above 200-day moving average (institutions buying).')
        print('                           Fail: price below 200-day MA (long-term money is exiting).')
        print()
        print('  DECISION THRESHOLDS:  BUY = 8-10  |  WATCH = 5-7  |  SKIP = 0-4')
    else:
        print('  SCORING GUIDE  [SHORT-TERM TRADING -- 10 pts total]')
        print(DIVIDER)
        print('  BUSINESS QUALITY                                          3 pts max')
        print('  Revenue Growth      1pt  Is the company growing revenue year over year?')
        print('                           Pass: >5% growth. Fail: flat or declining.')
        print('  Profitability (EPS) 1pt  Is the company profitable?')
        print('                           Pass: EPS > 0. Fail: loss-making.')
        print('  Gross Margin        1pt  Does the company keep good profit per sale?')
        print('                           Pass: >40%. High margin reduces downside risk.')
        print()
        print('  VALUATION                                                 2 pts max')
        print('  PEG Ratio           1pt  Is the stock priced reasonably vs its growth?')
        print('                           Pass: PEG <= 2.0. Fail: >2.0 (overpriced).')
        print('  Earnings Direction  1pt  Are future earnings expected to be higher?')
        print('                           Pass: Forward P/E < Trailing P/E.')
        print()
        print('  ENTRY TIMING                                              4 pts max')
        print('  Price Zone (ATR)    3pt  Has the stock pulled back enough to be a good entry?')
        print('                           Uses ATR -- the average daily price movement over 14 days.')
        print('                           >5 ATR below 52wk high = 3pts (deep pullback).')
        print('                           2.5-5 ATR below       = 2pts (moderate pullback).')
        print('                           1-2.5 ATR below       = 1pt  (small pullback).')
        print('                           Above Tier 1          = 0pt  (too close to recent high).')
        print('  Volume Trend        1pt  Are more people buying this stock than usual?')
        print('                           Pass: 5-day avg volume > 110% of 20-day avg.')
        print('                           Higher volume confirms the move is real, not noise.')
        print()
        print('  DECISION THRESHOLDS:  BUY = 8-10  |  WATCH = 5-7  |  SKIP = 0-4')
    print(DIVIDER)

    # Factor table
    sections = {
        0: ('  STEP 1: BUSINESS QUALITY' if mode == 'long' else '  BUSINESS QUALITY'),
        3: ('  STEP 2: VALUATION'         if mode == 'long' else '  VALUATION'),
        5: ('  STEP 5: ENTRY ZONE'        if mode == 'long' else '  ENTRY TIMING'),
        7: ('  LONG-TERM TREND (200-day MA)' if mode == 'long' else ''),
    }
    if mode == 'short':
        sections = {0: '  BUSINESS QUALITY', 3: '  VALUATION', 5: '  ENTRY TIMING (ATR-based)'}

    print()
    print(DIVIDER)
    print(f'  FACTOR ANALYSIS  [{mode_label}]')
    print(DIVIDER)

    for i, (label, s, m, note, status) in enumerate(factors):
        if i in sections and sections[i]:
            print(f'\n{sections[i]}')
        icon = {'+': '✓', '-': '✗', '~': '~', '?': '?'}.get(status, status)
        bar  = '█' * s + '░' * (m - s)
        print(f'  {icon}  {label:<28}  {s}/{m} {bar:<3}  {note}')

    # Tiers section
    print()
    print(DIVIDER)
    if mode == 'short':
        print('  BUY LIMIT TIERS -- ATR-based (short-term)')
        print('  Method: 52-week high minus multiples of 14-day Average True Range')
        print(f'  ATR (14-day) = ${d["atr"]:.2f}  |  52-week high = ${d["wk52_high"]:.2f}')
        print()
        t1, t2, t3 = d['st_tier1'], d['st_tier2'], d['st_tier3']
        print(f'  Tier 1  ${t2:.2f} to ${t1:.2f}    (~1 ATR below peak -- first support)')
        print(f'  Tier 2  ${t3:.2f} to ${t2:.2f}    (~2.5 ATR below peak -- moderate pullback)')
        print(f'  Tier 3  below ${t3:.2f}             (~5 ATR below peak -- deep pullback)')
        print()
        print(f'  4-week momentum : {d["momentum_pct"]:+.1f}%')
        print(f'  Volume trend    : {d["vol_ratio"]:.2f}x 20-day average')
        print(f'  50-day MA       : ${d["ma_50d"]:.2f}  '
              f'(price {"ABOVE" if d["price"] > d["ma_50d"] else "BELOW"} short-term average)')
    else:
        print('  BUY LIMIT TIERS -- % Pullback from 52-week high (long-term)')
        print('  Method: fixed percentage discounts from peak price (margin of safety)')
        print(f'  52-week high = ${d["wk52_high"]:.2f}  |  Current pullback = '
              f'{round((d["wk52_high"]-d["price"])/d["wk52_high"]*100,1)}% below peak')
        print()
        t1, t2, t3 = d['lt_tier1'], d['lt_tier2'], d['lt_tier3']
        print(f'  Tier 1  ${t2:.2f} to ${t1:.2f}    (8-18% below peak -- first opportunity)')
        print(f'  Tier 2  ${t3:.2f} to ${t2:.2f}    (18-28% below peak -- good margin of safety)')
        print(f'  Tier 3  below ${t3:.2f}             (>28% below peak -- strong margin of safety)')
        print()
        tpe_s = f'{d["trailing_pe"]:.1f}x' if d["trailing_pe"] else 'N/A'
        fpe_s = f'{d["forward_pe"]:.1f}x'  if d["forward_pe"]  else 'N/A'
        peg_s = f'{d["peg"]:.2f}'          if d["peg"]          else 'N/A'
        print(f'  Trailing P/E  : {tpe_s}  |  Forward P/E : {fpe_s}  |  PEG : {peg_s}')
        ma200 = d['ma_200d']
        if ma200:
            print(f'  200-day MA    : ${ma200:.2f}  '
                  f'(price {"ABOVE" if d["price"] > ma200 else "BELOW"} long-term average)')

    # Decision
    if score >= 8:
        decision = 'BUY'
        verdict  = '✓  Strong entry -- conditions are in your favour'
    elif score >= 5:
        decision = 'WATCH'
        verdict  = '⟳  Not yet -- one or more key conditions are against you'
    else:
        decision = 'SKIP'
        verdict  = '✗  Do not buy -- too many conditions are unfavourable'

    print()
    print(DIVIDER2)
    print(f'  DECISION: {decision}   ({score} / {max_pts})   [{mode_label}]')
    print(f'  {verdict}')
    print(DIVIDER2)

    # Plain-English action plan
    print()
    print(DIVIDER)
    print('  WHAT TO DO NOW')
    print(DIVIDER)

    price = d['price']

    if mode == 'short':
        t1, t2, t3 = d['st_tier1'], d['st_tier2'], d['st_tier3']
        atr = d['atr']

        # How to buy
        if price > t1:
            print(f'\n  HOW TO BUY')
            print(f'  Do not buy yet. Price (${price:.2f}) is still too close to its recent high.')
            print(f'  Set a price alert at ${t1:.2f}. Only consider buying once it drops to that level.')
        elif price <= t3:
            print(f'\n  HOW TO BUY')
            print(f'  Price (${price:.2f}) has dropped significantly. You can buy your full planned amount now.')
            print(f'  This is a deep pullback -- risk/reward is in your favour for a short-term trade.')
        elif price <= t2:
            print(f'\n  HOW TO BUY')
            print(f'  Price (${price:.2f}) is at a moderate pullback. Buy half your planned amount now.')
            print(f'  Hold the other half and add more if it drops to ${t3:.2f} (deeper pullback).')
        else:
            print(f'\n  HOW TO BUY')
            print(f'  Price (${price:.2f}) is at a small pullback. Buy cautiously -- only a quarter of your planned amount.')
            print(f'  Add more at ${t2:.2f} and ${t3:.2f} if it continues to drop.')

        # How much
        pos = position_guide(d['beta'])
        print(f'\n  HOW MUCH TO BUY')
        print(f'  Limit this stock to {pos}.')
        print(f'  Example: if your total portfolio is $10,000 -- keep this position under that limit.')

        # Stop loss -- concrete dollar
        sl = round(price - 1.5 * atr, 2)
        tgt = round(price + 2.5 * atr, 2)
        print(f'\n  STOP LOSS (mandatory for short-term trades)')
        print(f'  If price falls to ${sl:.2f} -- exit immediately. Do not wait or hope for recovery.')
        print(f'  This level (1.5x daily ATR below entry) means the trade has gone wrong.')

        print(f'\n  PROFIT TARGET')
        print(f'  Consider selling if price reaches ${tgt:.2f}.')
        print(f'  That is 2.5x the average daily move above your entry -- a good short-term gain.')

        print(f'\n  MAXIMUM HOLD TIME')
        print(f'  Planned duration: {duration}.')
        print(f'  If the stock has not moved in your favour by then -- exit regardless of price.')

    else:
        t1, t2, t3 = d['lt_tier1'], d['lt_tier2'], d['lt_tier3']
        peak = d['wk52_high']
        pullback = round((peak - price) / peak * 100, 1)

        # How to buy
        print(f'\n  HOW TO BUY (split your budget, do not buy all at once)')
        if price > t1:
            print(f'  Do not buy yet. Price (${price:.2f}) is only {pullback}% below its high -- not enough discount.')
            print(f'  Set a price alert at ${t1:.2f}. That is the first level worth buying at.')
            print(f'  If it never drops that far and keeps going up, you simply miss this one -- that is fine.')
        elif price <= t3:
            print(f'  Price (${price:.2f}) is {pullback}% below its high -- a deep discount.')
            print(f'  Buy your full planned amount now, split across 2-3 purchases over the next few weeks.')
            print(f'  This is the best entry zone for a long-term position.')
        elif price <= t2:
            print(f'  Price (${price:.2f}) is {pullback}% below its high -- a solid entry point.')
            print(f'  Buy 2/3 of your planned amount now.')
            print(f'  Keep 1/3 in reserve. If it drops to ${t3:.2f}, buy the rest at a better price.')
        else:
            print(f'  Price (${price:.2f}) is {pullback}% below its high -- a reasonable but not ideal entry.')
            print(f'  Buy 1/3 of your planned amount now.')
            print(f'  Keep the rest and add at ${t2:.2f} and ${t3:.2f} if the price keeps falling.')

        # How much
        pos = position_guide(d['beta'])
        print(f'\n  HOW MUCH TO BUY')
        print(f'  Limit this stock to {pos}.')
        print(f'  Example: if your total portfolio is $10,000 -- keep this position under that limit.')

        # When to sell -- concrete, data-driven conditions (no "thesis" language)
        print(f'\n  WHEN TO SELL')
        print(f'  Sell if ANY of these become true:')
        rg = d['revenue_growth']
        if rg is not None:
            print(f'  - Revenue growth drops below 0% (currently {rg*100:.1f}% -- watch for decline)')
        else:
            print(f'  - Revenue stops growing for two consecutive quarters (check quarterly reports)')
        eps = d['eps']
        if eps is not None and eps > 0:
            print(f'  - The company starts reporting a loss (EPS is currently ${eps:.2f} -- if it goes negative, exit)')
        else:
            print(f'  - The company reports a loss in earnings')
        peg = d['peg']
        if peg is not None:
            print(f'  - PEG ratio rises above 3.0 (currently {peg:.2f} -- means stock has become overpriced for its growth)')
        else:
            print(f'  - Valuation becomes extreme (check PEG ratio in quarterly reports)')
        ma200 = d['ma_200d']
        if ma200:
            if price < ma200:
                print(f'  - Price does not recover above ${ma200:.2f} (200-day average) within 6 months')
            else:
                print(f'  - Price falls and stays below ${ma200:.2f} (200-day average) for more than 6 months')
        print(f'  - The company gets acquired, changes its core business, or faces a major legal/regulatory threat')

        # When to review
        print(f'\n  WHEN TO CHECK AGAIN')
        print(f'  Every 3 months -- after each quarterly earnings announcement.')
        print(f'  At each check, re-run this script and see if the score has changed.')
        print(f'  Planned holding period: {duration}.')

    # Contextual closing section -- different message depending on decision
    print()
    print(DIVIDER)

    if decision == 'BUY':
        print('  ALL CONDITIONS MET -- CHECKLIST BEFORE YOU BUY')
        print(DIVIDER)
        print('  Before placing the order, confirm:')
        print('  [ ] You have checked the date of the next earnings announcement')
        print('  [ ] You are not investing money you may need in the next 12 months')
        print('  [ ] You have set your position size limit (see HOW MUCH TO BUY above)')
        print('  [ ] You know your exit conditions (see WHEN TO SELL above)')

    elif decision == 'WATCH':
        # Show exactly what threshold each failing factor needs to hit
        missed = [label for label, s, m, _, status in factors
                  if s < m and status == '-']
        if missed:
            print('  WHY IT IS NOT A BUY YET -- AND WHAT NEEDS TO CHANGE')
            print(DIVIDER)
            print('  These specific conditions are currently failing:\n')
            for label in missed:
                if 'Revenue' in label:
                    rg = d['revenue_growth']
                    cur = f'{rg*100:.1f}%' if rg is not None else 'N/A'
                    print(f'  Revenue Growth       Currently: {cur}   →  Needs to be above +5% to pass')
                elif 'EPS' in label or 'Profit' in label:
                    eps = d['eps']
                    cur = f'${eps:.2f}' if eps is not None else 'N/A'
                    print(f'  Profitability (EPS)  Currently: {cur}   →  EPS needs to be above $0 to pass')
                elif 'Gross' in label or 'Margin' in label or 'Moat' in label:
                    gm = d['gross_margin']
                    cur = f'{gm*100:.0f}%' if gm is not None else 'N/A'
                    print(f'  Gross Margin         Currently: {cur}    →  Needs to be above 40% to pass')
                elif 'Earnings Growth' in label:
                    eg = d['earnings_growth']
                    cur = f'{eg*100:.1f}%' if eg is not None else 'N/A'
                    print(f'  Earnings Growth      Currently: {cur}   →  Profits need to be growing (above 0%) to pass')
                elif 'PEG' in label:
                    peg = d['peg']
                    cur = f'{peg:.2f}' if peg is not None else 'N/A'
                    print(f'  PEG Ratio            Currently: {cur}   →  Below 2.0 = 1pt, below 1.0 = 2pts (undervalued)')
                elif 'Trajectory' in label or 'Direction' in label:
                    fpe = d['forward_pe']; tpe = d['trailing_pe']
                    cur = f'Fwd {fpe:.1f}x vs Trail {tpe:.1f}x' if fpe and tpe else 'N/A'
                    print(f'  Earnings Trajectory  Currently: {cur}   →  Forward P/E needs to be lower than Trailing P/E')
                elif 'Volume' in label:
                    vr = d['vol_ratio']
                    print(f'  Volume Trend         Currently: {vr:.2f}x avg   →  Needs to be above 1.10x (buying activity picking up)')
                elif 'Price Zone' in label or 'Entry Zone' in label:
                    price_now = d['price']
                    peak = d['wk52_high']
                    pullback = round((peak - price_now) / peak * 100, 1)
                    if mode == 'long':
                        t1 = d['lt_tier1']
                        print(f'  Entry Zone           Currently: {pullback}% below 52wk high   →  Needs to drop to ${t1:.2f} (8% below peak) to score any points')
                    else:
                        t1 = d['st_tier1']
                        print(f'  Price Zone           Currently: ${price_now:.2f}   →  Needs to drop to ${t1:.2f} (Tier 1) to score any points')
                elif '200' in label or 'MA Trend' in label:
                    ma200 = d['ma_200d']
                    price_now = d['price']
                    cur = f'${price_now:.2f} vs MA ${ma200:.2f}' if ma200 else 'N/A'
                    print(f'  200-day MA Trend     Currently: {cur}   →  Price needs to rise above ${ma200:.2f} to pass')
            print()
            print('  Re-run this script in 3 months to check if conditions have improved.')

    else:  # SKIP
        pts_needed = 8 - score
        print('  WHY THIS IS A SKIP -- DO NOT BUY')
        print(DIVIDER)
        print(f'  This stock scored {score}/10. It needs {pts_needed} more points to reach BUY.')
        print()

        failed = [label for label, *_, status in factors if status == '-']
        for label in failed:
            if 'Revenue' in label:
                rg = d['revenue_growth']
                cur = f'{rg*100:.1f}%' if rg is not None else 'N/A'
                print(f'  Revenue is SHRINKING ({cur}). A healthy company grows revenue every year.')
                print(f'  This needs to be above +5% before this stock is worth considering.')
            elif 'EPS' in label or 'Profit' in label:
                eps = d['eps']
                cur = f'${eps:.2f}' if eps is not None else 'N/A'
                print(f'  Company is making a LOSS (EPS {cur}). Every share you hold loses money.')
                print(f'  EPS must turn positive before this becomes investable.')
            elif 'Gross' in label or 'Margin' in label or 'Moat' in label:
                gm = d['gross_margin']
                cur = f'{gm*100:.0f}%' if gm is not None else 'N/A'
                print(f'  Gross margin is only {cur}. After making its product, almost nothing is left.')
                print(f'  Needs to be above 40% -- low margin = no pricing power, no competitive edge.')
            elif 'PEG' in label:
                peg = d['peg']
                cur = f'{peg:.2f}' if peg is not None else 'N/A'
                print(f'  PEG ratio is {cur} -- meaning you are massively overpaying for the growth.')
                print(f'  A fair price would be PEG below 2.0. Below 1.0 would be undervalued.')
            elif 'Trajectory' in label or 'Direction' in label:
                fpe = d['forward_pe']; tpe = d['trailing_pe']
                if fpe and tpe:
                    print(f'  Earnings are EXPECTED TO SHRINK (Fwd P/E {fpe:.1f}x > Trail {tpe:.1f}x).')
                    print(f'  This means analysts expect the company to earn less next year than this year.')
            elif '200' in label or 'MA Trend' in label:
                ma200 = d['ma_200d']
                price_now = d['price']
                if ma200:
                    print(f'  Price (${price_now:.2f}) is BELOW the 200-day average (${ma200:.2f}).')
                    print(f'  This means long-term investors have been selling, not buying.')
            print()

        print('  BOTTOM LINE: These are structural business problems, not temporary dips.')
        print('  A stock being cheap is not a reason to buy if the business is broken.')
        print('  Come back when revenue is growing and the company is profitable.')

    print()
    print(f'  Scoring   : BUY 8-10 | WATCH 5-7 | SKIP 0-4')
    print(DIVIDER)


# ── MAIN ───────────────────────────────────────────────────────────────────────

def run():
    print()
    print(DIVIDER2)
    print('  AUTOMATED STOCK DECISION FRAMEWORK')
    print('  Short-term: ATR tiers  |  Long-term: 6-step Playbook + % pullback')
    print(DIVIDER2)
    print('  Type any stock ticker. Data fetched live from Yahoo Finance.')
    print('  Examples: AAPL  NVDA  TSM  IBM  VOO  BRK-B  ASML  PLTR')

    while True:
        print()
        ticker = input('  Enter ticker (or "q" to quit): ').strip().upper()
        if ticker in ('Q', 'QUIT', 'EXIT', ''):
            if ticker == '':
                continue
            print('\n  Goodbye.\n')
            break

        print(f'\n  Fetching data for {ticker}...')
        data, error = fetch(ticker)
        if error:
            print(f'\n  Error: {error}')
            continue

        mode, duration = ask_horizon()

        if mode == 'short':
            score, max_pts, factors = score_short(data)
        else:
            score, max_pts, factors = score_long(data)

        print_report(ticker, data, score, max_pts, factors, mode, duration)

        print()
        again = input('  Evaluate another stock? (y/n): ').strip().lower()
        if again != 'y':
            print('\n  Done. Run again: python3 stock_auto.py\n')
            break


if __name__ == '__main__':
    run()
