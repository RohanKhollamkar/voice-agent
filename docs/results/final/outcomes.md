# How outcomes were captured

Main runs: commit `de12c92`, judge `moonshotai/kimi-k3.1-pro`. A call's outcome is either recorded during the call (`captured_by: tool_call`) or read off the transcript after it by the extraction model (`captured_by: post_call_extraction`). v1 has a record_outcome tool but no nudges or code-recorded outcomes.

| How | v1 main | v2 main | v1 held-out | v2 held-out |
|---|---|---|---|---|
| recorded by the bot on its own (record_outcome) | 54% (31/57) | 68% (39/57) | 20% (1/5) | 60% (3/5) |
| recorded by the bot after a nudge from code | 0% (0/57) | 14% (8/57) | 0% (0/5) | 20% (1/5) |
| recorded by code (forced transfer) | 0% (0/57) | 16% (9/57) | 0% (0/5) | 0% (0/5) |
| recorded by code (time-limit close) | 0% (0/57) | 0% (0/57) | 0% (0/5) | 0% (0/5) |
| read off the transcript after the call (post_call_extraction) | 46% (26/57) | 0% (0/57) | 80% (4/5) | 20% (1/5) |
| no outcome | 0% (0/57) | 2% (1/57) | 0% (0/5) | 0% (0/5) |
