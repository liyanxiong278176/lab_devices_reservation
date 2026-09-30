# Device-list data-scale profile

Synthetic cohorts in the disposable QA MySQL schema; each uses its own marker.
Three unique pages per depth; the API cache remains enabled.

| Cohort rows | Insert s | Shallow p50 ms | Shallow max ms | Deep p50 ms | Deep max ms |
|---:|---:|---:|---:|---:|---:|
| 1000 | 0.42 | 57.43 | 100.92 | 83.38 | 100.41 |
| 10000 | 0.94 | 43.66 | 46.28 | 40.34 | 44.97 |
| 100000 | 4.72 | 131.53 | 131.62 | 211.00 | 241.37 |
