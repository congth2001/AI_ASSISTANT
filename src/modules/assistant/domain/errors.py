"""Central catalog of assistant error codes and message templates."""
from src.common.errors import (
    ConfigurationError,
    ExternalServiceError,
    InternalError,
    OperationTimeoutError,
    PermissionDeniedError,
    ValidationError,
)


class SQLValidationError(ValidationError):
    code = "sql_validation_error"


class SQLQueryRejectedError(SQLValidationError):
    """Database rejected the query; only the sanitized primary message is kept."""
    code = 'sql_query_rejected'
    message_template = 'Lỗi SQL ({sqlstate}): {detail}'


class SQLQueryTimeoutError(OperationTimeoutError):
    code = 'sql_query_timeout'
    message_template = 'Truy vấn dữ liệu vượt quá thời gian cho phép.'


class SQLDatabaseConnectionLostError(ExternalServiceError):
    code = 'sql_database_connection_lost'
    message_template = 'Mất kết nối tới cơ sở dữ liệu.'


class SQLDatabaseFailureError(ExternalServiceError):
    code = 'sql_database_failure'
    message_template = 'Cơ sở dữ liệu không thực hiện được truy vấn.'


class LLMServiceRequiredError(ValidationError):
    code = 'llm_service_required'
    message_template = 'llm_service is required when include_response=True'


class AgentPolicyStateError(InternalError):
    code = 'agent_policy_state'
    message_template = 'unreachable'


class AgentOperationTimeout(OperationTimeoutError):
    code = 'agent_operation_timeout'
    message_template = '{operation} timed out'


class UnsupportedAgentRouteError(ValidationError):
    code = 'unsupported_agent_route'
    message_template = 'Unsupported agent route: {route!r}'


class SQLRepairFailedError(SQLValidationError):
    code = 'sql_repair_failed'
    message_template = 'LLM không thể tạo SQL sửa lỗi.'


class SQLPlanLimitError(SQLValidationError):
    code = 'sql_plan_limit'
    message_template = 'Chỉ cho phép tối đa {max_plans} query plans.'


class EmptySQLQueryError(SQLValidationError):
    code = 'empty_sql_query'
    message_template = 'SQL rỗng — LLM không sinh được query.'


class MultipleSQLStatementsError(SQLValidationError):
    code = 'multiple_sql_statements'
    message_template = 'Chỉ cho phép một câu SQL.'


class SQLCommentsForbiddenError(SQLValidationError):
    code = 'sql_comments_forbidden'
    message_template = 'SQL comment không được phép.'


class SQLReadOnlyRequiredError(SQLValidationError):
    code = 'sql_read_only_required'
    message_template = "Chỉ cho phép SELECT hoặc CTE. Câu SQL bắt đầu bằng: '{query_prefix}'"


class SQLKeywordForbiddenError(SQLValidationError):
    code = 'sql_keyword_forbidden'
    message_template = 'SQL chứa từ khóa bị cấm: {blocked}'


class SQLMetadataForbiddenError(SQLValidationError):
    code = 'sql_metadata_forbidden'
    message_template = 'Không cho phép truy cập metadata hệ thống.'


class SQLWriteOrLockForbiddenError(SQLValidationError):
    code = 'sql_write_or_lock_forbidden'
    message_template = 'Không cho phép khóa hoặc ghi dữ liệu từ SELECT.'


class SQLLegacyTableError(SQLValidationError):
    code = 'sql_legacy_table'
    message_template = 'SQL sử dụng bảng legacy không còn tồn tại: {legacy}'


class SQLTableNotAllowedError(SQLValidationError):
    code = 'sql_table_not_allowed'
    message_template = 'SQL truy cập bảng ngoài phạm vi dữ liệu bán hàng: {table}'


class SQLSelectStarForbiddenError(SQLValidationError):
    code = 'sql_select_star_forbidden'
    message_template = 'Không cho phép SELECT *; phải liệt kê cột tường minh.'


class SQLPlaceholderError(SQLValidationError):
    code = 'sql_placeholder'
    message_template = 'SQL còn chứa placeholder chưa resolve.'


class GuestBusinessDataForbiddenError(PermissionDeniedError):
    code = 'guest_business_data_forbidden'
    message_template = 'Tài khoản khách không có quyền truy cập dữ liệu kinh doanh của cửa hàng'


class QueryAnalyzerRequiredError(ConfigurationError, ValueError):
    code = 'query_analyzer_required'
    message_template = 'query_analyzer is required when execute() receives a string'


class AnthropicRequestError(ExternalServiceError):
    code = 'anthropic_request'
    message_template = 'Anthropic API error'


class OpenAIRequestError(ExternalServiceError):
    code = 'openai_request'
    message_template = 'OpenAI API error'


class EmbeddingRequestError(ExternalServiceError):
    code = 'embedding_request'
    message_template = 'OpenAI embedding error'


class BatchEmbeddingRequestError(ExternalServiceError):
    code = 'batch_embedding_request'
    message_template = 'OpenAI batch embedding error'


class VectorStoreWriteError(ExternalServiceError):
    code = 'vector_store_write'
    message_template = 'Vector store rejected a write to collection {collection} ({count} chunks)'


class VectorStoreQueryError(ExternalServiceError):
    code = 'vector_store_query'
    message_template = 'Vector store {operation} failed on collection {collection}'


class ConversationIdRequiredError(ValidationError):
    code = 'conversation_id_required'
    message_template = 'conversation_id is required'


class ChatFailedError(InternalError):
    code = 'chat_failed'
    message_template = 'Chat error'


class DocumentSearchFailedError(InternalError):
    code = 'document_search_failed'
    message_template = 'Search error'


class InvalidConversationIdError(ValidationError):
    code = 'invalid_conversation_id'
    message_template = 'conversation_id must be a valid UUID'


class StreamingResponseFailedError(InternalError):
    code = 'streaming_response_failed'
    message_template = 'Không thể xử lý yêu cầu lúc này. Vui lòng thử lại sau.'


class SQLGenerationFailedError(InternalError):
    code = 'sql_generation_failed'
    message_template = 'Không thể xác định câu query phù hợp cho câu hỏi này.'


class SQLPlanValidationFailedError(SQLValidationError):
    code = 'sql_validation_failed'
    message_template = 'Không thể tạo truy vấn dữ liệu an toàn.'


class SQLExecutionFailedError(InternalError):
    code = 'sql_execution_failed'
    message_template = 'Không thể thực hiện truy vấn dữ liệu.'

    @classmethod
    def diagnostic(cls, error: str) -> str:
        return f'[Lỗi: {error}]'
