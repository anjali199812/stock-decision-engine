#!/usr/bin/env python3
"""
Stock Decision Web App
Run: python3 stock_web.py
Open: http://localhost:5000
"""

import os
from flask import Flask, request, jsonify

from stock_auto import (
    fetch, score_short, score_long,
    position_guide, wk52_label, fmt_cap
)

app = Flask(__name__)


# ── AUTO-THESIS GENERATOR ──────────────────────────────────────────────────────

def _auto_thesis(d, ticker):
    name   = d['name']
    sector = d['sector']
    rg     = d['revenue_growth']
    gm     = d['gross_margin']
    eps    = d['eps']
    peg    = d['peg']
    fpe    = d['forward_pe']
    tpe    = d['trailing_pe']
    price  = d['price']
    ma200  = d['ma_200d']

    chunks = []

    # Growth story
    if rg is not None:
        rp = rg * 100
        if rp >= 20:
            chunks.append(f'{name} is a high-growth {sector} company expanding revenue at +{rp:.0f}% per year.')
        elif rp >= 5:
            chunks.append(f'{name} is a steadily growing {sector} company with +{rp:.0f}% annual revenue growth.')
        elif rp >= 0:
            chunks.append(f'{name} is a mature {sector} company with flat revenue growth ({rp:.1f}%) — this is a stability, not growth, thesis.')
        else:
            chunks.append(f'{name} is a {sector} company with declining revenue ({rp:.1f}%) — the growth story is currently broken.')
    else:
        chunks.append(f'{name} operates in the {sector} sector.')

    # Profitability and margin
    if eps is not None and eps > 0:
        if gm is not None and gm >= 0.50:
            chunks.append(f'It is profitable (EPS ${eps:.2f}) with very high gross margins of {gm*100:.0f}%, suggesting a strong competitive moat and pricing power.')
        elif gm is not None and gm >= 0.35:
            chunks.append(f'It is profitable (EPS ${eps:.2f}) with solid gross margins of {gm*100:.0f}%.')
        else:
            chunks.append(f'It is profitable (EPS ${eps:.2f}).')
    elif eps is not None:
        chunks.append(f'It is currently loss-making (EPS ${eps:.2f}), so the thesis depends entirely on when — and whether — it reaches profitability.')

    # Valuation
    if peg is not None:
        if peg < 1.0:
            chunks.append(f'At a PEG ratio of {peg:.2f}, the stock looks undervalued relative to its growth — you are paying less than $1 for every $1 of expected earnings growth.')
        elif peg <= 2.0:
            chunks.append(f'At a PEG of {peg:.2f}, valuation is fair for the growth on offer.')
        else:
            chunks.append(f'At a PEG of {peg:.2f}, the stock is priced expensively — it needs to sustain strong growth just to justify the current price.')
    elif fpe and tpe:
        if fpe < tpe:
            chunks.append(f'Analysts project earnings improvement next year (Forward P/E {fpe:.1f}x vs Trailing {tpe:.1f}x), which supports the bull case.')
        else:
            chunks.append(f'Analysts project earnings to decline (Forward P/E {fpe:.1f}x > Trailing {tpe:.1f}x) — growth momentum may be slowing.')

    # Trend confirmation
    if ma200 and price:
        if price > ma200:
            chunks.append(f'The long-term trend supports this: price (${price:.2f}) is above the 200-day moving average (${ma200:.2f}).')
        else:
            chunks.append(f'One risk: the stock is below its 200-day moving average (${ma200:.2f}), meaning the long-term trend has not yet turned up — institutions may still be net sellers.')

    if not chunks:
        return f'Insufficient data to generate a thesis for {ticker.upper()}. Research the company\'s competitive position and growth drivers before investing.'

    return ' '.join(chunks)


# ── RESPONSE BUILDER ───────────────────────────────────────────────────────────

