from systematic_trading.cloud.logs import tail_cloudwatch_log, read_s3_log

tail_cloudwatch_log(stream_prefix="live_csf_champions", history=50)
read_s3_log("logs/live_csf_champions/2026-07-23T14Z/full.log")