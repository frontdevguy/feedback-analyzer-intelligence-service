import json
from typing import List, Dict, Any
from openai import AsyncOpenAI, APIStatusError, RateLimitError
from src.utils.logger import get_logger
import datetime
import asyncio

logger = get_logger(__name__)


class LLM:
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize LLM service with OpenAI configuration.

        Args:
            config: Configuration dictionary containing OpenAI settings
        """
        if not config:
            raise ValueError("Configuration is required")

        self.api_key = config.get("OPENAI_API_KEY")
        self.model = config.get("OPENAI_MODEL", "gpt-4.1")
        # self.temperature = float(config.get("OPENAI_TEMPERATURE", "0.1"))
        # self.max_tokens = int(config.get("OPENAI_MAX_TOKENS", "1000"))

        if not self.api_key:
            logger.error("Missing OpenAI API key")
            raise ValueError("OPENAI_API_KEY is required in configuration")

        self.client = AsyncOpenAI(api_key=self.api_key)

        self.system_prompt = """

You are an AI-powered message interpretation engine for a WhatsApp-based customer feedback analyzer.

You will analyze a chronological list of messages exchanged between a user and the system. Each message includes:
- `type`: either "text" or "media"
- `text` or `url`: based on the message type
- `direction`: either "inbound" (from user) or "outbound" (from system)

Analyze the entire conversation contextually and return strictly a single JSON object structured exactly as follows:

{
  "is_product_name_present": boolean,
  "is_feedback_present": boolean,
  "did_user_confirm_media_availability": boolean,
  "is_media_present": boolean,
  "reply": string,
  "product_name": string,
  "feedback": string,
  "media_urls": string[],
  "is_feedback_session_complete": boolean,
  "is_x_rated_conversation": boolean,
  "is_crime_rated_conversation": boolean,
  "is_immoral_conversation": boolean,
  "is_too_short": boolean,
  "is_irrelevant": boolean,
  "reply_stage": product_name, feedback, media, complete
}

### Field Definitions:
- is_product_name_present: true if user mentions a valid Apple product (generic or model-specific) from the allowed list below, in correct context. 
If the name provided is misspelled or unclear but closely resembles an allowed product, suggest the closest match in the reply and assume the intended product_name.
If a word is generic but context suggests a product (e.g., "mac" → "MacBook"), assume the most likely Apple product.

Allowed products:
iPhone, iPhone SE, iPhone mini, iPhone Plus, iPhone Pro, iPhone Pro Max,
MacBook, MacBook Air, MacBook Pro, iMac, Mac mini, Mac Studio, Mac Pro,
Apple Watch, Apple Watch Ultra, Apple Watch SE, Apple Watch Nike, Apple Watch Hermès,
iPad, iPad Air, iPad Pro, iPad mini,
AirPods, AirPods Pro, AirPods Max, EarPods,
Beats, Beats Studio, Beats Studio Pro, Beats Studio Buds, Beats Studio Buds+, Beats Fit Pro, Beats Solo, Beats Solo3, Beats Flex,
Apple TV, Apple TV 4K, HomePod, HomePod mini,
Magic Keyboard, Magic Mouse, Magic Trackpad, Apple Pencil, MagSafe Charger, MagSafe Battery Pack,
Smart Keyboard, Smart Keyboard Folio, Smart Cover, Smart Folio,
USB-C Cable, USB-C to Lightning Cable, Lightning Cable, USB Cable, Power Adapter, Wall Charger, Charging Brick, USB-C Power Adapter, Lightning to 3.5mm Adapter, EarPods with Lightning Connector, EarPods with 3.5mm Connector
- `is_feedback_present`: True if the user clearly provides an opinion, suggestion, or comment about the product.
- `did_user_confirm_media_availability`: True if both product name and feedback are present and the user explicitly confirms sending/intending to send media, or media is already provided.
- `is_media_present`: True if at least one inbound media (image) message exists.
- `is_feedback_session_complete`: True if product name, feedback, and media (if indicated) are all fully provided.
- `reply`: A concise, polite, and neutral instruction guiding the user's next action based on conversation status.
- `product_name`: The exact product name mentioned by the user; empty if absent.
- `feedback`: The exact feedback provided by the user; empty if absent.
- `media_urls`: URLs of up to 1 inbound media image; empty array if no valid media.
- `is_x_rated_conversation`: True if user content contains explicit, offensive, or sexual language.
- `is_crime_rated_conversation`: True if user content references illegal activities (theft, fraud, threats, etc.).
- `is_immoral_conversation`: True if user content involves morally questionable ideas or language (hate speech, unethical behaviors).
- `is_too_short`: True if user's latest inbound text message contains fewer than 100 characters (excluding whitespace).
- `is_irrelevant`: True if user's messages are clearly unrelated to product feedback/support (e.g., "I am Jesus").
- `reply_stage`: 'product_name' if asking for product name, 'feedback' if asking for feedback, 'media' if asking for media, 'complete' if feedback session is complete or other scenarios.

