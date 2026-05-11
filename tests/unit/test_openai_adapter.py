"""
Unit tests for OpenAI adapter
Tests for generating responses and analyzing intent using OpenAI API
"""

import os
import sys
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT_DIR)

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.infrastructure.llm.openai_adapter import OpenAIAdapter

# Use a test API key placeholder - never commit real API keys
TEST_API_KEY = ""


class TestOpenAIAdapterInit:
    """Tests for OpenAIAdapter initialization"""

    def test_init_with_default_model(self):
        """Test initializing OpenAIAdapter with default model"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        assert adapter.api_key == TEST_API_KEY
        assert adapter.model == "gpt-4"

    def test_init_with_custom_model(self):
        """Test initializing OpenAIAdapter with custom model"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY, model="gpt-3.5-turbo")
        assert adapter.api_key == TEST_API_KEY
        assert adapter.model == "gpt-3.5-turbo"

    def test_init_sets_api_key(self):
        """Test that initialization sets the OpenAI API key"""
        with patch('openai.api_key'):
            adapter = OpenAIAdapter(api_key=TEST_API_KEY)


class TestGenerateResponse:
    """Tests for generate_response method"""

    @pytest.mark.asyncio
    async def test_generate_response_simple_prompt(self):
        """Test generating response with simple prompt"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY, model = "gpt=5-nano")
        
        # Mock OpenAI API response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "This is a test response"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response("What is 2+2?")
            print(response)
            
            assert response == "This is a test response"
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_response_with_context(self):
        """Test generating response with retrieved context"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Answer based on context"
        
        context = {
            'retrieved_context': 'The sky is blue because of Rayleigh scattering'
        }
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response("Why is the sky blue?", context=context)
            
            assert response == "Answer based on context"
            # Verify the system message was added with context
            call_args = mock_create.call_args
            messages = call_args.kwargs['messages']
            assert len(messages) >= 2
            assert 'system' in [msg['role'] for msg in messages]

    @pytest.mark.asyncio
    async def test_generate_response_with_conversation_history(self):
        """Test generating response with conversation history"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Follow-up response"
        
        context = {
            'conversation_history': [
                {'role': 'user', 'content': 'Hello'},
                {'role': 'assistant', 'content': 'Hi there!'}
            ]
        }
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response("What's your name?", context=context)
            
            assert response == "Follow-up response"
            # Verify conversation history was included
            call_args = mock_create.call_args
            messages = call_args.kwargs['messages']
            assert len(messages) >= 3  # system, history (2), current prompt

    @pytest.mark.asyncio
    async def test_generate_response_with_full_context(self):
        """Test generating response with both context and conversation history"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Comprehensive response"
        
        context = {
            'conversation_history': [
                {'role': 'user', 'content': 'Previous question'},
                {'role': 'assistant', 'content': 'Previous answer'}
            ],
            'retrieved_context': 'Relevant business data about quarterly revenue'
        }
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response("What was our revenue?", context=context)
            
            assert response == "Comprehensive response"
            call_args = mock_create.call_args
            messages = call_args.kwargs['messages']
            assert any('revenue' in msg.get('content', '').lower() for msg in messages)

    @pytest.mark.asyncio
    async def test_generate_response_without_context(self):
        """Test generating response without any context"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Generic response"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response("Hello")
            
            assert response == "Generic response"
            # Verify default system message was used
            call_args = mock_create.call_args
            messages = call_args.kwargs['messages']
            system_msg = [msg for msg in messages if msg['role'] == 'system'][0]
            assert 'business chatbot' in system_msg['content'].lower()

    @pytest.mark.asyncio
    async def test_generate_response_strips_whitespace(self):
        """Test that response content is stripped of whitespace"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "  Response with whitespace  \n"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response("Test")
            
            assert response == "Response with whitespace"
            assert not response.startswith(" ")
            assert not response.endswith(" ")

    @pytest.mark.asyncio
    async def test_generate_response_api_error(self):
        """Test handling of OpenAI API errors"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = Exception("API rate limit exceeded")
            
            with pytest.raises(Exception) as exc_info:
                await adapter.generate_response("Test prompt")
            
            assert "OpenAI API error" in str(exc_info.value)
            assert "API rate limit exceeded" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_generate_response_verifies_api_parameters(self):
        """Test that correct parameters are passed to OpenAI API"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY, model="gpt-4")
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            await adapter.generate_response("Test")
            
            call_args = mock_create.call_args
            assert call_args.kwargs['model'] == 'gpt-4'
            assert call_args.kwargs['max_tokens'] == 1000
            assert call_args.kwargs['temperature'] == 0.7