def build_response(ticker, d, score, max_pts, factors, mode, duration):
    if score >= 8:
        decision, verdict = 'BUY',   'Strong entry — conditions are in your favour'
    elif score >= 5:
        decision, verdict = 'WATCH', 'Not yet — one or more key conditions are against you'
    else:
        decision, verdict = 'SKIP',  'Do not buy — too many conditions are unfavourable'

    price  = d['price']
    thesis = _auto_thesis(d, ticker) if mode == 'long' else None

    # ── Factors
    factor_list = [
        {'label': label, 'scored': s, 'max': m, 'note': note, 'status': status}
        for label, s, m, note, status in factors
    ]

    if mode == 'long':
        pg       = position_guide(d['beta'])
        beta_str = f'{d["beta"]:.2f}' if d['beta'] else 'N/A'
        factor_list.insert(6, {
            'label': 'Your Thesis', 'scored': 0, 'max': 0,
            'note': thesis, 'status': 'info',
        })
        factor_list.insert(7, {
            'label': 'Position Size', 'scored': 0, 'max': 0,
            'note': f'Beta {beta_str} — {pg}.',
            'status': 'info',
        })

    # ── Tiers
    if mode == 'short':
        t1, t2, t3 = d['st_tier1'], d['st_tier2'], d['st_tier3']
        tiers = {
            'method':        'ATR-based (short-term)',
            'method_detail': f'14-day ATR = ${d["atr"]:.2f}  |  52-week high = ${d["wk52_high"]:.2f}',
            't1_range':  f'${t2:.2f} to ${t1:.2f}',
            't2_range':  f'${t3:.2f} to ${t2:.2f}',
            't3_range':  f'below ${t3:.2f}',
            't1_label':  '~1 ATR below peak — first support',
            't2_label':  '~2.5 ATR below peak — moderate pullback',
            't3_label':  '~5 ATR below peak — deep pullback',
            'momentum':  f'{d["momentum_pct"]:+.1f}%',
            'vol_ratio': f'{d["vol_ratio"]:.2f}x 20-day avg',
            'ma50':      f'${d["ma_50d"]:.2f}',
            'price_vs_ma50': 'ABOVE' if price > d['ma_50d'] else 'BELOW',
        }
    else:
        t1, t2, t3 = d['lt_tier1'], d['lt_tier2'], d['lt_tier3']
        pullback = round((d['wk52_high'] - price) / d['wk52_high'] * 100, 1)
        ma200    = d['ma_200d']
        tiers = {
            'method':        '% pullback from 52-week high (long-term)',
            'method_detail': f'52-week high = ${d["wk52_high"]:.2f}  |  Current pullback = {pullback}% below peak',
            't1_range':  f'${t2:.2f} to ${t1:.2f}',
            't2_range':  f'${t3:.2f} to ${t2:.2f}',
            't3_range':  f'below ${t3:.2f}',
            't1_label':  '8-18% below peak — first opportunity',
            't2_label':  '18-28% below peak — good margin of safety',
            't3_label':  '>28% below peak — strong margin of safety',
            'trailing_pe': f'{d["trailing_pe"]:.1f}x' if d['trailing_pe'] else 'N/A',
            'forward_pe':  f'{d["forward_pe"]:.1f}x'  if d['forward_pe']  else 'N/A',
            'peg':         f'{d["peg"]:.2f}'           if d['peg']         else 'N/A',
            'ma200':        f'${ma200:.2f}' if ma200 else None,
            'price_vs_ma200': ('ABOVE' if price > ma200 else 'BELOW') if ma200 else None,
        }

    # ── Action plan
    action = []
    if mode == 'short':
        t1v, t2v, t3v = d['st_tier1'], d['st_tier2'], d['st_tier3']
        atr = d['atr']
        if price > t1v:
            how = f'Do not buy yet. Price (${price:.2f}) is still too close to its recent high. Set a price alert at ${t1v:.2f}. Only consider buying once it drops to that level.'
        elif price <= t3v:
            how = f'Price (${price:.2f}) has dropped significantly. You can buy your full planned amount now. This is a deep pullback — risk/reward is in your favour for a short-term trade.'
        elif price <= t2v:
            how = f'Price (${price:.2f}) is at a moderate pullback. Buy half your planned amount now. Hold the other half and add more if it drops to ${t3v:.2f}.'
        else:
            how = f'Price (${price:.2f}) is at a small pullback. Buy cautiously — only a quarter of your planned amount. Add more at ${t2v:.2f} and ${t3v:.2f} if it drops further.'
        action.append({'heading': 'HOW TO BUY',          'text': how,  'cls': ''})
        action.append({'heading': 'HOW MUCH TO BUY',     'text': f'Limit this stock to {position_guide(d["beta"])}. Example: if your total portfolio is $10,000 — keep this position under that limit.', 'cls': 'size'})
        sl  = round(price - 1.5 * atr, 2)
        tgt = round(price + 2.5 * atr, 2)
        action.append({'heading': 'STOP LOSS (mandatory)', 'text': f'If price falls to ${sl:.2f} — exit immediately. Do not wait or hope for recovery. This level (1.5× daily ATR below entry) means the trade has gone wrong.', 'cls': 'stop'})
        action.append({'heading': 'PROFIT TARGET',         'text': f'Consider selling if price reaches ${tgt:.2f}. That is 2.5× the average daily move above your entry.', 'cls': 'target'})
        action.append({'heading': 'MAXIMUM HOLD TIME',     'text': f'Planned duration: {duration}. If the stock has not moved in your favour by then — exit regardless of price.', 'cls': ''})
    else:
        t1v, t2v, t3v = d['lt_tier1'], d['lt_tier2'], d['lt_tier3']
        peak     = d['wk52_high']
        pullback = round((peak - price) / peak * 100, 1)
        if price > t1v:
            how = f'Do not buy yet. Price (${price:.2f}) is only {pullback}% below its high — not enough discount. Set a price alert at ${t1v:.2f}. That is the first level worth buying at.'
        elif price <= t3v:
            how = f'Price (${price:.2f}) is {pullback}% below its high — a deep discount. Buy your full planned amount now, split across 2-3 purchases over the next few weeks.'
        elif price <= t2v:
            how = f'Price (${price:.2f}) is {pullback}% below its high — a solid entry. Buy 2/3 of your planned amount now. Keep 1/3 in reserve — add at ${t3v:.2f} if it drops further.'
        else:
            how = f'Price (${price:.2f}) is {pullback}% below its high — a reasonable but not ideal entry. Buy 1/3 now. Keep the rest and add at ${t2v:.2f} and ${t3v:.2f} if it keeps falling.'
        action.append({'heading': 'HOW TO BUY',      'text': how, 'cls': ''})
        action.append({'heading': 'HOW MUCH TO BUY', 'text': f'Limit this stock to {position_guide(d["beta"])}. Example: if your total portfolio is $10,000 — keep this position under that limit.', 'cls': 'size'})
        sell_pts = []
        rg = d['revenue_growth']
        sell_pts.append(f'Revenue growth drops below 0% (currently {rg*100:.1f}% — watch each quarter)' if rg is not None else 'Revenue stops growing for two consecutive quarters')
        eps = d['eps']
        if eps is not None and eps > 0:
            sell_pts.append(f'Company starts reporting a loss (EPS is currently ${eps:.2f} — if it goes negative, exit)')
        else:
            sell_pts.append('Company reports a loss in earnings')
        peg = d['peg']
        sell_pts.append(f'PEG ratio rises above 3.0 (currently {peg:.2f})' if peg else 'Valuation becomes extreme (check PEG each quarter)')
        ma200 = d['ma_200d']
        if ma200:
            sell_pts.append(f'Price {"does not recover above" if price < ma200 else "falls and stays below"} ${ma200:.2f} (200-day average) for more than 6 months')
        sell_pts.append('Company changes its core business or faces a major legal/regulatory threat')
        action.append({'heading': 'WHEN TO SELL',       'points': sell_pts, 'cls': 'stop'})
        action.append({'heading': 'WHEN TO CHECK AGAIN', 'text': f'Every 3 months — after each quarterly earnings announcement. Re-run this analysis and see if the score has changed. Planned holding period: {duration}.', 'cls': ''})

    # ── Closing
    def _factor_currently(label):
        if 'Revenue' in label:
            rg = d['revenue_growth']
            return f'{rg*100:.1f}%' if rg is not None else 'N/A'
        if 'EPS' in label or 'Profit' in label:
            eps = d['eps']
            return f'${eps:.2f}' if eps is not None else 'N/A'
        if 'Gross' in label or 'Margin' in label or 'Moat' in label:
            gm = d['gross_margin']
            return f'{gm*100:.0f}%' if gm is not None else 'N/A'
        if 'Earnings Growth' in label:
            eg = d['earnings_growth']
            return f'{eg*100:.1f}%' if eg is not None else 'N/A'
        if 'PEG' in label:
            peg = d['peg']
            return f'{peg:.2f}' if peg is not None else 'N/A'
        if 'Trajectory' in label or 'Direction' in label:
            fpe = d['forward_pe']; tpe = d['trailing_pe']
            return f'Fwd {fpe:.1f}x vs Trail {tpe:.1f}x' if fpe and tpe else 'N/A'
        if 'Volume' in label:
            return f'{d["vol_ratio"]:.2f}x avg'
        if 'Price Zone' in label or 'Entry Zone' in label:
            pb = round((d['wk52_high'] - price) / d['wk52_high'] * 100, 1)
            return f'{pb}% below 52wk high'
        if '200' in label or 'MA Trend' in label:
            ma200 = d['ma_200d']
            return f'${price:.2f} vs MA ${ma200:.2f}' if ma200 else 'N/A'
        return 'N/A'

    def _factor_needs(label):
        if 'Revenue' in label:           return 'above +5% to pass'
        if 'EPS' in label or 'Profit' in label: return 'EPS above $0 to pass'
        if 'Gross' in label or 'Margin' in label or 'Moat' in label: return 'above 40% to pass'
        if 'Earnings Growth' in label:   return 'above 0% (profits growing) to pass'
        if 'PEG' in label:               return 'below 2.0 for 1pt, below 1.0 for 2pts'
        if 'Trajectory' in label or 'Direction' in label: return 'Forward P/E must be lower than Trailing P/E'
        if 'Volume' in label:            return 'above 1.10x average (buying activity picking up)'
        if 'Price Zone' in label or 'Entry Zone' in label:
            ref = d['lt_tier1'] if mode == 'long' else d['st_tier1']
            return f'price to drop to ${ref:.2f} to score any points'
        if '200' in label or 'MA Trend' in label:
            ma200 = d['ma_200d']
            return f'price to rise above ${ma200:.2f}' if ma200 else 'price to rise above 200-day MA'
        return ''

    if decision == 'BUY':
        closing = {
            'type': 'buy',
            'title': 'ALL CONDITIONS MET — CHECKLIST BEFORE YOU BUY',
            'checklist': [
                'You have checked the date of the next earnings announcement',
                'You are not investing money you may need in the next 12 months',
                'You have set your position size limit (see HOW MUCH TO BUY above)',
                'You know your exit conditions (see WHEN TO SELL above)',
            ]
        }
    elif decision == 'WATCH':
        missed = [
            {'label': label, 'currently': _factor_currently(label), 'needs': _factor_needs(label)}
            for label, s, m, _, status in factors if s < m and status == '-'
        ]
        closing = {
            'type': 'watch',
            'title': 'WHY IT IS NOT A BUY YET — WHAT NEEDS TO CHANGE',
            'items': missed,
            'footer': 'Re-run this analysis in 3 months to check if conditions have improved.',
        }
    else:
        def _skip_reason(label):
            if 'Revenue' in label:
                rg = d['revenue_growth']
                cur = f'{rg*100:.1f}%' if rg is not None else 'N/A'
                return {'problem': f'Revenue is SHRINKING ({cur}). A healthy company grows revenue every year.', 'threshold': 'Needs to be above +5% before this stock is worth considering.'}
            if 'EPS' in label or 'Profit' in label:
                eps = d['eps']
                cur = f'${eps:.2f}' if eps is not None else 'N/A'
                return {'problem': f'Company is making a LOSS (EPS {cur}). Every share you hold loses money.', 'threshold': 'EPS must turn positive before this becomes investable.'}
            if 'Gross' in label or 'Margin' in label or 'Moat' in label:
                gm = d['gross_margin']
                cur = f'{gm*100:.0f}%' if gm is not None else 'N/A'
                return {'problem': f'Gross margin is only {cur}. After making its product, almost nothing is left.', 'threshold': 'Needs to be above 40% — low margin means no pricing power.'}
            if 'PEG' in label:
                peg = d['peg']
                cur = f'{peg:.2f}' if peg is not None else 'N/A'
                return {'problem': f'PEG ratio is {cur} — massively overpaying for the growth rate.', 'threshold': 'A fair price would be PEG below 2.0. Below 1.0 is undervalued.'}
            if 'Trajectory' in label or 'Direction' in label:
                fpe = d['forward_pe']; tpe = d['trailing_pe']
                if fpe and tpe:
                    return {'problem': f'Earnings are EXPECTED TO SHRINK (Fwd P/E {fpe:.1f}x > Trail {tpe:.1f}x).', 'threshold': 'Analysts expect the company to earn less next year than this year.'}
            if '200' in label or 'MA Trend' in label:
                ma200 = d['ma_200d']
                if ma200:
                    return {'problem': f'Price (${price:.2f}) is BELOW the 200-day average (${ma200:.2f}).', 'threshold': 'Long-term investors have been selling, not buying.'}
            return None

        reasons = [r for label, *_, status in factors if status == '-' for r in [_skip_reason(label)] if r]
        closing = {
            'type': 'skip',
            'title': 'WHY THIS IS A SKIP — DO NOT BUY',
            'score_context': f'Scored {score}/10. Needs {8 - score} more points to reach BUY.',
            'reasons': reasons,
            'bottom_line': 'These are structural business problems, not temporary dips. A stock being cheap is not a reason to buy if the business is broken. Come back when revenue is growing and the company is profitable.',
        }

    # ── Scoring guide
    if mode == 'long':
        scoring_guide = [
            {'section': 'STEP 1 — BUSINESS QUALITY', 'max': 4, 'items': [
                {'factor': 'Revenue Growth YoY', 'pts': '1pt', 'what': 'Is the company selling more each year?',              'pass': '>5% annual growth',          'fail': 'flat or declining'},
                {'factor': 'Profitability (EPS)', 'pts': '1pt', 'what': 'Is the company making money after all costs?',       'pass': 'EPS > $0',                   'fail': 'reporting a loss'},
                {'factor': 'Gross Margin',         'pts': '1pt', 'what': 'After making its product, how much profit remains?', 'pass': '>40% (competitive moat)',    'fail': 'low margin, no pricing power'},
                {'factor': 'Earnings Growth',      'pts': '1pt', 'what': 'Are profits growing year over year?',               'pass': 'positive earnings growth',   'fail': 'profits shrinking'},
            ]},
            {'section': 'STEP 2 — VALUATION', 'max': 3, 'items': [
                {'factor': 'PEG Ratio', 'pts': '2pt', 'what': 'Are you paying a fair price for the growth rate? (P/E ÷ growth rate)', 'pass': '<1.0 undervalued (2pts), 1–2 fair (1pt)', 'fail': '>2.0 expensive (0pts)'},
                {'factor': 'Earnings Trajectory', 'pts': '1pt', 'what': "Will next year's earnings be higher than this year's?", 'pass': 'Forward P/E < Trailing P/E', 'fail': 'Forward P/E > Trailing P/E'},
            ]},
            {'section': 'STEP 3 — YOUR THESIS', 'max': 0, 'info': 'The investment thesis — a data-driven summary of why this stock may be worth more in 3–5 years — is shown in full in the Factor Analysis section above, based on the stock\'s actual revenue growth, margins, profitability, and valuation.', 'items': []},
            {'section': 'STEP 4 — POSITION SIZING', 'max': 0, 'info': f'Based on beta {beta_str}, recommended allocation: {pg}. Higher beta means more volatile — size down to limit the damage if the position moves against you.', 'items': []},
            {'section': 'STEP 5 — ENTRY ZONE', 'max': 2, 'items': [
                {'factor': 'Entry Zone', 'pts': '2pt', 'what': 'How far is the price below its 52-week high?', 'pass': '>28% below peak = 2pts, 8–28% = 1pt', 'fail': '<8% below peak, near all-time high'},
            ]},
            {'section': 'STEP 6 — EXIT STRATEGY', 'max': 0, 'info': 'Know your exit before you enter. Your personalised exit conditions — based on this stock\'s actual numbers — are in the WHEN TO SELL section below. Review them after every quarterly earnings report. Never hold through a broken thesis.', 'items': []},
            {'section': 'TREND BONUS', 'max': 1, 'items': [
                {'factor': '200-day MA', 'pts': '1pt', 'what': 'Is the stock in a long-term uptrend or downtrend?', 'pass': 'Price above 200-day moving average', 'fail': 'Price below 200-day MA (institutions selling)'},
            ]},
        ]
    else:
        scoring_guide = [
            {'section': 'BUSINESS QUALITY', 'max': 3, 'items': [
                {'factor': 'Revenue Growth', 'pts': '1pt', 'what': 'Is the company growing revenue year over year?', 'pass': '>5% growth',    'fail': 'flat or declining'},
                {'factor': 'Profitability',  'pts': '1pt', 'what': 'Is the company profitable?',                    'pass': 'EPS > $0',        'fail': 'loss-making'},
                {'factor': 'Gross Margin',   'pts': '1pt', 'what': 'Does the company keep good profit per sale?',   'pass': '>40%',            'fail': 'low margin'},
            ]},
            {'section': 'VALUATION', 'max': 2, 'items': [
                {'factor': 'PEG Ratio',          'pts': '1pt', 'what': 'Is the stock priced reasonably vs its growth?',   'pass': 'PEG ≤ 2.0',                  'fail': '>2.0 overpriced'},
                {'factor': 'Earnings Direction',  'pts': '1pt', 'what': 'Are future earnings expected to be higher?',     'pass': 'Forward P/E < Trailing P/E', 'fail': 'earnings shrinking'},
            ]},
            {'section': 'ENTRY TIMING', 'max': 4, 'items': [
                {'factor': 'Price Zone (ATR)', 'pts': '3pt', 'what': 'Has stock pulled back enough? (14-day ATR method)', 'pass': '>5 ATR below high (3pts), 2.5–5 ATR (2pts), 1–2.5 ATR (1pt)', 'fail': 'Above Tier 1, too close to recent high'},
                {'factor': 'Volume Trend',     'pts': '1pt', 'what': 'Are more people buying than usual?',                'pass': '5-day avg > 110% of 20-day avg', 'fail': 'low or normal volume'},
            ]},
        ]

    dy = d['dividend_yield']
    dy_str = f'{dy*100:.2f}%' if dy and dy < 0.5 else (f'{dy:.2f}%' if dy else 'None')

    return {
        'ticker':        ticker.upper(),
        'name':          d['name'],
        'sector':        d['sector'],
        'market_cap':    fmt_cap(d['market_cap']),
        'price':         d['price'],
        'wk52_low':      d['wk52_low'],
        'wk52_high':     d['wk52_high'],
        'wk52_position': wk52_label(d['price'], d['wk52_low'], d['wk52_high']),
        'beta':          f'{d["beta"]:.2f}' if d['beta'] else 'N/A',
        'dividend_yield': dy_str,
        'holding_plan':  duration,
        'mode':          mode,
        'mode_label':    'SHORT-TERM TRADING' if mode == 'short' else 'LONG-TERM INVESTING',
        'score':         score,
        'max_pts':       max_pts,
        'decision':      decision,
        'verdict':       verdict,
        'factors':       factor_list,
        'tiers':         tiers,
        'action':        action,
        'closing':       closing,
        'scoring_guide': scoring_guide,
    }


