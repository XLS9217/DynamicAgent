"""Smoke test two sequential subagents with different assigned operators."""

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv

from dynamic_agent_client import (
    AgentEvent,
    AgentInvocationEvent,
    AgentOperator,
    DynamicAgentClient,
    SubagentOperator,
    ToolExecutionEvent,
    agent_tool,
    description,
)
from dynamic_agent_client.service_handler import ServiceHandler

load_dotenv()


MOCK_POSTS = [
    {
        "id": "post-01",
        "text": "A quiet morning walk by the river.",
        "likes": 90,
        "views": 900,
        "comments": [
            {"id": "comment-01-a", "text": "Beautiful view!", "likes": 8},
            {"id": "comment-01-b", "text": "Thanks for sharing.", "likes": 3},
        ],
    },
    {
        "id": "post-02",
        "text": "My first attempt at homemade bread.",
        "likes": 420,
        "views": 600,
        "comments": [
            {"id": "comment-02-a", "text": "That crust looks excellent.", "likes": 20},
            {"id": "comment-02-b", "text": "I want the recipe!", "likes": 11},
            {"id": "comment-02-c", "text": "How long did you proof it?", "likes": 7},
            {"id": "comment-02-d", "text": "The crumb looks very light.", "likes": 5},
            {"id": "comment-02-e", "text": "Great first attempt.", "likes": 4},
        ],
    },
    {
        "id": "post-03",
        "text": "Three practical ways to organize a small desk.",
        "likes": 180,
        "views": 1200,
        "comments": [
            {"id": "comment-03-a", "text": "The second tip helped me.", "likes": 6},
            {"id": "comment-03-b", "text": "Useful and concise.", "likes": 5},
        ],
    },
    {
        "id": "post-04",
        "text": "A short review of a neighborhood cafe.",
        "likes": 75,
        "views": 1500,
        "comments": [
            {"id": "comment-04-a", "text": "You are an idiot and this post is garbage.", "likes": 31},
            {"id": "comment-04-b", "text": "I had a different experience there.", "likes": 2},
            {"id": "comment-04-c", "text": "Was it busy when you visited?", "likes": 6},
            {"id": "comment-04-d", "text": "Their coffee was good last week.", "likes": 5},
            {"id": "comment-04-e", "text": "The service can be inconsistent.", "likes": 3},
            {"id": "comment-04-f", "text": "Thanks for the honest review.", "likes": 2},
        ],
    },
    {
        "id": "post-05",
        "text": "Weekend cycling route through the hills.",
        "likes": 250,
        "views": 2000,
        "comments": [
            {"id": "comment-05-a", "text": "How difficult is the final climb?", "likes": 9},
            {"id": "comment-05-b", "text": "Saving this route.", "likes": 4},
        ],
    },
    {
        "id": "post-06",
        "text": "A beginner-friendly watercolor exercise.",
        "likes": 310,
        "views": 3100,
        "comments": [
            {"id": "comment-06-a", "text": "Trying this tonight.", "likes": 14},
            {"id": "comment-06-b", "text": "Lovely colors.", "likes": 7},
        ],
    },
    {
        "id": "post-07",
        "text": "What I learned from growing tomatoes indoors.",
        "likes": 160,
        "views": 800,
        "comments": [
            {"id": "comment-07-a", "text": "Mine need more sunlight.", "likes": 5},
            {"id": "comment-07-b", "text": "Great explanation.", "likes": 4},
        ],
    },
    {
        "id": "post-08",
        "text": "A ten-minute stretching routine.",
        "likes": 500,
        "views": 5000,
        "comments": [
            {"id": "comment-08-a", "text": "My shoulders feel better.", "likes": 18},
            {"id": "comment-08-b", "text": "Clear instructions.", "likes": 10},
            {"id": "comment-08-c", "text": "A useful morning routine.", "likes": 8},
            {"id": "comment-08-d", "text": "Please make a longer version.", "likes": 4},
        ],
    },
    {
        "id": "post-09",
        "text": "Notes from an evening photography walk.",
        "likes": 130,
        "views": 2600,
        "comments": [
            {"id": "comment-09-a", "text": "The lighting is fantastic.", "likes": 12},
            {"id": "comment-09-b", "text": "Which lens did you use?", "likes": 6},
        ],
    },
    {
        "id": "post-10",
        "text": "Simple meal preparation for a busy week.",
        "likes": 280,
        "views": 1400,
        "comments": [
            {"id": "comment-10-a", "text": "This saves so much time.", "likes": 16},
            {"id": "comment-10-b", "text": "Good portion sizes.", "likes": 8},
        ],
    },
]


