# Evaluation run - mock / mock-rules-v2

Run at 2026-10-14T15:31:29.017307+00:00 on 14 questions.

> **Mock provider**: SQL comes from pre-written rules, not an LLM. This run checks the pipeline (validation, execution, comparison), not model accuracy.

| Metric | Value |
|---|---|
| Execution success rate | 50% |
| Correct result rate | 50% |
| Executed but wrong | 0 |
| Questions needing a retry | 0 |
| Retry success rate | - |
| Average latency | 4 ms |
| Total estimated cost | unavailable |

Failure categories: {'unanswerable': 7}

| # | Question | Status | Correct | Retries | Latency | Note |
|---|---|---|---|---|---|---|
| 1 | What is our total revenue? | success | yes | 0 | 26 ms | match |
| 2 | Which five products generated the highest revenue? | success | yes | 0 | 7 ms | match |
| 3 | Show the customer IDs and names of the five customers who placed the most orders, with their order counts. | success | yes | 0 | 3 ms | match |
| 4 | What was our monthly revenue over the last six months? | success | yes | 0 | 8 ms | match |
| 5 | Which product categories perform best by revenue? | success | yes | 0 | 7 ms | match |
| 6 | What is the average order value? | success | yes | 0 | 5 ms | match |
| 7 | Which products have never been ordered? | success | yes | 0 | 3 ms | match |
| 8 | How many customers do we have in each country? | unanswerable | no | 0 | 0 ms | The offline mock provider only knows the built-in example questions. Set ANTHROP |
| 9 | How many orders were cancelled? | unanswerable | no | 0 | 0 ms | The offline mock provider only knows the built-in example questions. Set ANTHROP |
| 10 | What was the revenue for each payment method in 2026? | unanswerable | no | 0 | 0 ms | The offline mock provider only knows the built-in example questions. Set ANTHROP |
| 11 | Which customer segment generated the most revenue? | unanswerable | no | 0 | 0 ms | The offline mock provider only knows the built-in example questions. Set ANTHROP |
| 12 | How many units of each product category were sold in completed orders? | unanswerable | no | 0 | 1 ms | The offline mock provider recognised this question but can't apply its order sta |
| 13 | Which two cities have the most customers? | unanswerable | no | 0 | 0 ms | The offline mock provider only knows the built-in example questions. Set ANTHROP |
| 14 | How many orders did each customer segment place in 2026? | unanswerable | no | 0 | 0 ms | The offline mock provider only knows the built-in example questions. Set ANTHROP |
