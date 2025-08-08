import asyncio
import multiprocessing
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, List, Tuple

import boto3
import requests
from boto3.dynamodb.conditions import Key, Attr
from sqlalchemy.orm import Session
from twilio.rest import Client

from src.models.feedback import Feedback
from src.services.llm_service import LLM
from src.utils.logger import get_logger

logger = get_logger(__name__)

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
s3 = boto3.client("s3", region_name="us-east-1")
session_table = dynamodb.Table("sessions")
chat_table = dynamodb.Table("chats")


thread_pool = ThreadPoolExecutor(max_workers=multiprocessing.cpu_count())


class ChatService:
    def __init__(self, config: Dict[str, Any], db=None):
        """Initialize ChatService with Twilio and AWS configuration."""
        if not config:
            raise ValueError("Configuration is required")

        self.account_sid = config.get("TWILIO_ACCOUNT_SID")
        self.auth_token = config.get("TWILIO_AUTH_TOKEN")
        self.from_number = config.get("TWILIO_WHATSAPP_FROM")
        self.s3_bucket_name = config.get("S3_BUCKET_NAME")
        self.db = db

        # Validate configs
        if not self.s3_bucket_name:
            raise ValueError("S3_BUCKET_NAME is required in configuration")
        if not all([self.account_sid, self.auth_token, self.from_number]):
            raise ValueError(
                "Missing required Twilio configurations. "
                "Please set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_WHATSAPP_FROM"
            )

        self.client = Client(self.account_sid, self.auth_token)
        self.llm = LLM(config)

    def save_feedback_data(self, feedback_data: Dict[str, Any]):
        """Save feedback data using SQLAlchemy model."""
        try:
            feedback = Feedback(
                sender_id=feedback_data.get("sender_id"),
                product_name=feedback_data.get("product_name"),
                feedback_text=feedback_data.get("feedback_text"),
                media_urls=feedback_data.get("media_urls", []),
            )
            self.db.add(feedback)
            self.db.commit()
            self.db.refresh(feedback)

            return feedback
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to save feedback", error=str(e))
            raise

    async def upload_to_s3(
        self, content: bytes, message_sid: str, media_sid: str, content_type: str
    ) -> Optional[str]:
        """Upload media content to S3 and return the S3 URL."""
        try:
            extension = content_type.split("/")[-1]
            s3_key = f"feedback-media/{message_sid}/{media_sid}.{extension}"

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                thread_pool,
                lambda: s3.put_object(
                    Bucket=self.s3_bucket_name,
                    Key=s3_key,
                    Body=content,
                    ContentType=content_type,
                    CacheControl="max-age=31536000",  # Cache for 1 year
                ),
            )

            s3_url = f"https://{self.s3_bucket_name}.s3.amazonaws.com/{s3_key}"
            logger.info(
                "Media uploaded to S3",
                message_sid=message_sid,
                media_sid=media_sid,
                s3_url=s3_url,
            )
            return s3_url
        except Exception as e:
            logger.error(
                "Failed to upload media to S3",
                message_sid=message_sid,
                media_sid=media_sid,
                error=str(e),
            )
            return None

    async def download_single_media(self, url: str) -> Optional[Dict[str, Any]]:
        """Download a single media file from Twilio and upload to S3."""
        try:
            # Extract IDs
            parts = url.split("/")
            message_sid = parts[-3]
            media_sid = parts[-1]

            loop = asyncio.get_event_loop()

            # Get media list
            media_list = await loop.run_in_executor(
                thread_pool, lambda: self.client.messages(message_sid).media.list()
            )

            media_url = None
            for media in media_list:
                if media.sid == media_sid:
                    media_url = (
                        f"https://api.twilio.com{media.uri.replace('.json', '')}"
                    )
                    break
            if not media_url:
                raise ValueError(f"Media not found: {media_sid}")

            # Download content
            response = await loop.run_in_executor(
                thread_pool,
                lambda: requests.get(
                    media_url, auth=(self.account_sid, self.auth_token), stream=True
                ),
            )
            response.raise_for_status()
            content = await loop.run_in_executor(thread_pool, lambda: response.content)

            # Upload to S3
            s3_url = await self.upload_to_s3(
                content=content,
                message_sid=message_sid,
                media_sid=media_sid,
                content_type=response.headers.get(
                    "Content-Type", "application/octet-stream"
                ),
            )

            return {"s3_url": s3_url} if s3_url else None
        except Exception as e:
            logger.error("Failed to download media", url=url, error=str(e))
            return None

    async def download_media_files(self, feedback_data: Dict[str, Any]) -> None:
        """Download media files and save feedback data."""
        media_urls = feedback_data.get("media_urls", [])

        feedback_model_data = {
            "sender_id": feedback_data.get("sender_id"),
            "product_name": feedback_data.get("product_name"),
            "feedback_text": feedback_data.get("feedback_text"),
            "media_urls": feedback_data.get("media_urls", []),
        }

        if len(media_urls) > 0:
            tasks = [self.download_single_media(url) for url in media_urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            saved_urls = [r.get("s3_url") for r in results if r and r.get("s3_url")]
            feedback_model_data["media_urls"] = saved_urls

        self.save_feedback_data(feedback_model_data)

    async def send_whatsapp_message(
        self, from_number: str, to_number: str, reply_message: str
    ):
        """Send WhatsApp message using Twilio."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            thread_pool,
            lambda: self.client.messages.create(
                from_=from_number, body=reply_message, to=to_number
            ),
        )

    async def save_chat_message(self, message_data: Dict[str, Any]):
        """Save chat message to DynamoDB."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            thread_pool, lambda: chat_table.put_item(Item=message_data)
        )

    def mark_session_as_limited(self, session_id: str, user_limited_until: str):
        """Mark a user's session as limited in DynamoDB."""
        session_table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET #user_limited_until = :user_limited_until, updated_at = :updated_at",
            ExpressionAttributeNames={"#user_limited_until": "user_limited_until"},
            ExpressionAttributeValues={
                ":user_limited_until": user_limited_until,
                ":updated_at": int(time.time()),
            },
            ReturnValues="ALL_NEW",
        )
        logger.info(
            "Session marked as limited",
            session_id=session_id,
            user_limited_until=user_limited_until,
        )

    def mark_session_as_completed(
        self, sender_id: str, session_id: str, reopen_session: bool = False
    ):
        """Mark a user's session as completed in DynamoDB."""
        try:
            if reopen_session:
                new_session_id = str(uuid.uuid4())
                session_table.put_item(
                    Item={
                        "session_id": new_session_id,
                        "sender_id": sender_id,
                        "status": "active",
                        "created_at": int(time.time()),
                    }
                )
                return new_session_id

            session_table.update_item(
                Key={"session_id": session_id},
                UpdateExpression="SET #status = :status, updated_at = :updated_at",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":status": "completed",
                    ":updated_at": int(time.time()),
                },
                ReturnValues="ALL_NEW",
            )
            logger.info("Session marked as completed", session_id=session_id)
            return session_id
        except Exception as e:
            logger.error(
                "Failed to mark session as completed",
                error=str(e),
                session_id=session_id,
            )
            raise

    def get_user_unresolved_session_message(
        self, sender_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch the active session and all its messages."""
        try:
            session_response = session_table.query(
                IndexName="SenderSessionsIndex",
                KeyConditionExpression=Key("sender_id").eq(sender_id),
                FilterExpression=Attr("status").eq("active"),
                ScanIndexForward=False,
                Limit=1,
            )
            sessions = session_response.get("Items", [])
            if not sessions:
                logger.info("No active session found", sender_id=sender_id)
                return None

            active_session = sessions[0]
            session_id = active_session["session_id"]

            # Fetch all messages for session
            messages, last_key = [], None
            while True:
                query = {
                    "IndexName": "SessionIndex",
                    "KeyConditionExpression": Key("session_id").eq(session_id),
                    "ScanIndexForward": True,
                }
                if last_key:
                    query["ExclusiveStartKey"] = last_key

                response = chat_table.query(**query)
                messages.extend(response.get("Items", []))
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break

            if not messages:
                logger.info(
                    "No messages for session",
                    sender_id=sender_id,
                    session_id=session_id,
                )
                return None

            transformed = []
            for msg in messages:
                content = msg.get("content", {})
                direction = (
                    "inbound" if msg.get("chat_type") == "inbound" else "outbound"
                )

                if text := content.get("text"):
                    transformed.append(
                        {"type": "text", "text": text, "direction": direction}
                    )
                for media in content.get("media_items", []):
                    transformed.append(
                        {
                            "type": "media",
                            "url": media.get("url"),
                            "direction": direction,
                        }
                    )

            logger.info(
                "User session messages retrieved",
                message_count=len(transformed),
                sender_id=sender_id,
                session_id=session_id,
            )
            return {"messages": transformed, "session_id": session_id}
        except Exception as e:
            logger.error(
                "Failed to get unresolved session messages",
                error=str(e),
                sender_id=sender_id,
            )
            raise

    async def get_reply_message(
        self, sender_id: str
    ) -> Tuple[str, str, bool, str, bool, Dict[str, Any]]:
        """Generate reply for user conversation and return full session info."""
        conversation = self.get_user_unresolved_session_message(sender_id)
        if not conversation:
            session_id = str(uuid.uuid4())
            session_table.put_item(
                Item={
                    "session_id": session_id,
                    "sender_id": sender_id,
                    "status": "active",
                    "created_at": int(time.time()),
                }
            )
            logger.info(
                "Created new session", session_id=session_id, sender_id=sender_id
            )
            conversation = {"messages": [], "session_id": session_id}
        else:
            session_id = conversation.get("session_id")

        result = await self.llm.analyze_conversation(messages=conversation["messages"])
        feedback_data = {}

        if result.get("is_feedback_session_complete", False):
            feedback_data = {
                "product_name": result.get("product_name", ""),
                "feedback_text": result.get("feedback", ""),
                "media_urls": result.get("media_urls", []),
            }

        reply = result.get("reply", "")
        should_persist_reply = result.get("should_persist_reply", True)
        is_feedback_session_complete = result.get("is_feedback_session_complete", False)
        user_limited_until = result.get("user_limited_until", None)
        reopen_session = result.get("reopen_session", False)
        reply_stage = result.get("reply_stage", 0)

        if is_feedback_session_complete and session_id:
            self.mark_session_as_completed(sender_id, session_id)
        if reopen_session and session_id:
            session_id = self.mark_session_as_completed(sender_id, session_id, True)
        if user_limited_until and session_id:
            self.mark_session_as_limited(session_id, user_limited_until)

        return (
            reply,
            session_id,
            should_persist_reply,
            reply_stage,
            is_feedback_session_complete,
            feedback_data,
        )

    async def reply_user(self, sender_id: str) -> Dict[str, str]:
        """Send a WhatsApp reply to the user and optionally save to DB and S3."""
        try:
            receiver_id = f"+{sender_id}"
            (
                reply_message,
                session_id,
                should_persist_reply,
                reply_stage,
                is_feedback_session_complete,
                feedback_data,
            ) = await self.get_reply_message(sender_id)

            from_number = (
                self.from_number
                if self.from_number.startswith("whatsapp:")
                else f"whatsapp:{self.from_number}"
            )
            to_number = (
                receiver_id
                if receiver_id.startswith("whatsapp:")
                else f"whatsapp:{receiver_id}"
            )

            # Generate message_id
            message_id = str(uuid.uuid4())
            timestamp = int(time.time())

            chat_data = {
                "sender_id": sender_id,
                "message_id": message_id,
                "chat_type": "outbound",
                "session_id": session_id,
                "created_at": timestamp,
                "content": {
                    "text": reply_message,
                    "media_count": 0,
                    "segments": 1,
                    "reply_stage": reply_stage,
                },
                "metadata": {"message_id": message_id, "status": "sent"},
            }

            whatsapp_task = self.send_whatsapp_message(
                from_number, to_number, reply_message
            )
            save_task = (
                self.save_chat_message(chat_data) if should_persist_reply else None
            )

            tasks = [whatsapp_task] + ([save_task] if save_task else [])

            if is_feedback_session_complete:
                feedback_data["sender_id"] = sender_id
                tasks.append(self.download_media_files(feedback_data))

            await asyncio.gather(*tasks, return_exceptions=True)

            return {
                "session_id": session_id,
                "message_id": message_id,
                "status": "sent",
            }
        except Exception as e:
            logger.error(
                "Failed to send WhatsApp message", error=str(e), receiver_id=sender_id
            )
            raise
