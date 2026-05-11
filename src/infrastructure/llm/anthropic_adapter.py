import anthropic
from typing import Optional, Dict, Any
from src.domain.interfaces.i_llm_service import ILLMService


class AnthropicAdapter(ILLMService):
    """Anthropic Claude implementation of LLM service"""

    def __init__(self, api_key: str, model: str = "claude-3-sonnet-20240229"):
        self.api_key = api_key
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key)

    async def generate_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Generate response using Anthropic Claude"""
        try:
            # Build system prompt
            system_prompt = "You are a helpful business chatbot assistant. Provide accurate and helpful responses about business data and analytics."

            # Add retrieved context if available
            if context and 'retrieved_context' in context and context['retrieved_context']:
                system_prompt += f"\n\nUse this retrieved context to provide accurate information:\n{context['retrieved_context']}"

            # Build conversation history
            conversation_parts = []

            # Add conversation history if provided
            if context and 'conversation_history' in context:
                for msg in context['conversation_history']:
                    role = msg['role']
                    if role == 'assistant':
                        role = 'assistant'
                    elif role == 'user':
                        role = 'user'
                    conversation_parts.append(f"{role}: {msg['content']}")

            # Add current user message
            conversation_parts.append(f"user: {prompt}")

            # Combine into full prompt
            full_prompt = "\n\n".join(conversation_parts)

            # Call Anthropic API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                temperature=0.7,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": full_prompt}
                ]
            )

            return response.content[0].text.strip()

        except Exception as e:
            raise Exception(f"Anthropic API error: {str(e)}")

    async def analyze_intent(self, message: str) -> str:
        """Analyze intent of user message"""
        try:
            prompt = f"""
            Analyze the intent of this user message and classify it into one of these categories:
            - revenue: questions about income, sales, earnings
            - profit: questions about profit, loss, margins
            - customer: questions about customers, clients, users
            - inventory: questions about stock, products, inventory
            - sales: questions about sales transactions, orders
            - trend: questions about changes, trends, growth
            - comparison: questions comparing different things
            - report: requests for reports, summaries, analysis
            - general: general conversation or other topics

            Message: "{message}"

            Return only the category name, nothing else.
            """

            response = self.client.messages.create(
                model=self.model,
                max_tokens=50,
                temperature=0.1,
                system="You are an intent classification assistant. Return only the category name.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            intent = response.content[0].text.strip().lower()
            return intent

        except Exception as e:
            return "general"  # fallback