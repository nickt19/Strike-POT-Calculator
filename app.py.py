import streamlit as st
import yfinance as yf
import numpy as np
from scipy.stats import norm

# ----------------------------
# FUNCTIONS
# ----------------------------
def black_scholes_delta(S, K, T, r, sigma, option_type='call'):
    """Calculate the Black-Scholes delta for a call or put."""
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    if option_type == 'call':
        return norm.cdf(d1)
    else:
        return norm.cdf(d1) - 1

def pot_from_delta(S, K, T, r, sigma, option_type='call'):
    """Approximate Probability of Touch as 2 × |Delta| (capped at 100%)."""
    delta = black_scholes_delta(S, K, T, r, sigma, option_type)
    return min(1, abs(delta) * 2)

def calculate_expected_move(S, iv, T):
    """Calculate the +/- expected move based on IV and Time to Expiration."""
    if T <= 0 or iv <= 0:
        return 0.0
    return S * iv * np.sqrt(T)

# ----------------------------
# CACHED DATA FETCHING
# ----------------------------
@st.cache_data(ttl=300)  # Saves data locally for 5 minutes to prevent API rate limiting
def get_options_data(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)

    # Try fetching via fast_info first for better reliability, fall back to info
    try:
        S = ticker.fast_info['lastPrice']
    except:
        S = ticker.info.get('regularMarketPrice', None)

    if S is None:
        return None, None, None, None

    # Find the next available expiration date
    expirations = ticker.options
    if not expirations:
        return S, None, None, None

    expiration_date = expirations[0]

    # Pull the option chain for that date
    opt_chain = ticker.option_chain(expiration_date)
    return S, expiration_date, opt_chain.calls, opt_chain.puts

# ----------------------------
# STREAMLIT UI
# ----------------------------

st.title("Options Strategy & Probability of Touch Dashboard")
st.markdown("Estimates the expected move and probability that your strikes will be touched before expiration.")

# Sidebar Inputs
st.sidebar.header("Settings")
ticker_symbol = st.sidebar.text_input("Ticker Symbol", "^SPX")

# Strategy Selector
strategy = st.sidebar.selectbox(
    "Select Strategy",
    ["Iron Condor", "Put Spread", "Call Spread"]
)

pct_OTM_input = st.sidebar.number_input("Target OTM % (Enter as whole number, e.g. 1.50 for 1.5%)", value=2.00, step=0.25, format="%.2f")
pct_OTM = pct_OTM_input / 100.0
days_to_expiration = st.sidebar.number_input("Days to Expiration", value=2, step=1)
risk_free_rate = st.sidebar.number_input("Risk-Free Rate (decimal)", value=0.05, step=0.01)

st.sidebar.markdown("---")
st.sidebar.write("Change inputs and the calculator updates instantly.")

