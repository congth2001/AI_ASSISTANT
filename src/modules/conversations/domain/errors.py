"""Central catalog of conversations error codes and message templates."""
from src.common.errors import (
    InternalError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)


class ConversationNotFoundError(NotFoundError):
    code = 'conversation_not_found'
    message_template = 'Conversation not found'


class ConversationReadOnlyError(PermissionDeniedError):
    code = 'conversation_read_only'
    message_template = 'Conversations owned by other accounts are read-only'


class ConversationScopeRequiredError(InternalError):
    """Programming error: a conversation was accessed without an owner or an explicit admin scope."""

    code = 'conversation_scope_required'
    message_template = 'Conversation access requires an owner id or an explicit admin scope'


class ConversationReadFailedError(InternalError):
    code = 'conversation_read_failed'
    message_template = 'Error retrieving conversation'


class ConversationListFailedError(InternalError):
    code = 'conversation_list_failed'
    message_template = 'Error retrieving conversations'


class ConversationCreateFailedError(InternalError):
    code = 'conversation_create_failed'
    message_template = 'Error creating conversation'


class ConversationRenameFailedError(InternalError):
    code = 'conversation_rename_failed'
    message_template = 'Error renaming conversation'


class ConversationDeleteFailedError(InternalError):
    code = 'conversation_delete_failed'
    message_template = 'Error deleting conversation'


class ConversationMetadataInvalidError(ValidationError):
    code = 'conversation_metadata_invalid'
    message_template = 'Conversation metadata must be JSON serializable'


class ConversationMetadataTooLargeError(ValidationError):
    code = 'conversation_metadata_too_large'
    message_template = 'Conversation metadata must not exceed {max_bytes} bytes of JSON'
