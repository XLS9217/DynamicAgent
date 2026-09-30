"""Script name: resource_browser.py. Browse OpenAI resources in the terminal."""

from pathlib import Path

from dotenv import load_dotenv
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Static

from dynamic_agent_service.external_service.openai_resource_accessor import (
    OpenAIResourceAccessor,
)
from dynamic_agent_service.external_service.openai_resource_structs import OpenAIResource
from dynamic_agent_service.external_service.pg_instance import PgInstance


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _masked_key(api_key: str) -> str:
    """Keep enough characters to identify a key without exposing it."""
    if len(api_key) <= 10:
        return "•" * len(api_key)
    return f"{api_key[:6]}{'•' * 10}{api_key[-4:]}"


class ResourceBrowser(App):
    """Show current OpenAI-compatible resources without changing them."""

    TITLE = "DynamicAgent · OpenAI Resources"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("v", "toggle_key", "Show/hide key"),
    ]
    CSS = """
    Screen { layout: vertical; }
    #status { height: 3; padding: 1 2; }
    #resources { height: 1fr; margin: 0 1; }
    #details { height: 10; margin: 1; padding: 1 2; border: round $primary; }
    """

    def __init__(self) -> None:
        """Initialize empty display state."""
        super().__init__()
        self.resources: dict[str, OpenAIResource] = {}
        self.active_resource_id: str | None = None
        self.selected_resource_id: str | None = None
        self.show_key = False
        self.pool_ready = False

    def compose(self) -> ComposeResult:
        """Build the resource table and detail panel."""
        yield Header()
        with Vertical():
            yield Static("Loading resources…", id="status")
            yield DataTable(id="resources", cursor_type="row", zebra_stripes=True)
            yield Static("Select a resource to inspect it.", id="details", markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        """Connect to PostgreSQL and load resources."""
        table = self.query_one("#resources", DataTable)
        table.add_columns("Active", "Model", "Base URL", "Enabled", "Priority", "API key")
        await self._refresh_resources()

    async def on_unmount(self) -> None:
        """Close the shared PostgreSQL pool."""
        if self.pool_ready:
            await PgInstance.close()

    async def action_refresh(self) -> None:
        """Reload all current resources from PostgreSQL."""
        await self._refresh_resources()

    def action_toggle_key(self) -> None:
        """Toggle the selected resource key between masked and visible."""
        self.show_key = not self.show_key
        self._render_details()

    async def _refresh_resources(self) -> None:
        """Fetch resources and replace the displayed rows."""
        status = self.query_one("#status", Static)
        table = self.query_one("#resources", DataTable)
        status.update("Loading resources…")
        try:
            if not self.pool_ready:
                await PgInstance.initialize()
                self.pool_ready = True
            items = await OpenAIResourceAccessor.list_resources(enabled_only=False)
            active = await OpenAIResourceAccessor.get_active_resource()
        except Exception as exc:
            status.update(f"Database error: {type(exc).__name__}: {exc}")
            return

        self.resources = {item.resource_id: item for item in items}
        self.active_resource_id = active.resource_id if active else None
        table.clear()
        for item in items:
            marker = Text("●", style="bold green") if item.resource_id == self.active_resource_id else ""
            table.add_row(
                marker,
                item.model,
                item.base_url,
                "yes" if item.enabled else "no",
                str(item.priority),
                _masked_key(item.api_key),
                key=item.resource_id,
            )
        status.update(f"{len(items)} resources · active model: {active.model if active else 'none'}")
        if self.selected_resource_id not in self.resources:
            self.selected_resource_id = items[0].resource_id if items else None
        if items:
            table.focus()
        self._render_details()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Show details for the highlighted resource."""
        self.selected_resource_id = str(event.row_key.value)
        self.show_key = False
        self._render_details()

    def _render_details(self) -> None:
        """Render the selected resource with a protected API key."""
        panel = self.query_one("#details", Static)
        item = self.resources.get(self.selected_resource_id or "")
        if item is None:
            panel.update("No resource selected.")
            return
        api_key = item.api_key if self.show_key else _masked_key(item.api_key)
        panel.update(
            "\n".join([
                f"Resource ID: {item.resource_id}",
                f"Model:       {item.model}",
                f"Base URL:    {item.base_url}",
                f"API key:     {api_key}",
                f"Enabled:     {item.enabled}",
                f"Priority:    {item.priority}",
                f"Active:      {item.resource_id == self.active_resource_id}",
            ])
        )
