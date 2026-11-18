---
description: Start the demo console for live calls and open it in the browser
---

Start the demo console in the background from the repo root:

```bash
python -m voice.demo --open
```

It serves http://localhost:7860/demo (localhost only) and opens it in the default browser once the server is up. Do not start a call: the user starts it with the Start call button. Tell the user the page is open, and that Ctrl+C in the server's terminal (or stopping the background task) shuts it down.
