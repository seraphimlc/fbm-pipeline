class TaskStepCanceled(RuntimeError):
    """Raised by a worker when a cancel request should stop success projection."""


class TaskStepInterrupted(RuntimeError):
    """Raised when a running step is interrupted before normal completion."""


class TaskStepWaitingExternal(RuntimeError):
    """Raised after durable external jobs are submitted and the runner may release the step."""

    def __init__(self, message: str, payload: dict | None = None):
        super().__init__(message)
        self.payload = payload or {}
