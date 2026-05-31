import asyncio
import logging
import unittest
from unittest.mock import AsyncMock, MagicMock

from crabber.services.llm import LlmService, LlmChat


class LowercaseLogChecker(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class TestLlmService(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Configure logging to capture logs
        self.logger = logging.getLogger("test_llm")
        self.logger.setLevel(logging.DEBUG)
        self.log_checker = LowercaseLogChecker()
        self.logger.addHandler(self.log_checker)

        # Sample config matching config.example.json structure
        self.config = {
            "provider": "openai",
            "api_key": "sk-test-key",
            "base_url": "https://api.test.com/v1",
            "chat_params": {
                "model": "deepseek-v4-pro",
                "temperature": 0.7
            }
        }

    def tearDown(self):
        self.logger.removeHandler(self.log_checker)

    def test_service_initialization(self):
        """Test that LlmService initializes correctly with config."""
        service = LlmService(self.config, self.logger)
        self.assertEqual(service.provider, "openai")
        self.assertEqual(service.api_key, "sk-test-key")
        self.assertEqual(service.base_url, "https://api.test.com/v1")
        self.assertEqual(service.chat_params, {"model": "deepseek-v4-pro", "temperature": 0.7})
        self.assertIsNotNone(service.client)

        # Check logs are lowercase
        for record in self.log_checker.records:
            msg = record.getMessage()
            self.assertTrue(msg[0].islower(), f"Log message must start with a lowercase letter: '{msg}'")

    def test_new_chat_with_single_system_prompt(self):
        """Test creating LlmChat with a single system prompt."""
        service = LlmService(self.config, self.logger)
        system_prompt = "You are a friendly cat chatbot."
        chat = service.new_chat(system_prompt=system_prompt)

        self.assertIsInstance(chat, LlmChat)
        self.assertEqual(len(chat.history), 1)
        self.assertEqual(chat.history[0], {"role": "system", "content": system_prompt})

    def test_new_chat_with_multiple_system_prompts(self):
        """Test creating LlmChat with multiple system prompts in a list."""
        service = LlmService(self.config, self.logger)
        system_prompts = [
            "You are a friendly cat chatbot.",
            "You only say meow.",
            "Be very cute."
        ]
        chat = service.new_chat(system_prompt=system_prompts)

        self.assertIsInstance(chat, LlmChat)
        self.assertEqual(len(chat.history), 3)
        self.assertEqual(chat.history[0], {"role": "system", "content": "You are a friendly cat chatbot."})
        self.assertEqual(chat.history[1], {"role": "system", "content": "You only say meow."})
        self.assertEqual(chat.history[2], {"role": "system", "content": "Be very cute."})

    async def test_continuous_conversation(self):
        """Test multi-turn continuous conversation with mocked client."""
        service = LlmService(self.config, self.logger)
        chat = service.new_chat(system_prompt="You are a helper.")

        # Mock the chat completions API call
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "hello! how can i assist you today?"
        mock_response.choices = [mock_choice]

        service.client.chat.completions.create = AsyncMock(return_value=mock_response)

        # Send first message
        reply1 = await chat.send_message("hello")
        self.assertEqual(reply1, "hello! how can i assist you today?")

        # Verify history contains: system prompt, user message, and assistant reply
        self.assertEqual(len(chat.history), 3)
        self.assertEqual(chat.history[0], {"role": "system", "content": "You are a helper."})
        self.assertEqual(chat.history[1], {"role": "user", "content": "hello"})
        self.assertEqual(chat.history[2], {"role": "assistant", "content": "hello! how can i assist you today?"})

        # Mock second response
        mock_choice2 = MagicMock()
        mock_choice2.message.content = "sure, i can do that."
        mock_response2 = MagicMock()
        mock_response2.choices = [mock_choice2]
        service.client.chat.completions.create.mock_add_spec(spec=None)
        service.client.chat.completions.create.return_value = mock_response2

        # Send second message
        reply2 = await chat.send_message("can you help me write a python script?")
        self.assertEqual(reply2, "sure, i can do that.")

        # Verify history has grown
        self.assertEqual(len(chat.history), 5)
        self.assertEqual(chat.history[3], {"role": "user", "content": "can you help me write a python script?"})
        self.assertEqual(chat.history[4], {"role": "assistant", "content": "sure, i can do that."})

        # Verify AsyncOpenAI completions was called with full history and config params
        service.client.chat.completions.create.assert_called_with(
            model="deepseek-v4-pro",
            messages=chat.history,
            temperature=0.7
        )

        # Assert all logged messages start with lowercase
        self.assertTrue(len(self.log_checker.records) > 0)
        for record in self.log_checker.records:
            msg = record.getMessage()
            self.assertTrue(msg[0].islower(), f"Log message must start with a lowercase letter: '{msg}'")

    async def test_error_handling_pops_failed_message(self):
        """Test that if calling the API fails, the failed user message is popped so history stays consistent."""
        service = LlmService(self.config, self.logger)
        chat = service.new_chat()

        # Mock client to raise an exception
        service.client.chat.completions.create = AsyncMock(side_effect=RuntimeError("api limit reached"))

        with self.assertRaises(RuntimeError):
            await chat.send_message("this message should fail")

        # History should be empty because the user message was popped upon failure
        self.assertEqual(len(chat.history), 0)

        # Check logs are lowercase and contain the error
        error_logs = [r.getMessage() for r in self.log_checker.records if r.levelno == logging.ERROR]
        self.assertEqual(len(error_logs), 1)
        self.assertTrue(error_logs[0].startswith("failed to send message to llm"))


    async def test_send_message_with_system_prompt_injection(self):
        """Test sending a message with an injected system prompt, verifying history and rollback on failure."""
        service = LlmService(self.config, self.logger)
        chat = service.new_chat()

        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "i hear you."
        mock_response.choices = [mock_choice]
        service.client.chat.completions.create = AsyncMock(return_value=mock_response)

        # Successful call with system prompt injection
        reply = await chat.send_message("hello", system_prompt="[system signal: allow break ice]")
        self.assertEqual(reply, "i hear you.")
        self.assertEqual(len(chat.history), 3)
        self.assertEqual(chat.history[0], {"role": "system", "content": "[system signal: allow break ice]"})
        self.assertEqual(chat.history[1], {"role": "user", "content": "hello"})
        self.assertEqual(chat.history[2], {"role": "assistant", "content": "i hear you."})

        # Failed call with system prompt injection, verifying rollback of both user and system messages
        service.client.chat.completions.create = AsyncMock(side_effect=RuntimeError("api limit reached"))
        with self.assertRaises(RuntimeError):
            await chat.send_message("another message", system_prompt="[another signal]")

        # History size should still be 3 (rollback deleted the new system and user messages)
        self.assertEqual(len(chat.history), 3)


if __name__ == "__main__":
    unittest.main()