### Additional Instructions & Edge Cases:
- If product name is missing, explicitly prompt for product name.
- if product name is not satisfied Ask user to provide the name of the apple product. IT MUST BE A PRODUCT FROM APPLE INC.
- If it's user's first inbound message and contains a greeting, begin your reply with a casual greeting.
- If feedback is missing, explicitly prompt the user for feedback.
- Only prompt for media if product name and feedback are present.
- Explicitly inform the user that only images are supported, with a maximum of 1 image processed, regardless of how many images are sent.
- If media is confirmed or already provided, do not prompt again for media.
- If the user sends non-image media (e.g., video or audio), explicitly instruct them that only images are supported.
- If media is not intended, explicitly instruct the user to respond with "No Image."
- If the conversation includes explicit, illegal, immoral, irrelevant, or inappropriate content, politely redirect the user to send only relevant messages.
- If user's messages are too short or unclear, explicitly prompt the user to provide more specific and detailed information.
- If a user repeatedly ignores instructions or sends irrelevant content after multiple prompts, politely remind them about the purpose of the conversation.
- Do not thank or acknowledge the user prematurely. Only thank them concisely when the feedback session (product name, feedback, and media if applicable) is fully completed. Do not prompt for additional feedback.
- Always return strictly the specified JSON object without additional explanations, formatting, or content.
- User can respond with "No Image" to indicate that they have no media to support their feedback.
- Do not thank the user for their response to every message. Only thank them when the feedback session is complete.
- Do no ask the user to send more feedback at the end of the conversation. Just thank them and mention their feedback has been received and session is complete.
- Do not thank the user for providing the product name.

        """.strip()

        logger.info(
            "LLM service initialized",
            model=self.model,
            # temperature=self.temperature,
            # max_tokens=self.max_tokens,
        )

    def _convert_messages_to_string(self, messages: List[Dict[str, Any]]) -> str:
        """
        Convert structured WhatsApp messages to LLM-readable dialogue format.
        """
        output = []
        for msg in messages:
            if msg["type"] == "text":
                output.append(f"{msg['direction'].capitalize()}: {msg['text']}")
            elif msg["type"] == "media":
                output.append(f"{msg['direction'].capitalize()}: [Media] {msg['url']}")
        return "\n".join(output)

    async def analyze_conversation(
        self, messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze a WhatsApp conversation and return extracted feedback details.

        Args:
            messages: List of WhatsApp message objects

        Returns:
            A structured JSON object with feedback analysis
        """
        try:
            # Check if any message exceeds 1000 characters
            for msg in messages:
                if msg["type"] == "text" and msg.get("text"):
                    if len(msg["text"]) > 1000:
                        logger.warning(
                            "Message exceeds character limit",
                            message_length=len(msg["text"]),
                            direction=msg.get("direction", "unknown"),
                        )
                        return {
                            "is_product_name_present": False,
                            "is_feedback_present": False,
                            "did_user_confirm_media_availability": False,
                            "is_media_present": False,
                            "reply": "Message too long. Please shorten it to under 1000 characters and try again.",
                            "product_name": "",
                            "feedback": "",
                            "media_url": "",
                            "is_feedback_session_complete": False,
                            "is_x_rated_conversation": False,
                            "is_crime_rated_conversation": False,
                            "is_immoral_conversation": False,
                            "is_too_short": False,
                            "is_irrelevant": False,
                            "should_persist_reply": True,
                        }

            user_message_content = self._convert_messages_to_string(messages)

            response = None
            max_attempts = 3
            wait_seconds = 1
            for attempt_index in range(max_attempts):
                try:
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": self.system_prompt},
                            {"role": "user", "content": user_message_content},
                        ],
                        # temperature=self.temperature,
                        # max_tokens=self.max_tokens,
                        response_format={"type": "json_object"},
                    )
                    break
                except RateLimitError:
                    if attempt_index < max_attempts - 1:
                        logger.warning(
                            "OpenAI rate limited; retrying",
                            attempt=attempt_index + 1,
                            max_attempts=max_attempts,
                            wait_seconds=wait_seconds,
                        )
                        await asyncio.sleep(wait_seconds)
                        continue
                    raise
                except APIStatusError as e:
                    if e.status_code == 429 and attempt_index < max_attempts - 1:
                        logger.warning(
                            "OpenAI 429; retrying",
                            attempt=attempt_index + 1,
                            max_attempts=max_attempts,
                            wait_seconds=wait_seconds,
                        )
                        await asyncio.sleep(wait_seconds)
                        continue
                    raise

            result = json.loads(response.choices[0].message.content)

            logger.info(
                "Feedback analysis generated",
                result=result,
            )

            if (
                result.get("is_x_rated_conversation", False)
                or result.get("is_crime_rated_conversation", False)
                or result.get("is_immoral_conversation", False)
                or result.get("is_irrelevant", False)
            ):
                result["should_persist_reply"] = False
                result["reply"] = (
                    "We detected misuse of the system, and your access has been temporarily suspended for 1 minute. Thank you for your understanding."
                )
                result["user_limited_until"] = (
                    datetime.datetime.now() + datetime.timedelta(minutes=1)
                ).isoformat()
                result["reopen_session"] = True

                return result

            # if (
            #     result.get("is_too_short", False)
            #     and int(result.get("reply_stage", 0)) == 1 # change to reply_stage #multiple immages, one reply only
            # ):
            #     result["should_persist_reply"] = False
            #     result["reply"] = (
            #         "Your message is too short. Please provide more context.."
            #     )
            #     return result

            return result

        except Exception as e:
            logger.error("Failed to analyze feedback", error=str(e))
            return {
                "is_product_name_present": False,
                "is_feedback_present": False,
                "did_user_confirm_media_availability": False,
                "is_media_present": False,
                "reply": "Failed to process your message. Please try again.",
                "product_name": "",
                "feedback": "",
                "media_url": "",
                "is_feedback_session_complete": False,
                "is_x_rated_conversation": False,
                "is_crime_rated_conversation": False,
                "is_immoral_conversation": False,
                "is_too_short": False,
                "is_irrelevant": False,
                "should_persist_reply": False,
            }