# ----------------------------
# MAIN EXECUTION LOGIC
# ----------------------------
try:
    # Use cached data fetch function
    S, expiration_date, calls, puts = get_options_data(ticker_symbol)

    if S is None:
        st.error("⚠️ Could not fetch live price for this ticker.")
        st.stop()

    if expiration_date is None:
        st.error("⚠️ No options data found for this ticker.")
        st.stop()

    T = days_to_expiration / 365.0

    # 1. Target Strikes & IV Fetching
    # --- Put Leg ---
    put_target = round(S * (1 - pct_OTM) / 10) * 10
    put_strike = puts['strike'].iloc[(puts['strike'] - put_target).abs().argsort()[0]]
    put_iv = puts.loc[puts['strike'] == put_strike, 'impliedVolatility'].iloc[0]
    put_pot = pot_from_delta(S, put_strike, T, risk_free_rate, put_iv, 'put')

    # --- Call Leg ---
    call_target = round(S * (1 + pct_OTM) / 10) * 10
    call_strike = calls['strike'].iloc[(calls['strike'] - call_target).abs().argsort()[0]]
    call_iv = calls.loc[calls['strike'] == call_strike, 'impliedVolatility'].iloc[0]
    call_pot = pot_from_delta(S, call_strike, T, risk_free_rate, call_iv, 'call')

    # 2. Marketwide Benchmark Expected Move Calculation (ATM)
    # Find the call contract closest to the current spot price
    atm_idx = (calls['strike'] - S).abs().idxmin()
    atm_iv = calls.loc[atm_idx, 'impliedVolatility']
    
    # Calculate expected move using the ATM benchmark IV
    expected_move = calculate_expected_move(S, atm_iv, T)

    # ----------------------------
    # DISPLAY RESULTS
    # ----------------------------

    # Clean layout fix bypassing the st.metric bug and formatting issues
    st.markdown("### **Current Market Metrics**")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"**Underlying Price**\n\n${S:,.2f}")
    with col2:
        st.markdown(f"**Expected Move (+/-)**\n\n${expected_move:.2f}")
    with col3:
        # Combined into a single line string to force proper browser rendering
        expected_range_str = f"${S - expected_move:,.2f} to ${S + expected_move:,.2f}"
        st.markdown(f"**Expected Range**\n\n{expected_range_str}")

    st.write(f"**Expiration Cycle:** {expiration_date} ({days_to_expiration} DTE)")
    st.markdown("---")

   # Display based on selected strategy
    st.subheader(f"Strategy Setup: {strategy}")

    if strategy == "Iron Condor":
        # Pull delta directly from your existing Black-Scholes function
        put_delta = black_scholes_delta(S, put_strike, T, risk_free_rate, put_iv, 'put')
        call_delta = black_scholes_delta(S, call_strike, T, risk_free_rate, call_iv, 'call')

        st.write(f"**Short Put Strike:** {put_strike}  |  IV: {put_iv:.2%}  |  **Delta:** {put_delta:.2f}")
        st.write(f"**Short Call Strike:** {call_strike}  |  IV: {call_iv:.2%}  |  **Delta:** {call_delta:.2f}")

        # Combined probabilities for Iron Condor
        prob_either_touch = call_pot + put_pot - (call_pot * put_pot)
        prob_neither_touch = 1 - prob_either_touch

        st.markdown("##### Probabilities")
        st.write(f"💥 **Probability of Touch (Call Leg):** {call_pot:.1%}")
        st.write(f"💥 **Probability of Touch (Put Leg):** {put_pot:.1%}")
        st.success(f"🦅 **Probability Neither Strike Touches (Max Profit):** {prob_neither_touch:.1%}")

    elif strategy == "Put Spread":
        put_delta = black_scholes_delta(S, put_strike, T, risk_free_rate, put_iv, 'put')
        
        st.write(f"**Short Put Strike:** {put_strike}  |  IV: {put_iv:.2%}  |  **Delta:** {put_delta:.2f}")
        prob_no_touch = 1 - put_pot

        st.markdown("##### Probabilities")
        st.write(f"💥 **Probability of Touch (Put Leg):** {put_pot:.1%}")
        st.success(f"🟢 **Probability Put Leg is Safe:** {prob_no_touch:.1%}")

    elif strategy == "Call Spread":
        call_delta = black_scholes_delta(S, call_strike, T, risk_free_rate, call_iv, 'call')
        
        st.write(f"**Short Call Strike:** {call_strike}  |  IV: {call_iv:.2%}  |  **Delta:** {call_delta:.2f}")
        prob_no_touch = 1 - call_pot

        st.markdown("##### Probabilities")
        st.write(f"💥 **Probability of Touch (Call Leg):** {call_pot:.1%}")
        st.success(f"🟢 **Probability Call Leg is Safe:** {prob_no_touch:.1%}")

    st.markdown("---")
    st.caption("POT is estimated from Black-Scholes delta. Actual outcomes depend on volatility, news, and market conditions.")
    st.caption("""
    **Disclaimer:** This tool is for educational and informational purposes only.
    It is not financial advice, and nothing displayed here should be taken as a recommendation to buy or sell any security or options contract.
    Market data is provided by Yahoo Finance and may be delayed or inaccurate.
    Options trading involves significant risk and is not suitable for all investors.
    """)

except Exception as e:
    st.error(f"An error occurred: {e}")
