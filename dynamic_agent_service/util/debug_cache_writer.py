import os
import json
from pathlib import Path

def get_cache_folder():
    cache_dir = os.getenv("CHCHE_DIR")
    if not cache_dir:
        raise ValueError("CHCHE_DIR not found in environment variables")

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    return cache_path

def debug_cache_json(file_name, debug_json):
    """
    Write debug JSON to cache folder with file_name as the filename.
    """
    cache_folder = get_cache_folder()
    file_path = cache_folder / f"{file_name}.json"

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(debug_json, f, ensure_ascii=False, indent=2)

def debug_cache_md(file_name, text):
    """Write debug text to cache folder as a .md file."""
    cache_folder = get_cache_folder()
    file_path = cache_folder / f"{file_name}.md"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)

def debug_trigger_response(messages: list[dict], tools: list[dict]):
    """
    Called at the end of agent_general_interface's trigger to dump
    the full conversation and tool definitions into a readable .md file.
    """
    WIDTH = 50
    lines = []

    for msg in messages:
        role = msg.get("role", "unknown")

        if role == "system":
            lines.append("System Prompt".center(WIDTH, "="))
            lines.append(msg.get("content", ""))
            lines.append("")

            # Print tools right after system prompt
            if tools:
                lines.append("Tools".center(WIDTH, "="))
                for tool in tools:
                    func = tool.get("function", {})
                    name = func.get("name", "")
                    desc = func.get("description", "")
                    lines.append(f"[{name}]")
                    lines.append(f"  - Description: {desc}")
                    params = func.get("parameters", {}).get("properties", {})
                    if params:
                        lines.append("  - Parameters:")
                        for p_name, p_info in params.items():
                            p_desc = p_info.get("description", "")
                            p_type = p_info.get("type", "")
                            entry = f"      {p_name} ({p_type})"
                            if p_desc:
                                entry += f": {p_desc}"
                            lines.append(entry)
                    lines.append("")

        elif role == "user":
            lines.append("User".center(WIDTH, "="))
            lines.append(msg.get("content", ""))
            lines.append("")

        elif role == "assistant":
            lines.append("Assistant".center(WIDTH, "="))
            content = msg.get("content", "") or ""
            if content:
                lines.append(content)
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                lines.append("")
                for tc in tool_calls:
                    func = tc.get("function", {})
                    lines.append(f"[{func.get('name', '')}] (id: {tc.get('id', '')})")
                    lines.append(f"Arguments: {func.get('arguments', '')}")
                    lines.append("")
            lines.append("")

        elif role == "tool":
            lines.append("Tool Result".center(WIDTH, "="))
            tool_call_id = msg.get("tool_call_id", "")
            # find tool name by matching tool_call_id in messages
            tool_name = ""
            for m in messages:
                for tc in m.get("tool_calls", []):
                    if tc.get("id") == tool_call_id:
                        tool_name = tc.get("function", {}).get("name", "")
                        break
            lines.append(f"tool: {tool_name}")
            lines.append(f"tool_call_id: {tool_call_id}")
            lines.append(f"content: {msg.get('content', '')}")
            lines.append("")

    text = "\n".join(lines)
    debug_cache_md("trigger_response", text)