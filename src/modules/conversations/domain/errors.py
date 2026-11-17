"""Central catalog of conversations error codes and message templates."""
from src.common.errors import (
    InternalError,
    NotFoundError,
    PermissionDeniedError,
)


class ConversationNotFoundError(NotFoundError):
    code = 'conversation_not_found'
    message_template = 'Conversation not found'


class ConversationReadOnlyError(PermissionDeniedError):
    code = 'conversation_read_only'
    message_template = 'Conversation của tài khoản khác chỉ được phép xem'


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
