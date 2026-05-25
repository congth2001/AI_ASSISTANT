from openai import AsyncOpenAI
from typing import Optional, Dict, Any
from src.domain.interfaces.i_llm_service import ILLMService


class OpenAIAdapter(ILLMService):
    """OpenAI implementation of LLM service"""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key)

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
            retrieved = context.get('retrieved_text', None)
            if context and retrieved:
                system_message = f"""
                Bạn là một trợ lý chatbot chuyên về phân tích kinh doanh. Sử dụng thông tin ngữ cảnh được truy xuất dưới đây để cung cấp câu trả lời chính xác và hữu ích cho người dùng:

                {retrieved}

                Trả lời câu hỏi của người dùng dựa trên ngữ cảnh này dưới kiến thức tổng quát của bạn.
                """
                messages.insert(0, {"role": "system", "content": system_message})
            else:
                messages.insert(0, {
                    "role": "system",
                    "content": "Bạn là một trợ lý chatbot chuyên về phân tích kinh doanh. Hãy trả lời các câu hỏi của người dùng một cách chính xác và hữu ích."
                })

            # Call OpenAI API
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_completion_tokens=1000,
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            raise Exception(f"OpenAI API error: {str(e)}")

    async def analyze_intent(self, message: str) -> str:
        """Analyze intent of user message"""
        try:
            prompt = f"""
            Phân tích ý định của tin nhắn người dùng này và phân loại nó vào một trong những danh mục sau:
            - revenue: câu hỏi về doanh thu, bán hàng, lợi nhuận
            - profit: câu hỏi về lợi nhuận, lỗ, biên lợi nhuận
            - customer: câu hỏi về khách hàng, đối tác, người dùng
            - inventory: câu hỏi về kho hàng, sản phẩm, tồn kho
            - sales: câu hỏi về giao dịch bán hàng, đơn đặt hàng
            - trend: câu hỏi về các thay đổi, xu hướng, tăng trưởng
            - comparison: câu hỏi so sánh các thứ khác nhau
            - report: yêu cầu báo cáo, tóm tắt, phân tích
            - general: cuộc trò chuyện tổng quát hoặc các chủ đề khác

            Message: "{message}"

            Return only the category name, nothing else.
            """

            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=50,
            )

            intent = response.choices[0].message.content.strip().lower()
            return intent

        except Exception as e:
            return "general"  # fallback