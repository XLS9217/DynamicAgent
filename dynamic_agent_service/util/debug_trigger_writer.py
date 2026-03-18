"""
Incremental debug writer for the trigger loop.

Usage in trigger():
    writer = DebugTriggerWriter()
    writer.put_system(system_content)
    writer.put_tools(tools)
    # in loop:
        writer.put_invoke(messages)  # writes only new messages since last call
"""
import os
from pathlib import Path

WIDTH = 50


class DebugTriggerWriter:

    def __init__(self):
        self._last_index = 0
        self._invoke_count = 0
        cache_dir = os.getenv("CACHE_DIR")
        if not cache_dir:
            self._file_path = None
            return
        cache_path = Path(cache_dir)
        cache_path.mkdir(parents=True, exist_ok=True)
        self._file_path = cache_path / "trigger_response.md"
        with open(self._file_path, "w", encoding="utf-8") as f:
            f.write("")

    def _append(self, text: str):
        if not self._file_path:
            return
        with open(self._file_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    def put_system(self, content: str):
        self._append("System Prompt".center(WIDTH, "="))
        self._append(content)
        self._append("")

    def put_tools(self, tools: list[dict]):
        self._append("Tools".center(WIDTH, "="))
        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name", "")
            desc = func.get("description", "")
            self._append(f"[{name}]")
            self._append(f"  - Description: {desc}")
            params = func.get("parameters", {}).get("properties", {})
            if params:
                self._append("  - Parameters:")
                for p_name, p_info in params.items():
                    p_desc = p_info.get("description", "")
                    p_type = p_info.get("type", "")
                    entry = f"      {p_name} ({p_type})"
                    if p_desc:
                        entry += f": {p_desc}"
                    self._append(entry)
            self._append("")

    def put_invoke(self, messages: list[dict]):
        """Write only the new messages since the last put_invoke call."""
        self._invoke_count += 1
        self._append("")
        self._append(f">>>>>>>>>>>>>> INVOKE {self._invoke_count} <<<<<<<<<<<<<<")
        self._append("")

        new_messages = messages[self._last_index:]
        self._last_index = len(messages)

        for msg in new_messages:
            role = msg.get("role", "")

            if role == "user":
                self._append("User".center(WIDTH, "="))
                self._append(msg.get("content", ""))
                self._append("")

            elif role == "assistant":
                self._append("Assistant".center(WIDTH, "="))
                content = msg.get("content", "") or ""
                if content:
                    self._append(content)
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    self._append("")
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        self._append(f"[{func.get('name', '')}] (id: {tc.get('id', '')})")
                        self._append(f"Arguments: {func.get('arguments', '')}")
                        self._append("")

            elif role == "tool":
                self._append("Tool Result".center(WIDTH, "="))
                tool_call_id = msg.get("tool_call_id", "")
                tool_name = ""
                for m in messages:
                    for tc in m.get("tool_calls", []):
                        if tc.get("id") == tool_call_id:
                            tool_name = tc.get("function", {}).get("name", "")
                            break
                self._append(f"tool: {tool_name}")
                self._append(f"tool_call_id: {tool_call_id}")
                self._append(f"content: {msg.get('content', '')}")
                self._append("")