# ── ROUTES ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return HTML_PAGE

@app.route('/analyze', methods=['POST'])
def analyze():
    body    = request.get_json(silent=True) or {}
    ticker  = body.get('ticker', '').strip().upper()
    mode    = body.get('mode', 'long')
    duration = body.get('duration', '')
    if not ticker:
        return jsonify({'error': 'Please enter a ticker symbol.'}), 400
    data, error = fetch(ticker)
    if error:
        return jsonify({'error': error}), 400
    score_fn = score_short if mode == 'short' else score_long
    score, max_pts, factors = score_fn(data)
    return jsonify(build_response(ticker, data, score, max_pts, factors, mode, duration))


# ── HTML PAGE ──────────────────────────────────────────────────────────────────

HTML_PAGE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stock Decision Engine</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d1117;--surf:#161b22;--surf2:#21262d;--border:#30363d;
  --text:#e6edf3;--muted:#8b949e;--dim:#6e7681;
  --green:#3fb950;--green-bg:rgba(63,185,80,.13);
  --amber:#d29922;--amber-bg:rgba(210,153,34,.13);
  --red:#f85149;  --red-bg:rgba(248,81,73,.13);
  --blue:#388bfd; --blue-bg:rgba(56,139,253,.13);
  --r:10px;
}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;font-size:14px;line-height:1.6;min-height:100vh}
.wrap{max-width:880px;margin:0 auto;padding:24px 16px 80px}