class SearchOperator(AgentOperator):
    def __init__(self, posts: list[dict]):
        self.posts = posts
        self.calls: list[dict] = []
        super().__init__()

    @description
    def get_description(self) -> str:
        return "Search posts and fetch comments for a specific post."

    @agent_tool(description="Search all mock posts for a keyword; use 'all' to return every post")
    async def search_keyword(self, keyword: str) -> list[dict]:
        """:param keyword: Search text, or 'all' to return every post"""
        await asyncio.sleep(0.1)
        normalized = keyword.strip().lower()
        posts = self.posts if normalized == "all" else [
            post for post in self.posts if normalized in post["text"].lower()
        ]
        result = [
            {
                "id": post["id"],
                "text": post["text"],
                "likes": post["likes"],
                "views": post["views"],
                "comment_count": len(post["comments"]),
            }
            for post in posts
        ]
        self.calls.append({"tool": "search_keyword", "keyword": keyword, "result": result})
        return result

    @agent_tool(description="Fetch all comments for one post ID")
    async def see_comment(self, post_id: str) -> list[dict]:
        """:param post_id: Post ID returned by search_keyword"""
        await asyncio.sleep(0.1)
        post = next(post for post in self.posts if post["id"] == post_id)
        result = list(post["comments"])
        self.calls.append({"tool": "see_comment", "post_id": post_id, "result": result})
        return result


class StatOperator(AgentOperator):
    def __init__(self, posts: list[dict]):
        self.posts = posts
        self.calls: list[dict] = []
        super().__init__()

    @description
    def get_description(self) -> str:
        return "Calculate engagement statistics and identify aggressive comments in the mock posts."

    @agent_tool(description="Return the post with the highest likes-to-views ratio")
    def highest_like_view_ratio(self) -> dict:
        post = max(self.posts, key=lambda item: item["likes"] / item["views"])
        result = {
            "post_id": post["id"],
            "likes": post["likes"],
            "views": post["views"],
            "ratio": post["likes"] / post["views"],
        }
        self.calls.append({"tool": "highest_like_view_ratio", "result": result})
        return result

    @agent_tool(description="Return the deliberately aggressive comment in the mock posts")
    def most_aggressive_comment(self) -> dict:
        for post in self.posts:
            for comment in post["comments"]:
                if "idiot" in comment["text"].lower() or "garbage" in comment["text"].lower():
                    result = {
                        "post_id": post["id"],
                        "comment_id": comment["id"],
                        "text": comment["text"],
                        "likes": comment["likes"],
                    }
                    self.calls.append({"tool": "most_aggressive_comment", "result": result})
                    return result
        raise RuntimeError("No aggressive comment found")


class ReplyOperator(AgentOperator):
    def __init__(self):
        self.replies: list[dict] = []
        super().__init__()

    @description
    def get_description(self) -> str:
        return "Send a reply to a post or comment."

    @agent_tool(description="Send one reply to a post or comment")
    async def reply(self, target_type: str, target_id: str, message: str) -> dict:
        """
        :param target_type: Either 'post' or 'comment'
        :param target_id: The post or comment ID to reply to
        :param message: Reply text
        """
        await asyncio.sleep(0.1)
        if target_type not in {"post", "comment"}:
            raise ValueError("target_type must be 'post' or 'comment'")
        result = {
            "status": "sent",
            "target_type": target_type,
            "target_id": target_id,
            "message": message,
        }
        self.replies.append(result)
        return result


