# RegimeV2 Phase 6H PriceAction Drift Report

## Summary

- Total records: 720
- PriceAction subset removals: 185 (0.2569444444444444)
- Direction tested: 1
- Candidate rows: 88 (0.12222222222222222)
- Passing cells: 0 / 12
- Negative cells: 9
- Rolling failure windows: 15

## Cell Status

| Horizon | Fee bps | Count | Avg lift | Bad rate | Rolling min lift | Rolling positive rate | Status | Reasons |
|---:|---:|---:|---:|---:|---:|---:|---|---|
| 3 | 2.0 | 88 | -0.0020921891977865033 | 0.5568181818181818 | -0.016963140116756037 | 0.6666666666666666 | fail | avg_lift_below_floor, rolling_min_lift_below_floor, rolling_positive_rate_below_floor |
| 3 | 5.0 | 88 | -0.001792189197786503 | 0.5568181818181818 | -0.01666314011675604 | 0.6666666666666666 | fail | avg_lift_below_floor, rolling_min_lift_below_floor, rolling_positive_rate_below_floor |
| 3 | 10.0 | 88 | -0.0012921891977865031 | 0.5568181818181818 | -0.01616314011675604 | 0.6666666666666666 | fail | avg_lift_below_floor, rolling_min_lift_below_floor, rolling_positive_rate_below_floor |
| 6 | 2.0 | 88 | -0.005191555349797758 | 0.5340909090909091 | -0.024103082088263766 | 0.6666666666666666 | fail | avg_lift_below_floor, bad_rate_below_floor, rolling_min_lift_below_floor, rolling_positive_rate_below_floor |
| 6 | 5.0 | 88 | -0.004891555349797758 | 0.5340909090909091 | -0.023803082088263764 | 0.6666666666666666 | fail | avg_lift_below_floor, bad_rate_below_floor, rolling_min_lift_below_floor, rolling_positive_rate_below_floor |
| 6 | 10.0 | 88 | -0.004391555349797758 | 0.5454545454545454 | -0.023303082088263764 | 0.6666666666666666 | fail | avg_lift_below_floor, bad_rate_below_floor, rolling_min_lift_below_floor, rolling_positive_rate_below_floor |
| 12 | 2.0 | 88 | -0.006523643622427316 | 0.5113636363636364 | -0.024792812761196194 | 0.3333333333333333 | fail | avg_lift_below_floor, bad_rate_below_floor, rolling_min_lift_below_floor, rolling_positive_rate_below_floor |
| 12 | 5.0 | 88 | -0.006223643622427316 | 0.5113636363636364 | -0.024492812761196196 | 0.3333333333333333 | fail | avg_lift_below_floor, bad_rate_below_floor, rolling_min_lift_below_floor, rolling_positive_rate_below_floor |
| 12 | 10.0 | 88 | -0.005723643622427316 | 0.5227272727272727 | -0.023992812761196195 | 0.3333333333333333 | fail | avg_lift_below_floor, bad_rate_below_floor, rolling_min_lift_below_floor, rolling_positive_rate_below_floor |
| 24 | 2.0 | 88 | 0.0038792941578966746 | 0.5340909090909091 | -0.024062565941325952 | 0.6666666666666666 | fail | bad_rate_below_floor, rolling_min_lift_below_floor, rolling_positive_rate_below_floor |
| 24 | 5.0 | 88 | 0.004179294157896675 | 0.5454545454545454 | -0.023762565941325954 | 0.6666666666666666 | fail | bad_rate_below_floor, rolling_min_lift_below_floor, rolling_positive_rate_below_floor |
| 24 | 10.0 | 88 | 0.004679294157896675 | 0.5454545454545454 | -0.023262565941325954 | 0.6666666666666666 | fail | bad_rate_below_floor, rolling_min_lift_below_floor, rolling_positive_rate_below_floor |

## Worst Failure Windows

| Horizon | Fee bps | Start | End | Count | Avg lift | Bad rate | Labels |
|---:|---:|---|---|---:|---:|---:|---|
| 12 | 2.0 | 1771977600.0 | 1773489600.0 | 30 | -0.024792812761196194 | 0.23333333333333334 | {'avoided_loss': 7, 'missed_win': 23} |
| 12 | 5.0 | 1771977600.0 | 1773489600.0 | 30 | -0.024492812761196196 | 0.23333333333333334 | {'avoided_loss': 7, 'missed_win': 23} |
| 6 | 2.0 | 1771977600.0 | 1773489600.0 | 30 | -0.024103082088263766 | 0.26666666666666666 | {'avoided_loss': 8, 'missed_win': 22} |
| 24 | 2.0 | 1771977600.0 | 1773489600.0 | 30 | -0.024062565941325952 | 0.3333333333333333 | {'avoided_loss': 10, 'missed_win': 20} |
| 12 | 10.0 | 1771977600.0 | 1773489600.0 | 30 | -0.023992812761196195 | 0.23333333333333334 | {'avoided_loss': 7, 'missed_win': 23} |
| 6 | 5.0 | 1771977600.0 | 1773489600.0 | 30 | -0.023803082088263764 | 0.26666666666666666 | {'avoided_loss': 8, 'missed_win': 22} |
| 24 | 5.0 | 1771977600.0 | 1773489600.0 | 30 | -0.023762565941325954 | 0.3333333333333333 | {'avoided_loss': 10, 'missed_win': 20} |
| 6 | 10.0 | 1771977600.0 | 1773489600.0 | 30 | -0.023303082088263764 | 0.26666666666666666 | {'avoided_loss': 8, 'missed_win': 22} |
| 24 | 10.0 | 1771977600.0 | 1773489600.0 | 30 | -0.023262565941325954 | 0.3333333333333333 | {'avoided_loss': 10, 'missed_win': 20} |
| 3 | 2.0 | 1771977600.0 | 1773489600.0 | 30 | -0.016963140116756037 | 0.3 | {'avoided_loss': 9, 'missed_win': 21} |

## Asset / Timeframe Summary

| Asset/TF | Cells | Negative cells | Avg lift | Bad rate |
|---|---:|---:|---:|---:|
| ETHUSDT|4h | 12 | 12 | -0.02796063803617932 | 0.2875 |
| SOLUSDT|4h | 12 | 12 | -0.011510433970034668 | 0.3958333333333333 |
| BTCUSDT|4h | 12 | 12 | -0.009219100927506059 | 0.31862745098039214 |
| BNBUSDT|1h | 12 | 0 | 0.017125930321326772 | 0.8055555555555556 |

## Direction Comparison

| Direction | Cells | Count | Avg lift | Bad rate |
|---:|---:|---:|---:|---:|
| -1 | 12 | 1164 | 0.0002717036643974916 | 0.5060137457044673 |
| 1 | 12 | 1056 | -0.002115356836362059 | 0.5378787878787878 |