/* header */
.site-header{text-align:center;padding:44px 0 32px}
.site-header h1{font-size:1.9rem;font-weight:800;letter-spacing:-.5px}
.site-header h1 em{color:var(--blue);font-style:normal}
.site-header p{color:var(--muted);margin-top:6px;font-size:13px}

/* card */
.card{background:var(--surf);border:1px solid var(--border);border-radius:var(--r);padding:22px;margin-bottom:16px}

/* input */
.input-card{padding:28px}
.input-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;font-weight:700;margin-bottom:18px;display:block}
.ticker-row{display:flex;gap:10px;margin-bottom:16px}
.ticker-input{flex:1;background:var(--surf2);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:18px;font-weight:700;padding:12px 16px;text-transform:uppercase;letter-spacing:1px;outline:none;transition:border-color .2s}
.ticker-input::placeholder{font-size:13px;font-weight:400;letter-spacing:0;color:var(--dim);text-transform:none}
.ticker-input:focus{border-color:var(--blue)}
.go-btn{background:var(--blue);border:none;border-radius:8px;color:#fff;cursor:pointer;font-size:14px;font-weight:700;padding:12px 26px;transition:opacity .2s,transform .1s;white-space:nowrap}
.go-btn:hover{opacity:.88}
.go-btn:active{transform:scale(.97)}
.go-btn:disabled{opacity:.45;cursor:default}

.mode-row{display:flex;margin-bottom:14px}
.mode-btn{flex:1;background:var(--surf2);border:1px solid var(--border);color:var(--muted);cursor:pointer;font-size:13px;font-weight:500;padding:10px;transition:all .2s}
.mode-btn:first-child{border-radius:8px 0 0 8px}
.mode-btn:last-child{border-radius:0 8px 8px 0;border-left:none}
.mode-btn.active{background:var(--blue-bg);border-color:var(--blue);color:var(--blue);font-weight:700}

.dur-select{width:100%;background:var(--surf2);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;padding:10px 14px;outline:none;cursor:pointer}
.dur-select:focus{border-color:var(--blue)}

/* error / loading */
.error-box{background:var(--red-bg);border:1px solid var(--red);border-radius:var(--r);color:var(--red);padding:14px 18px;margin-bottom:16px;display:none;font-size:13px}
.loading{text-align:center;padding:44px;color:var(--muted);display:none}
.spin{display:inline-block;width:28px;height:28px;border:3px solid var(--border);border-top-color:var(--blue);border-radius:50%;animation:spin .7s linear infinite;margin-bottom:10px}
@keyframes spin{to{transform:rotate(360deg)}}

/* results fade-in */
#results{display:none;animation:fi .35s ease}
@keyframes fi{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}

/* stock header */
.price-header{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px}
.stock-name{font-size:20px;font-weight:800}
.stock-sub{font-size:12px;color:var(--muted);margin-top:3px}
.price-big{font-size:30px;font-weight:800;text-align:right;font-variant-numeric:tabular-nums}
.price-range{font-size:11px;color:var(--muted);text-align:right;margin-top:2px}
.mode-chip{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.4px;text-transform:uppercase;padding:2px 8px;border-radius:4px;margin-left:6px;vertical-align:middle}
.mode-chip.short{background:var(--amber-bg);color:var(--amber)}
.mode-chip.long{background:var(--blue-bg);color:var(--blue)}
.range-wrap{margin-top:14px}
.range-lbl{display:flex;justify-content:space-between;font-size:10px;color:var(--dim);margin-bottom:4px}
.range-track{background:var(--surf2);border-radius:4px;height:7px;position:relative;overflow:visible}
.range-fill{background:linear-gradient(90deg,var(--red),var(--amber) 50%,var(--green));height:100%;border-radius:4px}
.range-dot{position:absolute;top:50%;transform:translate(-50%,-50%);width:13px;height:13px;background:var(--text);border:2px solid var(--bg);border-radius:50%;box-shadow:0 0 0 2px var(--blue)}
.meta-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px}
.meta-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px}
.meta-val{font-size:13px;font-weight:600}