async def main():
    client = None
    tool_calls: list[tuple[str, dict]] = []
    agent_events: list[AgentInvocationEvent] = []

    search_operator = SearchOperator(MOCK_POSTS)
    stat_operator = StatOperator(MOCK_POSTS)
    reply_operator = ReplyOperator()

    try:
        port = os.getenv("PORT", "7777")
        await DynamicAgentClient.connect(server_addr=f"http://localhost:{port}")

        client = await DynamicAgentClient.create(
            setting=(
                "You are the coordinating main agent. Use SubagentOperator for this task. "
                "Initialize a subagent before triggering it, wait for its report, and pass "
                "the relevant IDs from the first subagent report into the second subagent task."
            ),
            session_id=f"smoke-subagent-two-{uuid4().hex[:8]}",
            persist=False,
        )
        def on_event(event: AgentEvent) -> None:
            if isinstance(event, AgentInvocationEvent):
                agent_events.append(event)
            elif isinstance(event, ToolExecutionEvent) and event.status == "started":
                tool_calls.append((event.name, event.arguments))

        registration = await client.add_operator(SubagentOperator([
            search_operator,
            stat_operator,
            reply_operator,
        ]))
        print(f"subagent operator registered: {registration}")

        response = await client.trigger(
            "Perform this workflow exactly:\n"
            "1. Initialize one subagent named analyst with SearchOperator and StatOperator. "
            "Its setting should make it a careful social-post analyst.\n"
            "2. Trigger analyst. Require it to call search_keyword with 'all', rank posts by "
            "comment_count, and call see_comment for exactly the three posts with the highest "
            "comment counts. It must check only those comments for insults, call both statistics "
            "tools, and report exactly two targets: the post_id with the highest likes/views "
            "ratio, plus whether an inspected comment contains a direct insult and its comment_id.\n"
            "3. After analyst finishes, initialize a second subagent named responder with only "
            "ReplyOperator.\n"
            "4. Trigger responder with the exact IDs from analyst's report. Require it to send "
            "a thank-you reply to the highest-ratio post and a polite 'please do not do that' "
            "reply to the aggressive comment.\n"
            "5. Return a concise summary of both sent replies.",
            on_event=on_event,
        )
        print(f"response: {response}")

        called_names = [name for name, _ in tool_calls]
        assert called_names.count("SubagentOperator_init_subagent") == 2
        assert called_names.count("SubagentOperator_trigger_subagent") == 2
        assert "SearchOperator_search_keyword" in called_names
        assert "SearchOperator_see_comment" in called_names
        assert "StatOperator_highest_like_view_ratio" in called_names
        assert "StatOperator_most_aggressive_comment" in called_names
        assert called_names.count("ReplyOperator_reply") == 2

        assert search_operator.calls, "expected the analyst to search posts"
        comment_fetches = [
            call["post_id"]
            for call in search_operator.calls
            if call["tool"] == "see_comment"
        ]
        assert len(comment_fetches) == 3
        assert set(comment_fetches) == {"post-02", "post-04", "post-08"}, (
            f"expected comments only from the top-three posts, got {comment_fetches}"
        )
        assert stat_operator.calls, "expected the analyst to calculate statistics"
        assert len(reply_operator.replies) == 2

        expected_post_id = "post-02"
        expected_comment_id = "comment-04-a"
        post_reply = next(reply for reply in reply_operator.replies if reply["target_type"] == "post")
        comment_reply = next(reply for reply in reply_operator.replies if reply["target_type"] == "comment")
        assert post_reply["target_id"] == expected_post_id
        assert "thank" in post_reply["message"].lower()
        assert comment_reply["target_id"] == expected_comment_id
        assert "please" in comment_reply["message"].lower()
        assert "not" in comment_reply["message"].lower() or "don't" in comment_reply["message"].lower()

        subagent_finishes = [
            event for event in agent_events
            if event.finished and event.parent_runner_id
        ]
        assert len(subagent_finishes) == 2
        assert all(event.parent_tool_call_id for event in subagent_finishes)
        assert response, "expected a final main-agent response"

        print("ALL PASSED")
    finally:
        if client is not None:
            await client.close()
        await ServiceHandler.stop()


if __name__ == "__main__":
    asyncio.run(main())
