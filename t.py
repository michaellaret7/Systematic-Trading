from systematic_trading.cloud.logs import tail_cloudwatch_log

  # follow one strategy, INFO only
for entry in tail_cloudwatch_log(level="INFO", stream_prefix="live_btc_ticker", history=100):
    print(f"{entry.time} {entry.source}: {entry.message}")