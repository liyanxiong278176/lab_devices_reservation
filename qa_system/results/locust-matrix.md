# Locust mixed business and AI API profile

Headless Locust, 10s per run, read-only endpoints after CSRF-protected login.
The isolated QA API disables request rate limiting only for this capacity profile; authentication and rate limiting are checked separately.
This fixture-scale run does not represent larger database cardinalities or production infrastructure.

| Users | Rep | Requests | Failures | Median ms | p95 ms | RPS |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 1 | 93 | 0 | 23 | 450 | 10.383540187655864 |
| 5 | 2 | 93 | 0 | 22 | 400 | 10.312502200926012 |
| 5 | 3 | 93 | 0 | 15 | 230 | 10.327709399477227 |
| 10 | 1 | 192 | 0 | 16 | 290 | 21.152729484286716 |
| 10 | 2 | 192 | 0 | 15 | 440 | 21.432281114147244 |
| 10 | 3 | 185 | 0 | 17 | 360 | 20.440829117449525 |
| 25 | 1 | 442 | 0 | 16 | 470 | 48.85720691241047 |
| 25 | 2 | 432 | 0 | 16 | 610 | 48.04108764104024 |
| 25 | 3 | 361 | 2 | 22 | 1600 | 39.88682973141247 |
| 50 | 1 | 536 | 22 | 49 | 1800 | 59.33345083122368 |
| 50 | 2 | 526 | 36 | 40 | 1900 | 58.255968116915206 |
| 50 | 3 | 634 | 528 | 11 | 1600 | 70.01704239724708 |
| 100 | 1 | 277 | 102 | 2100 | 3200 | 30.68218352301055 |
| 100 | 2 | 264 | 100 | 2100 | 3200 | 29.497651301845 |
| 100 | 3 | 307 | 114 | 1900 | 3000 | 34.0253094770001 |
