"""Central catalog of data_sync error codes and message templates."""
from src.common.errors import ConflictError, InternalError, NotFoundError, ValidationError


class SyncJobAlreadyRunningError(ConflictError):
    code = "sync_job_already_running"
    message_template = "Đang có một lượt đồng bộ chạy. Đợi lượt đó kết thúc rồi thử lại."


class SyncJobNotFoundError(NotFoundError):
    code = "sync_job_not_found"
    message_template = "Không tìm thấy lượt đồng bộ"


class SyncSourceUnavailableError(ValidationError):
    code = "sync_source_unavailable"
    message_template = "Nguồn đồng bộ '{source}' chưa sẵn sàng: {reason}"


class SyncSnapshotStaleError(ConflictError):
    code = "sync_snapshot_stale"
    message_template = (
        "Các file Excel (cập nhật {files_modified_at}) cũ hơn lần đồng bộ từ phần mềm bán hàng "
        "gần nhất ({latest_extraction_at}); nạp lại có thể làm mất dữ liệu mới hơn. "
        "Xác nhận nếu vẫn muốn nạp các file này."
    )


class SyncJobStartFailedError(InternalError):
    code = "sync_job_start_failed"
    message_template = "Không bắt đầu được lượt đồng bộ"


class SyncJobReadFailedError(InternalError):
    code = "sync_job_read_failed"
    message_template = "Không đọc được lịch sử đồng bộ"
