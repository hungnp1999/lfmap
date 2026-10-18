# lfmap-echo

Reference plugin for lfmap-core. It has one operation, `say`, which repeats text, and exists so the generated adapters can be tested end to end.

```powershell
uv run lfmap echo say --text "xin chào" --upper      # CLI
uv run lfmap serve mcp --plugins echo                 # MCP server (stdio), tool echo_say
```

```python
from lfmap_echo import SayInput, say

say(SayInput(text="hi")).text
```
