import asyncio
import shutil
from collections import deque
from contextlib import suppress
import logging

from crabber.logging import logger as default_logger


class FFmpegError(Exception):
    """Exception raised when an FFmpeg process exits with an error."""

    def __init__(self, returncode: int, stderr_logs: list[str]):
        self.returncode = returncode
        self.stderr_logs = stderr_logs
        # Display the last few lines of stderr for context
        logs_str = "\n".join(stderr_logs[-15:])
        message = (
            f"FFmpeg process exited with non-zero code {returncode}.\n"
            f"Last stderr output:\n{logs_str}"
        )
        super().__init__(message)


class FFmpegProcess:
    """A robust wrapper for running FFmpeg as an asynchronous subprocess.

    Provides asynchronous stdin writing and stdout/stderr reading. Handles
    background stream consumption to prevent process blocking, collects
    stderr logs for detailed error reporting, and provides clean methods for
    graceful termination and forced timeout closing.

    Example:
        ```python
        args = [
            "-nostdin", "-y",
            "-i", "pipe:0",
            "-c", "copy",
            "-movflags", "empty_moov+default_base_moof+frag_keyframe",
            "output.mp4"
        ]
        async with FFmpegProcess(args) as ffmpeg:
            await ffmpeg.write(video_chunk)
        ```
    """

    def __init__(
        self,
        args: list[str],
        ffmpeg_path: str | None = None,
        logger: logging.Logger | None = None,
        stdout_queue_size: int = 128,
        stderr_queue_size: int = 128,
        max_log_lines: int = 200,
    ) -> None:
        """Initialize the FFmpegProcess.

        Args:
            args: Command line arguments to pass to FFmpeg (excluding the executable name).
            ffmpeg_path: Optional path to the FFmpeg executable. If not specified,
                         it will be looked up in the system PATH.
            logger: Optional logger instance.
            max_log_lines: Maximum number of stderr lines to keep in memory for error reporting.
            stdout_queue_size: Capacity of the stdout queue once initialized.
            stderr_queue_size: Capacity of the stderr queue once initialized.
        """
        self.args = args
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg")
        self.logger = logger or default_logger
        self.stdout_queue_size = stdout_queue_size
        self.stderr_queue_size = stderr_queue_size
        self.max_log_lines = max_log_lines

        self._process: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None

        self._stderr_logs: deque = deque(maxlen=max_log_lines)
        self._stdout_queue: asyncio.Queue | None = None
        self._stderr_queue: asyncio.Queue | None = None

    @property
    def is_running(self) -> bool:
        """Check if the FFmpeg subprocess is currently running."""
        return self._process is not None and self._process.returncode is None

    @property
    def returncode(self) -> int | None:
        """Get the return code of the FFmpeg subprocess. Returns None if still running."""
        return self._process.returncode if self._process else None

    @property
    def stderr_logs(self) -> list[str]:
        """Get the accumulated stderr logs (up to max_log_lines)."""
        return list(self._stderr_logs)

    @property
    def stdout(self) -> asyncio.Queue:
        """Get the stdout queue.

        Note:
            Accessing this property initializes the queue. Any stdout data produced
            before this property is accessed will be discarded to prevent process blocking.
        """
        if self._stdout_queue is None:
            self._stdout_queue = asyncio.Queue(maxsize=self.stdout_queue_size)
        return self._stdout_queue

    @property
    def stderr(self) -> asyncio.Queue:
        """Get the stderr queue.

        Note:
            Accessing this property initializes the queue. Any stderr data produced
            before this property is accessed will be discarded (though logs are still
            accumulated in stderr_logs for diagnostics).
        """
        if self._stderr_queue is None:
            self._stderr_queue = asyncio.Queue(maxsize=self.stderr_queue_size)
        return self._stderr_queue

    async def start(self) -> None:
        """Spawn the FFmpeg subprocess and start background stream readers."""
        if self._process is not None:
            raise RuntimeError("ffmpeg process has already been started")

        if not self.ffmpeg_path:
            raise FileNotFoundError("ffmpeg executable not found in PATH or specified path is invalid")

        self.logger.debug(f"starting ffmpeg process: {self.ffmpeg_path} {' '.join(self.args)}")

        self._process = await asyncio.create_subprocess_exec(
            self.ffmpeg_path,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Clear logs and queues
        self._stderr_logs.clear()
        self._stdout_queue = None
        self._stderr_queue = None

        # Start background tasks to consume stdout and stderr to prevent blocking
        self._stdout_task = asyncio.create_task(self._read_stdout_loop())
        self._stderr_task = asyncio.create_task(self._read_stderr_loop())

    async def write(self, data: bytes) -> None:
        """Write binary data to FFmpeg's stdin and drain the writer buffer.

        Args:
            data: The bytes to write to the process stdin.

        Raises:
            FFmpegError: If the process has exited or failed.
            RuntimeError: If the process is not started or stdin is not available.
        """
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("ffmpeg process is not started or stdin is not available")

        if self._process.returncode is not None:
            raise FFmpegError(self._process.returncode, list(self._stderr_logs))

        try:
            self._process.stdin.write(data)
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            # The process probably exited, wait a tiny bit to get the return code and logs
            await asyncio.sleep(0.1)
            returncode = self._process.returncode if self._process.returncode is not None else -1
            raise FFmpegError(returncode, list(self._stderr_logs)) from e

    async def read_stdout(self) -> bytes:
        """Read a chunk of data from FFmpeg's stdout.

        Returns empty bytes when EOF is reached.
        """
        if self._process is None:
            raise RuntimeError("ffmpeg process is not started")
        return await self.stdout.get()

    async def read_stderr(self) -> bytes:
        """Read a line of data from FFmpeg's stderr.

        Returns empty bytes when EOF is reached.
        """
        if self._process is None:
            raise RuntimeError("ffmpeg process is not started")
        return await self.stderr.get()

    async def wait(self) -> int:
        """Wait for the FFmpeg process to exit and return its return code.

        Returns:
            The exit return code of the process.
        """
        if self._process is None:
            raise RuntimeError("ffmpeg process is not started")
        return await self._process.wait()

    async def close(self, timeout: float = 10.0) -> int:
        """Gracefully close the FFmpeg process.

        First attempts to write EOF to stdin and closes it, then waits for the
        process to exit. If the process does not exit within the timeout, it
        is forcibly killed.

        Args:
            timeout: Maximum seconds to wait for graceful exit before killing.

        Returns:
            The exit return code of the process.
        """
        if self._process is None:
            return 0

        self.logger.debug("closing ffmpeg process gracefully...")

        # 1. Write EOF to stdin if supported
        if self._process.stdin is not None:
            with suppress(BrokenPipeError, ConnectionResetError, OSError, RuntimeError):
                if self._process.stdin.can_write_eof():
                    self._process.stdin.write_eof()

            # 2. Close stdin and wait closed
            if not self._process.stdin.is_closing():
                with suppress(BrokenPipeError, ConnectionResetError, OSError, RuntimeError):
                    self._process.stdin.close()
                    await self._process.stdin.wait_closed()

        # 3. Wait for process exit or force kill on timeout
        try:
            returncode = await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            self.logger.warning(
                f"ffmpeg process did not exit within {timeout}s... force killing..."
            )
            with suppress(ProcessLookupError):
                self._process.kill()
            try:
                returncode = await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, TimeoutError):
                self.logger.error("ffmpeg process could not be killed.")
                returncode = -1

        # 4. Clean up background reader tasks
        if self._stdout_task and not self._stdout_task.done():
            self._stdout_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._stdout_task

        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._stderr_task

        # 5. Clear reference
        self._process = None
        self.logger.debug(f"ffmpeg process stopped with return code: {returncode}")
        return returncode

    async def _read_stdout_loop(self) -> None:
        """Background task to continuously read from stdout and queue data if queue is initialized."""
        try:
            while self._process and self._process.stdout:
                chunk = await self._process.stdout.read(32000) # 3.2k -> 200ms mono 16 kHz
                if not chunk:
                    break
                if self._stdout_queue is not None:
                    await self._stdout_queue.put(chunk)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"error reading ffmpeg stdout: {e}")
        finally:
            if self._stdout_queue is not None:
                await self._stdout_queue.put(b"")

    async def _read_stderr_loop(self) -> None:
        """Background task to continuously read stderr lines, log them, and queue them if queue is initialized."""
        try:
            buffer = b""
            while self._process and self._process.stderr:
                chunk = await self._process.stderr.read(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line_with_newline = line + b"\n"
                    # Keep stderr lines for error diagnostics
                    decoded_line = line_with_newline.decode("utf-8", errors="replace").strip()
                    if decoded_line:
                        self._stderr_logs.append(decoded_line)
                        self.logger.debug(f"ffmpeg stderr: {decoded_line}")

                    if self._stderr_queue is not None:
                        await self._stderr_queue.put(line_with_newline)

            # Handle any remaining data in the buffer after EOF
            if buffer:
                decoded_line = buffer.decode("utf-8", errors="replace").strip()
                if decoded_line:
                    self._stderr_logs.append(decoded_line)
                    self.logger.debug(f"ffmpeg stderr: {decoded_line}")

                if self._stderr_queue is not None:
                    await self._stderr_queue.put(buffer)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"error reading ffmpeg stderr: {e}")
        finally:
            if self._stderr_queue is not None:
                await self._stderr_queue.put(b"")

    async def __aenter__(self) -> "FFmpegProcess":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def __del__(self) -> None:
        # Cancel background tasks to avoid "Task was destroyed but it is pending" warning
        try:
            if hasattr(self, "_stdout_task") and self._stdout_task and not self._stdout_task.done():
                self._stdout_task.cancel()
        except Exception:
            pass
        try:
            if hasattr(self, "_stderr_task") and self._stderr_task and not self._stderr_task.done():
                self._stderr_task.cancel()
        except Exception:
            pass
