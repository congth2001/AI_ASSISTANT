"""Existing catch clauses must keep working after errors gain a common base."""
import pytest

from src.common.errors import ApplicationError, ConfigurationError
from src.modules.assistant.application.agent.runtime import AgentOperationTimeout
from src.modules.assistant.application.services.sql_service import SQLValidationError
from src.modules.auth.domain.errors import AuthenticationError, DuplicateEmailError


@pytest.mark.parametrize("error_type,previous_base,code", [
    (ConfigurationError, RuntimeError, "configuration_error"),
    (AuthenticationError, ValueError, "authentication_error"),
    (DuplicateEmailError, ValueError, "duplicate_email"),
    (SQLValidationError, Exception, "sql_validation_error"),
    (AgentOperationTimeout, TimeoutError, "agent_operation_timeout"),
])
def test_common_error_preserves_existing_exception_contract(error_type, previous_base, code):
    with pytest.raises(previous_base) as raised:
        raise error_type("Existing public message")

    error = raised.value
    assert isinstance(error, ApplicationError)
    assert str(error) == "Existing public message"
    assert error.message == "Existing public message"
    assert error.code == code
