"""Stream parsers turn recorded provider frames into text and tool calls."""

from alex.llm.parse import AnthropicStreamParser, OllamaStreamParser, OpenAIStreamParser


def test_openai_assembles_streamed_tool_call():
    parser = OpenAIStreamParser()
    lines = [
        'data: {"choices":[{"index":0,"delta":{"content":"Checking."},"finish_reason":null}]}',
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"remember","arguments":""}}]}}]}',
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"content\\": \\"tea\\"}"}}]}}]}',
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    events = []
    for line in lines:
        events.extend(parser.feed_line(line))
    kinds = [event.kind for event in events]
    assert kinds[0] == "text"
    assert events[0].text == "Checking."
    tool = next(event for event in events if event.kind == "tool_call")
    assert tool.name == "remember"
    assert tool.arguments == {"content": "tea"}
    assert tool.call_id == "call_1"
    assert sum(1 for event in events if event.kind == "tool_call") == 1


def test_anthropic_text_and_tool():
    parser = AnthropicStreamParser()
    lines = [
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"On it."}}',
        'data: {"type":"content_block_stop","index":0}',
        'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_1","name":"web_search","input":{}}}',
        'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"query\\": \\"arc reactor\\"}"}}',
        'data: {"type":"content_block_stop","index":1}',
        'data: {"type":"message_stop"}',
    ]
    events = []
    for line in lines:
        events.extend(parser.feed_line(line))
    assert events[0].text == "On it."
    tool = events[1]
    assert tool.name == "web_search"
    assert tool.arguments["query"] == "arc reactor"
    assert tool.call_id == "toolu_1"


def test_ollama_tool_call_object_arguments():
    parser = OllamaStreamParser()
    events = parser.feed_line(
        '{"message":{"role":"assistant","content":"","tool_calls":[{"function":{"name":"get_time","arguments":{}}}]},"done":false}'
    )
    assert events[0].kind == "tool_call"
    assert events[0].name == "get_time"
    assert events[0].arguments == {}