class TestAnalyzeIntent:
    """Tests for analyze_intent method"""

    @pytest.mark.asyncio
    async def test_analyze_intent_revenue(self):
        """Test intent analysis for revenue questions"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "revenue"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            intent = await adapter.analyze_intent("What is our total revenue?")
            
            assert intent == "revenue"

    @pytest.mark.asyncio
    async def test_analyze_intent_profit(self):
        """Test intent analysis for profit questions"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "  PROFIT  "
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            intent = await adapter.analyze_intent("What is our profit margin?")
            
            assert intent == "profit"

    @pytest.mark.asyncio
    async def test_analyze_intent_customer(self):
        """Test intent analysis for customer questions"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "customer"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            intent = await adapter.analyze_intent("Who are our top customers?")
            
            assert intent == "customer"

    @pytest.mark.asyncio
    async def test_analyze_intent_inventory(self):
        """Test intent analysis for inventory questions"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "inventory"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            intent = await adapter.analyze_intent("How much stock do we have?")
            
            assert intent == "inventory"

    @pytest.mark.asyncio
    async def test_analyze_intent_sales(self):
        """Test intent analysis for sales questions"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "sales"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            intent = await adapter.analyze_intent("Show me today's sales")
            
            assert intent == "sales"

    @pytest.mark.asyncio
    async def test_analyze_intent_trend(self):
        """Test intent analysis for trend questions"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "trend"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            intent = await adapter.analyze_intent("Is our revenue growing?")
            
            assert intent == "trend"

    @pytest.mark.asyncio
    async def test_analyze_intent_comparison(self):
        """Test intent analysis for comparison questions"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "comparison"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            intent = await adapter.analyze_intent("Compare Q1 and Q2 revenue")
            
            assert intent == "comparison"

    @pytest.mark.asyncio
    async def test_analyze_intent_report(self):
        """Test intent analysis for report requests"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "report"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            intent = await adapter.analyze_intent("Generate a sales report")
            
            assert intent == "report"

    @pytest.mark.asyncio
    async def test_analyze_intent_general(self):
        """Test intent analysis for general conversation"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "general"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            intent = await adapter.analyze_intent("Hello there!")
            
            assert intent == "general"

    @pytest.mark.asyncio
    async def test_analyze_intent_error_fallback_to_general(self):
        """Test that intent analysis falls back to general on error"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = Exception("API error")
            
            intent = await adapter.analyze_intent("What is this?")
            
            assert intent == "general"

    @pytest.mark.asyncio
    async def test_analyze_intent_case_insensitive(self):
        """Test that intent analysis returns lowercase result"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "REVENUE"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            intent = await adapter.analyze_intent("Revenue question")
            
            assert intent == "revenue"
            assert intent.islower()

    @pytest.mark.asyncio
    async def test_analyze_intent_api_parameters(self):
        """Test that correct parameters are passed for intent analysis"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY, model="gpt-3.5-turbo")
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "revenue"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            await adapter.analyze_intent("Test message")
            
            call_args = mock_create.call_args
            assert call_args.kwargs['model'] == 'gpt-3.5-turbo'
            assert call_args.kwargs['max_tokens'] == 50
            assert call_args.kwargs['temperature'] == 0.1


class TestEdgeCases:
    """Tests for edge cases and error handling"""

    @pytest.mark.asyncio
    async def test_empty_prompt(self):
        """Test handling of empty prompt"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Please provide a prompt"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response("")
            
            assert response == "Please provide a prompt"

    @pytest.mark.asyncio
    async def test_very_long_prompt(self):
        """Test handling of very long prompt"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        long_prompt = "test " * 5000  # Very long prompt
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response to long prompt"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response(long_prompt)
            
            assert response == "Response to long prompt"

    @pytest.mark.asyncio
    async def test_special_characters_in_prompt(self):
        """Test handling of special characters in prompt"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        special_prompt = "What about $100 & 50% discount? <test> [test]"
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response with special chars"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response(special_prompt)
            
            assert response == "Response with special chars"

    @pytest.mark.asyncio
    async def test_multiline_prompt(self):
        """Test handling of multiline prompt"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        multiline_prompt = """
        Question 1: What is revenue?
        Question 2: What is profit?
        Question 3: What is margin?
        """
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Answers to your questions"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response(multiline_prompt)
            
            assert response == "Answers to your questions"

    @pytest.mark.asyncio
    async def test_unicode_characters(self):
        """Test handling of unicode characters"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        unicode_prompt = "What is the revenue? 你好 مرحبا こんにちは"
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response in multiple languages 😊"
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response(unicode_prompt)
            
            assert response == "Response in multiple languages 😊"

    @pytest.mark.asyncio
    async def test_context_with_empty_history(self):
        """Test handling of context with empty conversation history"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response"
        
        context = {
            'conversation_history': []
        }
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response("Test", context=context)
            
            assert response == "Response"

    @pytest.mark.asyncio
    async def test_context_with_empty_retrieved_context(self):
        """Test handling of empty retrieved context"""
        adapter = OpenAIAdapter(api_key=TEST_API_KEY)
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response"
        
        context = {
            'retrieved_context': ''
        }
        
        with patch('openai.ChatCompletion.acreate', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            
            response = await adapter.generate_response("Test", context=context)
            
            assert response == "Response"


if __name__ == "__main__":
    import asyncio
    test_generate_response = TestGenerateResponse()
    asyncio.run(test_generate_response.test_generate_response_simple_prompt())