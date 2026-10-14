# Fault-injection evaluation

Correct reference SQL with one realistic LLM mistake injected, played through the real pipeline. *caught* = detected and corrected to the right answer; *missed* = a wrong answer was returned silently; *no effect* = the mistake didn't change the result.

| Mistake | Cases | Caught | Missed | No effect | Detected by |
|---|---|---|---|---|---|
| categorical value in the wrong case ('Completed') | 9 | 9 | 0 | 0 | unknown_value |
| near-miss categorical value ('refund', 'complete') | 9 | 9 | 0 | 0 | unknown_value |
| misspelled column (quantity -> qty) | 8 | 8 | 0 | 0 | unknown_column |
| forgot the revenue status rule (counts refunds as revenue) | 7 | 7 | 0 | 0 | business_rule_violation |
| ignored the requested number of rows (LIMIT removed) | 4 | 4 | 0 | 0 | row_count_mismatch |
| off-by-one date range ('last six months' from 29 Mar) | 1 | 0 | 1 | 0 | - |
| counted rows instead of summing units | 1 | 0 | 1 | 0 | - |

Mistakes that changed the answer: 39 of 39. Caught: 37. Missed: 2.
