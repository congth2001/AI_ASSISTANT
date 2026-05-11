from typing import Optional, Dict, Any, List
from uuid import UUID
from src.domain.entities.message import Message, Conversation
from src.domain.interfaces.i_llm_service import ILLMService
from src.domain.interfaces.i_conversation_repository import IConversationRepository
from src.domain.services.intent_classifier import IntentClassifier
from src.domain.services.context_builder import ContextBuilder


class ChatUseCase:
    """Use case for handling chat interactions"""

    def __init__(
        self,
        llm_service: ILLMService,
        conversation_repo: IConversationRepository,
        intent_classifier: IntentClassifier,
        context_builder: ContextBuilder
    ):
        self.llm_service = llm_service
        self.conversation_repo = conversation_repo
        self.intent_classifier = intent_classifier
        self.context_builder = context_builder

    async def execute(self, conversation_id: UUID, user_message: str) -> Dict[str, Any]:
        """Execute chat interaction"""
        # Get or create conversation
        conversation_data = await self.conversation_repo.get_conversation(conversation_id)
        if not conversation_data:
            # Create new conversation
            conversation_data = await self.conversation_repo.create_conversation({
                'id': str(conversation_id),
                'title': f"Chat {conversation_id}"[:50]  # Truncate title
            })

        # Convert to domain entities
        conversation = self._dict_to_conversation(conversation_data)

        # Classify intent
        intent = self.intent_classifier.classify(user_message)

        # Build context
        context = self.context_builder.build_context(conversation.messages, user_message)
        context['intent'] = intent.value

        # Generate response using LLM
        response_content = await self.llm_service.generate_response(user_message, context)

        # Create user message entity
        user_msg = Message(
            conversation_id=conversation_id,
            content=user_message,
            role='user'
        )

        # Create assistant message entity
        assistant_msg = Message(
            conversation_id=conversation_id,
            content=response_content,
            role='assistant'
        )

        # Add messages to conversation
        conversation.add_message(user_msg)
        conversation.add_message(assistant_msg)

        # Save messages to repository
        await self.conversation_repo.add_message(conversation_id, self._message_to_dict(user_msg))
        await self.conversation_repo.add_message(conversation_id, self._message_to_dict(assistant_msg))

        # Update conversation title if it's the first message
        if len(conversation.messages) == 2:  # First user message + response
            title = self._generate_title(user_message)
            await self.conversation_repo.update_conversation(conversation_id, {'title': title})

        return {
            'conversation_id': str(conversation_id),
            'response': response_content,
            'intent': intent.value,
            'timestamp': assistant_msg.timestamp.isoformat()
        }

    def _dict_to_conversation(self, data: Dict[str, Any]) -> Conversation:
        """Convert dict to Conversation entity"""
        messages_data = data.get('messages', [])
        messages = []
        for msg_data in messages_data:
            msg = Message(
                id=UUID(msg_data['id']) if msg_data.get('id') else None,
                conversation_id=UUID(data['id']),
                content=msg_data['content'],
                role=msg_data['role'],
                timestamp=msg_data.get('timestamp')
            )
            messages.append(msg)

        return Conversation(
            id=UUID(data['id']),
            user_id=data.get('user_id'),
            title=data.get('title'),
            messages=messages,
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            metadata=data.get('metadata')
        )

    def _message_to_dict(self, message: Message) -> Dict[str, Any]:
        """Convert Message entity to dict"""
        return {
            'id': str(message.id) if message.id else None,
            'conversation_id': str(message.conversation_id),
            'content': message.content,
            'role': message.role,
            'timestamp': message.timestamp.isoformat() if message.timestamp else None,
            'metadata': message.metadata
        }

    def _generate_title(self, first_message: str) -> str:
        """Generate conversation title from first message"""
        words = first_message.split()[:5]  # First 5 words
        title = ' '.join(words)
        if len(title) > 50:
            title = title[:47] + '...'
        return title or "New Conversation"