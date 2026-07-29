from systematic_trading.cloud.logs import tail_cloudwatch_log
from systematic_trading.config import CLOUDWATCH_JOB_LOG_GROUP

for record in tail_cloudwatch_log(
    CLOUDWATCH_JOB_LOG_GROUP,
    stream_prefix="generate_trade_ideas",
    history=50,
):
    print(record)