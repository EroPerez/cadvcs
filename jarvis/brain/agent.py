import anthropic
from ..config import ANTHROPIC_API_KEY, JARVIS_MODEL, JARVIS_NAME
from .prompts import SYSTEM_PROMPT
from ..tools.registry import TOOL_DEFINITIONS, execute_tool
from ..memory.history import ConversationHistory


class JarvisAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.history = ConversationHistory()
        self.system_prompt = SYSTEM_PROMPT.format(name=JARVIS_NAME)

    def chat(self, user_message: str) -> str:
        self.history.add("user", user_message)
        messages = self.history.get_messages()

        for _ in range(10):  # safety limit on tool use loops
            response = self.client.messages.create(
                model=JARVIS_MODEL,
                max_tokens=4096,
                system=self.system_prompt,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})

                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = execute_tool(block.name, block.input)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(result),
                            }
                        )

                messages.append({"role": "user", "content": tool_results})

            elif response.stop_reason == "end_turn":
                text = "".join(
                    block.text for block in response.content if hasattr(block, "text")
                )
                self.history.add("assistant", text)
                return text

            else:
                return f"Respuesta inesperada: {response.stop_reason}"

        return "Se alcanzó el límite de iteraciones de herramientas."
