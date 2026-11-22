# How outcomes were captured

Recorded during the call (`captured_by: tool_call`), or read off the transcript afterwards by the extraction model (`post_call_extraction`). Since commit ccd671c an unsupported extraction in v2 and v2.1 falls back to CALLBACK_REQUEST call_dropped, also counted under post_call_extraction.

| How | v1 main | v2 main | v2.1 main |
|---|---|---|---|
| recorded by the bot on its own (record_outcome) | 68% (26/38) | 74% (28/38) | 68% (26/38) |
| recorded by the bot after a nudge from code | 0% (0/38) | 11% (4/38) | 16% (6/38) |
| recorded by code (forced transfer) | 0% (0/38) | 16% (6/38) | 16% (6/38) |
| recorded by code (time-limit close) | 0% (0/38) | 0% (0/38) | 0% (0/38) |
| read off the transcript after the call (post_call_extraction) | 32% (12/38) | 0% (0/38) | 0% (0/38) |
| no outcome | 0% (0/38) | 0% (0/38) | 0% (0/38) |

Main-set calls ending as CALLBACK_REQUEST call_dropped: v1 4, v2 0, v2.1 0.
