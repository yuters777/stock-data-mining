import yfinance as yf
import os
os.makedirs('backtester/data/daily', exist_ok=True)
tickers = ['AAPL','AMD','AMZN','ARM','AVGO','BA','BABA','BIDU','C','COIN','COST','GOOGL','GS','INTC','JPM','MARA','META','MSFT','MSTR','MU','NVDA','PLTR','SMCI','TSLA','TSM','V','SPY']
for t in tickers:
    df = yf.download(t, start='2022-01-01', end='2026-04-01', auto_adjust=True)
    df.to_csv(f'backtester/data/daily/{t}_daily.csv')
    print(f'{t}: {len(df)} rows')
print('Done!')
