import openai
from typing import Optional, Dict, Any
from src.domain.interfaces.i_llm_service import ILLMService


class OpenAIAdapter(ILLMService):
    """OpenAI implementation of LLM service"""

    def __init__(self, api_key: str, model: str = "gpt-5-nano"):
        self.api_key = api_key
        self.model = model
        openai.api_key = api_key

    async def generate_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Generate response using OpenAI"""
        try:
            # Build messages
            messages = []

            # Add system context if provided
            if context and 'conversation_history' in context:
                for msg in context['conversation_history']:
                    messages.append({
                        "role": msg['role'],
                        "content": msg['content']
                    })

            # Add current prompt
            messages.append({"role": "user", "content": prompt})

            # Add additional context if provided
            if context and 'retrieved_context' in context and context['retrieved_context']:
                system_message = f"""
                You are a business chatbot assistant. Use the following retrieved context to provide accurate information:

                {context['retrieved_context']}

                Answer the user's question based on this context and your general knowledge.
                """
                messages.insert(0, {"role": "system", "content": system_message})
            else:
                messages.insert(0, {
                    "role": "system",
                    "content": "You are a helpful business chatbot assistant. Provide accurate and helpful responses about business data and analytics."
                })

            # Call OpenAI API
            response = await openai.ChatCompletion.acreate(
                model=self.model,
                messages=messages,
                max_tokens=1000,
                temperature=0.7
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            raise Exception(f"OpenAI API error: {str(e)}")

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

            response = await openai.ChatCompletion.acreate(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,
                temperature=0.1
            )

            intent = response.choices[0].message.content.strip().lower()
            return intent

        except Exception as e:
            return "general"  # fallback