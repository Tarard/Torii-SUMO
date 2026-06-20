# Local MCP Host Configuration

Torii is a local stdio MCP server. Configure it in an MCP-capable host with absolute paths so the host can find the Python interpreter, SUMO installation, and project source tree without depending on the current working directory.

Example host configuration:

```json
{
  "mcpServers": {
    "torii-sumo": {
      "command": "C:\\path\\to\\python.exe",
      "args": [
        "C:\\path\\to\\repo\\plugins\\torii-sumo\\scripts\\run_torii_sumo.py"
      ],
      "env": {
        "SUMO_HOME": "C:\\Program Files\\Eclipse\\sumo",
        "PYTHONPATH": "C:\\path\\to\\repo\\plugins\\torii-sumo\\src"
      }
    }
  }
}
```

If the package has been installed in the host's Python environment, the installed `torii-sumo` console script can be used instead of the module form.

The server communicates with the MCP host through stdio. SUMO subprocess stdout and stderr are captured by the tool code and returned to the host as structured fields.