/* decision */
.decision-card{text-align:center;padding:32px 20px}
.badge{display:inline-block;font-size:40px;font-weight:900;letter-spacing:2px;padding:8px 44px;border-radius:12px;margin-bottom:10px}
.badge.BUY  {background:var(--green-bg);color:var(--green);border:2px solid var(--green)}
.badge.WATCH{background:var(--amber-bg);color:var(--amber);border:2px solid var(--amber)}
.badge.SKIP {background:var(--red-bg);  color:var(--red);  border:2px solid var(--red)}
.score-line{font-size:17px;font-weight:600;margin-bottom:5px}
.score-line b{font-size:26px}
.verdict{color:var(--muted);font-size:13px;margin-bottom:20px}
.bar-outer{background:var(--surf2);border-radius:8px;height:12px;max-width:420px;margin:0 auto 6px;overflow:hidden}
.bar-inner{height:100%;border-radius:8px;width:0;transition:width 1s cubic-bezier(.4,0,.2,1)}
.bar-inner.BUY  {background:linear-gradient(90deg,#3fb950,#57e872)}
.bar-inner.WATCH{background:linear-gradient(90deg,#d29922,#f0b429)}
.bar-inner.SKIP {background:linear-gradient(90deg,#f85149,#ff7875)}
.bar-markers{display:flex;justify-content:space-between;max-width:420px;margin:0 auto;font-size:10px;color:var(--dim)}

/* accordion */
.acc{border:1px solid var(--border);border-radius:var(--r);overflow:hidden;margin-bottom:16px}
.acc-head{background:var(--surf);padding:14px 18px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;font-weight:700;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;user-select:none;transition:color .2s}
.acc-head:hover{color:var(--text)}
.acc-arrow{transition:transform .25s;font-size:10px}
.acc.open .acc-arrow{transform:rotate(180deg)}
.acc-body{display:none;background:var(--surf);border-top:1px solid var(--border);padding:18px}
.acc.open .acc-body{display:block}
.g-section{margin-bottom:18px}
.g-section:last-child{margin-bottom:0}
.g-sec-title{font-size:10px;color:var(--blue);text-transform:uppercase;letter-spacing:1px;font-weight:800;margin-bottom:10px;display:flex;align-items:center;gap:8px}
.g-pts{background:var(--blue-bg);color:var(--blue);border-radius:4px;padding:1px 7px;font-size:10px}
.g-row{display:grid;grid-template-columns:150px 1fr;gap:10px;margin-bottom:8px;font-size:12px}
.g-fac{font-weight:600}
.g-detail{color:var(--muted)}
.g-pass{color:var(--green)}
.g-fail{color:var(--red)}
.g-info{font-size:12px;color:var(--muted);line-height:1.65;padding:6px 0 2px}

/* factors */
.sec-title{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;font-weight:700;margin-bottom:14px}
.f-sec-hdr{font-size:12px;font-weight:800;color:var(--blue);text-transform:uppercase;letter-spacing:.4px;margin:16px 0 8px;padding-bottom:6px;border-bottom:1px solid var(--border)}
.f-sec-hdr:first-child{margin-top:0}
.f-row{display:grid;grid-template-columns:26px 1fr 70px;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)}
.f-row:last-child{border-bottom:none}
.f-icon{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;flex-shrink:0}
.f-icon.pass{background:var(--green-bg);color:var(--green)}
.f-icon.fail{background:var(--red-bg);color:var(--red)}
.f-icon.watch{background:var(--amber-bg);color:var(--amber)}
.f-icon.na{background:var(--surf2);color:var(--dim)}
.f-icon.info{background:var(--blue-bg);color:var(--blue);font-style:italic;font-size:13px}
.f-body{min-width:0}
.f-label{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.f-note{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}
.f-score{text-align:right}
.f-num{font-size:13px;font-weight:800;font-variant-numeric:tabular-nums}
.f-num.pass{color:var(--green)}.f-num.fail{color:var(--red)}.f-num.watch{color:var(--amber)}.f-num.na{color:var(--dim)}
.mini{height:4px;background:var(--surf2);border-radius:2px;margin-top:5px;overflow:hidden}
.mini-fill{height:100%;border-radius:2px}
.mini-fill.pass{background:var(--green)}.mini-fill.fail{background:var(--red)}.mini-fill.watch{background:var(--amber)}

/* tiers */
.tier-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:14px}
.tier-card{background:var(--surf2);border:1px solid var(--border);border-radius:8px;padding:16px;text-align:center;position:relative}
.tier-card.here{border-color:var(--green);background:var(--green-bg)}
.tier-card.above{border-color:var(--border)}
.t-badge{position:absolute;top:-9px;left:50%;transform:translateX(-50%);background:var(--dim);color:var(--bg);font-size:9px;font-weight:800;padding:2px 9px;border-radius:10px;white-space:nowrap}
.tier-card.here .t-badge{background:var(--green)}
.t-price{font-size:14px;font-weight:800;margin-top:6px}
.t-label{font-size:10px;color:var(--muted);margin-top:4px;line-height:1.4}
.tier-meta{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:16px;padding-top:14px;border-top:1px solid var(--border);font-size:12px}
.tm-lbl{font-size:10px;color:var(--muted);margin-bottom:2px}
.tm-val{font-weight:700}

/* action */
.action-item{background:var(--surf2);border-radius:8px;padding:16px;margin-bottom:10px;border-left:3px solid var(--blue)}
.action-item:last-child{margin-bottom:0}
.action-item.stop{border-left-color:var(--red)}
.action-item.target{border-left-color:var(--green)}
.action-item.size{border-left-color:var(--amber)}
.a-head{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.6px;color:var(--blue);margin-bottom:7px}
.action-item.stop .a-head{color:var(--red)}
.action-item.target .a-head{color:var(--green)}
.action-item.size .a-head{color:var(--amber)}
.a-text{font-size:13px;line-height:1.7}
.a-list{list-style:none;margin-top:4px}
.a-list li{font-size:13px;padding:4px 0 4px 18px;position:relative;line-height:1.6}
.a-list li::before{content:'→';position:absolute;left:0;color:var(--muted)}

/* closing */
.check-list{list-style:none}
.check-list li{display:flex;align-items:flex-start;gap:10px;padding:9px 0;border-bottom:1px solid var(--border);font-size:13px}
.check-list li:last-child{border-bottom:none}
.check-box{width:18px;height:18px;border:2px solid var(--green);border-radius:4px;flex-shrink:0;margin-top:1px}
.watch-tbl{width:100%;border-collapse:collapse;font-size:12px}
.watch-tbl th{text-align:left;color:var(--muted);font-size:10px;text-transform:uppercase;padding:6px 8px;border-bottom:1px solid var(--border)}
.watch-tbl td{padding:10px 8px;border-bottom:1px solid var(--border);vertical-align:top}
.watch-tbl tr:last-child td{border-bottom:none}
.cur{color:var(--red);font-weight:700}
.nds{color:var(--green)}
.arr{color:var(--muted);font-size:16px}
.skip-card{background:var(--red-bg);border:1px solid rgba(248,81,73,.3);border-radius:8px;padding:14px;margin-bottom:10px}
.skip-card:last-child{margin-bottom:0}
.skip-prob{font-size:13px;font-weight:700;color:var(--red);margin-bottom:4px}
.skip-thresh{font-size:12px;color:var(--muted)}
.bottom-line{background:var(--surf2);border-left:3px solid var(--red);border-radius:0 8px 8px 0;padding:14px 16px;margin-top:14px;font-size:13px;line-height:1.7}

/* responsive */
@media(max-width:620px){
  .tier-grid{grid-template-columns:1fr}
  .meta-grid{grid-template-columns:1fr 1fr}
  .tier-meta{grid-template-columns:1fr 1fr}
  .price-header{flex-direction:column}
  .price-big,.price-range{text-align:left}
  .g-row{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div class="wrap">
  <header class="site-header">
    <h1>Stock <em>Decision</em> Engine</h1>
    <p>Enter any ticker. Get an instant BUY / WATCH / SKIP with full reasoning — no guesswork.</p>
  </header>

  <div class="card input-card">
    <span class="input-label">Analyze a Stock</span>
    <div class="ticker-row">
      <input class="ticker-input" id="ticker" type="text" placeholder="Ticker — e.g. AAPL, NVDA, TSM, VOO" autocomplete="off" autocorrect="off" spellcheck="false">
      <button class="go-btn" id="goBtn" onclick="analyze()">Analyze →</button>
    </div>
    <div class="mode-row">
      <button class="mode-btn active" id="btn-long"  onclick="setMode('long')">📈&nbsp; Long-term Investing</button>
      <button class="mode-btn"        id="btn-short" onclick="setMode('short')">⚡&nbsp; Short-term Trading</button>
    </div>
    <select class="dur-select" id="duration"></select>
  </div>

  <div class="error-box" id="errBox"></div>
  <div class="loading" id="loading"><div class="spin"></div><br>Fetching live data from Yahoo Finance…</div>
  <div id="results"></div>
</div>

<script>
let mode = 'long';
const DURS = {
  long:  ['6 months to 1 year','1 to 3 years','3 to 5 years','5 years or more'],
  short: ['1 to 4 weeks','1 to 3 months','3 to 6 months'],
};
function setMode(m){
  mode = m;
  ['long','short'].forEach(x => document.getElementById('btn-'+x).classList.toggle('active', x===m));
  const s = document.getElementById('duration');
  s.innerHTML = DURS[m].map(d=>`<option>${d}</option>`).join('');
}
setMode('long');
document.getElementById('ticker').addEventListener('keydown', e => { if(e.key==='Enter') analyze(); });

async function analyze(){
  const ticker = document.getElementById('ticker').value.trim().toUpperCase();
  const duration = document.getElementById('duration').value;
  if(!ticker){ showErr('Please enter a ticker symbol.'); return; }
  hideErr();
  show('loading', true); show('results', false);
  document.getElementById('goBtn').disabled = true;
  try{
    const r = await fetch('/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker,mode,duration})});
    const d = await r.json();
    if(!r.ok){ showErr(d.error||'Something went wrong.'); return; }
    render(d);
  } catch(e){ showErr('Could not connect. Make sure stock_web.py is running.'); }
  finally{ show('loading',false); document.getElementById('goBtn').disabled=false; }
}

function showErr(m){ const b=document.getElementById('errBox'); b.textContent=m; b.style.display='block'; }
function hideErr(){ document.getElementById('errBox').style.display='none'; }
function show(id,v){ document.getElementById(id).style.display=v?'block':'none'; }
function sc(s){ return s==='+'?'pass':s==='-'?'fail':s==='~'?'watch':s==='info'?'info':'na'; }
function icon(s){ return s==='+'?'✓':s==='-'?'✗':s==='~'?'~':s==='info'?'i':'?'; }
function pct(p,l,h){ return h===l?50:Math.round((p-l)/(h-l)*100); }

function parseBounds(r){
  if(r.startsWith('below')){ return {lo:-Infinity,hi:parseFloat(r.replace('below $',''))}; }
  const p=r.split(' to '); return {lo:parseFloat(p[0].replace('$','')),hi:parseFloat(p[1].replace('$',''))};
}

function render(d){
  const R = document.getElementById('results');
  R.innerHTML = '';

  // ── Stock Header
  const pos = pct(d.price, d.wk52_low, d.wk52_high);
  R.innerHTML += `<div class="card">
    <div class="price-header">
      <div><div class="stock-name">${d.name}</div>
        <div class="stock-sub">${d.ticker} &nbsp;·&nbsp; ${d.sector} &nbsp;·&nbsp; ${d.market_cap}
          <span class="mode-chip ${d.mode}">${d.mode_label}</span></div></div>
      <div><div class="price-big">$${d.price.toFixed(2)}</div>
        <div class="price-range">52wk $${d.wk52_low.toFixed(2)} — $${d.wk52_high.toFixed(2)}</div></div>
    </div>
    <div class="range-wrap">
      <div class="range-lbl"><span>52wk Low</span><span>52wk High</span></div>
      <div class="range-track">
        <div class="range-fill" style="width:100%"></div>
        <div class="range-dot" style="left:${pos}%"></div>
      </div>
    </div>
    <div class="meta-grid">
      <div><div class="meta-lbl">Beta</div><div class="meta-val">${d.beta}</div></div>
      <div><div class="meta-lbl">Dividend</div><div class="meta-val">${d.dividend_yield}</div></div>
      <div><div class="meta-lbl">Holding Plan</div><div class="meta-val">${d.holding_plan}</div></div>
      <div><div class="meta-lbl">52wk Position</div><div class="meta-val">${d.wk52_position.split('--')[0].trim()}</div></div>
    </div>
  </div>`;

  // ── Decision
  const sp = Math.round(d.score/d.max_pts*100);
  R.innerHTML += `<div class="card decision-card">
    <div class="badge ${d.decision}">${d.decision}</div>
    <div class="score-line"><b>${d.score}</b> / ${d.max_pts} points</div>
    <div class="verdict">${d.verdict}</div>
    <div class="bar-outer"><div class="bar-inner ${d.decision}" id="sbar" style="width:0%"></div></div>
    <div class="bar-markers"><span>0</span><span style="color:var(--red)">SKIP &lt;5</span><span style="color:var(--amber)">WATCH 5-7</span><span style="color:var(--green)">BUY 8+</span><span>10</span></div>
  </div>`;
  setTimeout(()=>{ const b=document.getElementById('sbar'); if(b) b.style.width=sp+'%'; },80);

  // ── Scoring Guide
  let gHTML = '';
  d.scoring_guide.forEach(sec=>{
    const ptsLabel = sec.max > 0 ? `${sec.max} pts max` : 'action step';
    gHTML += `<div class="g-section"><div class="g-sec-title">${sec.section}<span class="g-pts">${ptsLabel}</span></div>`;
    if (sec.info) {
      gHTML += `<div class="g-info">${sec.info}</div>`;
    }
    sec.items.forEach(it=>{
      gHTML += `<div class="g-row"><div class="g-fac">${it.factor} <span style="color:var(--dim);font-size:10px">(${it.pts})</span></div>
        <div class="g-detail">${it.what}<br><span class="g-pass">✓ ${it.pass}</span>&ensp;<span class="g-fail">✗ ${it.fail}</span></div></div>`;
    });
    gHTML += '</div>';
  });
  R.innerHTML += `<div class="acc" id="guideAcc">
    <div class="acc-head" onclick="this.parentElement.classList.toggle('open')">
      Scoring Guide — what each factor means and how points are awarded
      <span class="acc-arrow">▼</span>
    </div>
    <div class="acc-body">${gHTML}</div>
  </div>`;

  // ── Factor Analysis
  const HDRS = d.mode==='long'
    ? {0:'STEP 1 — Business Quality (4 pts)',4:'STEP 2 — Valuation (3 pts)',6:'STEP 3 — Your Thesis',7:'STEP 4 — Position Sizing',8:'STEP 5 — Entry Zone (2 pts)',9:'Trend Bonus (1 pt)'}
    : {0:'Business Quality (3 pts)',3:'Valuation (2 pts)',5:'Entry Timing (4 pts)'};
  let fHTML = '';
  d.factors.forEach((f,i)=>{
    if(HDRS[i]) fHTML += `<div class="f-sec-hdr">${HDRS[i]}</div>`;
    const s=sc(f.status), ic=icon(f.status);
    if(f.status==='info'){
      fHTML += `<div class="f-row" style="grid-template-columns:26px 1fr;align-items:start;padding:10px 0">
        <div class="f-icon info" style="margin-top:2px">${ic}</div>
        <div class="f-body"><div class="f-note" style="white-space:normal;overflow:visible;text-overflow:clip;line-height:1.65;color:var(--muted)">${f.note}</div></div>
      </div>`;
    } else {
      const fp=f.max>0?Math.round(f.scored/f.max*100):0;
      fHTML += `<div class="f-row">
        <div class="f-icon ${s}">${ic}</div>
        <div class="f-body"><div class="f-label">${f.label}</div><div class="f-note">${f.note}</div></div>
        <div class="f-score"><div class="f-num ${s}">${f.scored}/${f.max}</div>
          <div class="mini"><div class="mini-fill ${s}" style="width:${fp}%"></div></div></div>
      </div>`;
    }
  });
  R.innerHTML += `<div class="card"><div class="sec-title">Factor Analysis</div>${fHTML}</div>`;

  // ── Buy Limit Tiers
  const t=d.tiers, pr=d.price;
  const b1=parseBounds(t.t1_range),b2=parseBounds(t.t2_range),b3=parseBounds(t.t3_range);
  const inT1=pr>=b1.lo&&pr<=b1.hi, inT2=pr>=b2.lo&&pr<=b2.hi, inT3=pr<=b3.hi&&!inT1&&!inT2;
  const aboveAll=!inT1&&!inT2&&!inT3;

  function tierCard(range,label,idx,isHere){
    const label2=isHere?`Tier ${idx} ← You are here`:`Tier ${idx}`;
    return `<div class="tier-card ${isHere?'here':''}">
      <span class="t-badge">${label2}</span>
      <div class="t-price">${range}</div>
      <div class="t-label">${label}</div>
    </div>`;
  }

  let tierMeta='';
  if(d.mode==='short'){
    tierMeta=`<div class="tier-meta">
      <div><div class="tm-lbl">4-wk Momentum</div><div class="tm-val">${t.momentum}</div></div>
      <div><div class="tm-lbl">Volume</div><div class="tm-val">${t.vol_ratio}</div></div>
      <div><div class="tm-lbl">50-day MA</div><div class="tm-val">${t.ma50}</div></div>
      <div><div class="tm-lbl">Price vs MA50</div><div class="tm-val">${t.price_vs_ma50}</div></div>
    </div>`;
  } else {
    tierMeta=`<div class="tier-meta">
      <div><div class="tm-lbl">Trailing P/E</div><div class="tm-val">${t.trailing_pe}</div></div>
      <div><div class="tm-lbl">Forward P/E</div><div class="tm-val">${t.forward_pe}</div></div>
      <div><div class="tm-lbl">PEG Ratio</div><div class="tm-val">${t.peg}</div></div>
      ${t.ma200?`<div><div class="tm-lbl">200-day MA</div><div class="tm-val">${t.ma200} (${t.price_vs_ma200})</div></div>`:''}
    </div>`;
  }

  R.innerHTML += `<div class="card">
    <div class="sec-title">Buy Limit Tiers — ${t.method}</div>
    <div style="font-size:11px;color:var(--muted);margin-bottom:4px">${t.method_detail}</div>
    ${aboveAll?`<div style="background:var(--amber-bg);border:1px solid var(--amber);border-radius:6px;padding:10px 14px;font-size:12px;color:var(--amber);margin-bottom:12px">Current price is above all tiers — wait for a pullback before buying.</div>`:''}
    <div class="tier-grid">
      ${tierCard(t.t1_range,t.t1_label,1,inT1)}
      ${tierCard(t.t2_range,t.t2_label,2,inT2)}
      ${tierCard(t.t3_range,t.t3_label,3,inT3)}
    </div>
    ${tierMeta}
  </div>`;

  // ── Action Plan
  let aHTML = '';
  d.action.forEach(a=>{
    const body = a.points
      ? `<ul class="a-list">${a.points.map(p=>`<li>${p}</li>`).join('')}</ul>`
      : `<div class="a-text">${a.text}</div>`;
    aHTML += `<div class="action-item ${a.cls||''}"><div class="a-head">${a.heading}</div>${body}</div>`;
  });
  R.innerHTML += `<div class="card"><div class="sec-title">What to Do Now</div>${aHTML}</div>`;

  // ── Closing
  const c=d.closing;
  let cHTML='';
  if(c.type==='buy'){
    cHTML=`<ul class="check-list">${c.checklist.map(x=>`<li><div class="check-box"></div>${x}</li>`).join('')}</ul>`;
  } else if(c.type==='watch' && c.items && c.items.length){
    cHTML=`<table class="watch-tbl"><thead><tr><th>Factor</th><th>Currently</th><th></th><th>Needs to be</th></tr></thead><tbody>
      ${c.items.map(it=>`<tr><td><strong>${it.label}</strong></td><td class="cur">${it.currently}</td><td class="arr">→</td><td class="nds">${it.needs}</td></tr>`).join('')}
    </tbody></table><div style="margin-top:12px;font-size:12px;color:var(--muted)">${c.footer}</div>`;
  } else if(c.type==='skip'){
    cHTML=`<div style="font-size:12px;color:var(--muted);margin-bottom:14px">${c.score_context}</div>
    ${(c.reasons||[]).map(r=>`<div class="skip-card"><div class="skip-prob">${r.problem}</div><div class="skip-thresh">${r.threshold}</div></div>`).join('')}
    ${c.bottom_line?`<div class="bottom-line">${c.bottom_line}</div>`:''}`;
  }

  if(cHTML){
    const bc = c.type==='buy'?'var(--green)':c.type==='watch'?'var(--amber)':'var(--red)';
    R.innerHTML += `<div class="card" style="border-color:${bc}"><div class="sec-title">${c.title}</div>${cHTML}</div>`;
  }

  show('results', true);
}
</script>
</body>
</html>'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=False, port=port, host='0.0.0.0')
