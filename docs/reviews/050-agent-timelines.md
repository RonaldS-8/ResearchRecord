# Gate50 · 120回合实际动作与计量

源码2af1a6b；每行实际参数重放一致，协议pass、非法调用0。时间为SDK累计秒；完整参数/回执见云端episode，最终答复见派生JSON。

| 回合 | strict | 发布数 | 恢复动作 | 工具费 执行/诊断 | SDK秒 |
|---|---:|---:|---|---:|---:|
| 500001-C-R0 | 0 | 1 | STOP | 0/0 | 11.58 |
| 500001-C-BTM | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 25.25 |
| 500001-C-BTM_NR | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 22.33 |
| 500001-C-H | 1 | 1 | list_record_publications → read_published_record | 1/1 | 14.66 |
| 500001-T-R0 | 0 | 0 | STOP | 0/0 | 11.54 |
| 500001-T-BTM | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 24.46 |
| 500001-T-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 22.87 |
| 500001-T-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 36.41 |
| 500001-P-R0 | 0 | 0 | STOP | 0/0 | 11.81 |
| 500001-P-BTM | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 27.54 |
| 500001-P-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 23.58 |
| 500001-P-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 37.17 |
| 500002-T-BTM | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 28.01 |
| 500002-T-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 22.61 |
| 500002-T-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 33.82 |
| 500002-T-R0 | 0 | 0 | STOP | 0/0 | 11.31 |
| 500002-P-BTM | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 28.27 |
| 500002-P-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 23.22 |
| 500002-P-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 34.41 |
| 500002-P-R0 | 0 | 0 | STOP | 0/0 | 11.20 |
| 500002-C-BTM | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 26.59 |
| 500002-C-BTM_NR | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 24.10 |
| 500002-C-H | 1 | 1 | list_record_publications → read_published_record | 1/1 | 12.32 |
| 500002-C-R0 | 0 | 1 | STOP | 0/0 | 11.21 |
| 500003-P-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 27.86 |
| 500003-P-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 36.19 |
| 500003-P-R0 | 0 | 0 | STOP | 0/0 | 9.25 |
| 500003-P-BTM | 1 | 1 | publish_verified_record → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 4/0 | 56.43 |
| 500003-C-BTM_NR | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 29.24 |
| 500003-C-H | 1 | 1 | list_record_publications → read_published_record | 1/1 | 17.23 |
| 500003-C-R0 | 0 | 1 | STOP | 0/0 | 8.98 |
| 500003-C-BTM | 0 | 2 | publish_verified_record → read_published_record | 2/0 | 63.54 |
| 500003-T-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 28.56 |
| 500003-T-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 35.33 |
| 500003-T-R0 | 0 | 0 | STOP | 0/0 | 8.88 |
| 500003-T-BTM | 1 | 1 | publish_verified_record → read_published_record | 2/0 | 42.96 |
| 500004-C-H | 1 | 1 | list_record_publications → read_published_record | 1/1 | 14.74 |
| 500004-C-R0 | 0 | 1 | STOP | 0/0 | 18.40 |
| 500004-C-BTM | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 27.79 |
| 500004-C-BTM_NR | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 23.52 |
| 500004-T-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 33.67 |
| 500004-T-R0 | 0 | 0 | STOP | 0/0 | 19.02 |
| 500004-T-BTM | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 27.64 |
| 500004-T-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 24.88 |
| 500004-P-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 32.02 |
| 500004-P-R0 | 0 | 0 | STOP | 0/0 | 18.34 |
| 500004-P-BTM | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 26.78 |
| 500004-P-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 25.36 |
| 500005-T-R0 | 0 | 0 | STOP | 0/0 | 11.25 |
| 500005-T-BTM | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 20.57 |
| 500005-T-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 24.76 |
| 500005-T-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 34.09 |
| 500005-P-R0 | 0 | 0 | STOP | 0/0 | 10.80 |
| 500005-P-BTM | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 20.17 |
| 500005-P-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 23.63 |
| 500005-P-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 34.89 |
| 500005-C-R0 | 0 | 1 | STOP | 0/0 | 11.31 |
| 500005-C-BTM | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 19.00 |
| 500005-C-BTM_NR | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 22.05 |
| 500005-C-H | 1 | 1 | list_record_publications → read_published_record | 1/1 | 14.13 |
| 500006-P-BTM | 1 | 1 | publish_verified_record → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 4/0 | 50.68 |
| 500006-P-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 23.58 |
| 500006-P-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 43.25 |
| 500006-P-R0 | 0 | 0 | STOP | 0/0 | 7.94 |
| 500006-C-BTM | 0 | 2 | publish_verified_record → read_published_record | 2/0 | 29.22 |
| 500006-C-BTM_NR | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 24.33 |
| 500006-C-H | 1 | 1 | list_record_publications → read_published_record | 1/1 | 17.83 |
| 500006-C-R0 | 0 | 1 | STOP | 0/0 | 8.23 |
| 500006-T-BTM | 1 | 1 | publish_verified_record → read_published_record | 2/0 | 30.11 |
| 500006-T-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 23.36 |
| 500006-T-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 43.86 |
| 500006-T-R0 | 0 | 0 | STOP | 0/0 | 8.00 |
| 500007-C-BTM_NR | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 25.76 |
| 500007-C-H | 1 | 1 | list_record_publications → read_published_record | 1/1 | 31.38 |
| 500007-C-R0 | 0 | 1 | STOP | 0/0 | 10.43 |
| 500007-C-BTM | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 36.69 |
| 500007-T-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 26.97 |
| 500007-T-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 34.44 |
| 500007-T-R0 | 0 | 0 | STOP | 0/0 | 10.12 |
| 500007-T-BTM | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 40.42 |
| 500007-P-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 28.37 |
| 500007-P-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 34.42 |
| 500007-P-R0 | 0 | 0 | STOP | 0/0 | 9.91 |
| 500007-P-BTM | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 40.59 |
| 500008-T-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 34.50 |
| 500008-T-R0 | 0 | 0 | STOP | 0/0 | 13.99 |
| 500008-T-BTM | 1 | 1 | publish_verified_record → read_published_record | 2/0 | 32.58 |
| 500008-T-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 25.85 |
| 500008-P-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 32.88 |
| 500008-P-R0 | 0 | 0 | STOP | 0/0 | 13.69 |
| 500008-P-BTM | 1 | 1 | publish_verified_record → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 4/0 | 46.95 |
| 500008-P-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 26.37 |
| 500008-C-H | 1 | 1 | list_record_publications → read_published_record | 1/1 | 20.78 |
| 500008-C-R0 | 0 | 1 | STOP | 0/0 | 15.23 |
| 500008-C-BTM | 0 | 2 | publish_verified_record → read_published_record | 2/0 | 29.75 |
| 500008-C-BTM_NR | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 26.77 |
| 500009-P-R0 | 0 | 0 | STOP | 0/0 | 14.15 |
| 500009-P-BTM | 1 | 1 | publish_verified_record → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 4/0 | 49.77 |
| 500009-P-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 32.42 |
| 500009-P-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 29.85 |
| 500009-C-R0 | 0 | 1 | STOP | 0/0 | 13.71 |
| 500009-C-BTM | 0 | 2 | publish_verified_record → read_published_record | 2/0 | 38.19 |
| 500009-C-BTM_NR | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 32.42 |
| 500009-C-H | 1 | 1 | list_record_publications → read_published_record | 1/1 | 12.70 |
| 500009-T-R0 | 0 | 0 | STOP | 0/0 | 13.76 |
| 500009-T-BTM | 1 | 1 | publish_verified_record → read_published_record | 2/0 | 39.00 |
| 500009-T-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 33.41 |
| 500009-T-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 31.49 |
| 500010-C-BTM | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 28.53 |
| 500010-C-BTM_NR | 0 | 2 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 29.07 |
| 500010-C-H | 1 | 1 | list_record_publications → read_published_record | 1/1 | 13.71 |
| 500010-C-R0 | 0 | 1 | STOP | 0/0 | 13.31 |
| 500010-T-BTM | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 30.18 |
| 500010-T-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 31.46 |
| 500010-T-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 31.66 |
| 500010-T-R0 | 0 | 0 | STOP | 0/0 | 12.85 |
| 500010-P-BTM | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 29.72 |
| 500010-P-BTM_NR | 1 | 1 | prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/0 | 30.77 |
| 500010-P-H | 1 | 1 | list_record_publications → prepare_alternate_publication → confirm_alternate_publication → read_published_record | 3/1 | 31.33 |
| 500010-P-R0 | 0 | 0 | STOP | 0/0 | 12.69 |
