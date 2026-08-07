from systematic_trading.data.repository import load_daily_prices

df = load_daily_prices()

df['daily_range'] = df.apply(lambda x: x['close'] - x['open'], axis=1)

print(df)