from systematic_trading.cloud.logs import tail_cloudwatch_log
from systematic_trading.config import CLOUDWATCH_LOG_GROUP

for record in tail_cloudwatch_log(
    CLOUDWATCH_LOG_GROUP,
    stream_prefix="live_btc_ticker",
    history=50,
):
    print(record)