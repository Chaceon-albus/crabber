import asyncio
import inspect
import logging

from collections.abc import Awaitable, Callable
from typing import Any


class TaskManager:

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._loop = loop
        self._logger = logger
        self.__tasks: set[asyncio.Task[Any]] = set()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("task manager is already bound to another event loop")
        self._loop = loop

    @property
    def tasks(self) -> frozenset[asyncio.Task[Any]]:
        return frozenset(self.__tasks)

    def go(
        self,
        work: Awaitable[Any] | Callable[..., Any],
        *args: Any,
        timeout: float | None = None,
        name: str | None = None,
        context: Any | None = None,
        **kwargs: Any,
    ) -> asyncio.Task[Any]:
        loop = self._get_loop()
        label = name or self._name_of(work)

        def create() -> asyncio.Task[Any]:
            coro = self._run(work, args, kwargs, timeout, label)
            task = loop.create_task(coro, name=label, context=context)
            self.__tasks.add(task)
            task.add_done_callback(self._on_task_done)
            return task

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        # Task creation must happen in the loop that will own the task. If go()
        # is called from another thread, submit the creation back to that loop.
        if running_loop is loop:
            return create()

        if not loop.is_running():
            raise RuntimeError("task manager is bound to an event loop that is not running")

        future = asyncio.run_coroutine_threadsafe(self._create_from_loop(create), loop)
        return future.result()

    async def close(self, timeout: float | None = 10) -> None:
        tasks = set(self.__tasks)
        if not tasks:
            return

        for task in tasks:
            task.cancel()

        _, pending = await asyncio.wait(tasks, timeout=timeout)

        if pending:
            for task in pending:
                task.cancel()
            if self._logger:
                names = ", ".join(task.get_name() for task in pending)
                self._logger.warning(f"timed out waiting for tasks to close: {names}")
        elif self._logger:
            self._logger.debug(f"all tasks cancelled: {', '.join(t.get_name() for t in tasks)}")

        self.__tasks.difference_update(tasks)

    async def _create_from_loop(self, create: Callable[[], asyncio.Task[Any]]) -> asyncio.Task[Any]:
        return create()

    async def _run(
        self,
        work: Awaitable[Any] | Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        timeout: float | None,
        label: str | None,
    ) -> Any:
        try:
            awaitable = self._to_awaitable(work, args, kwargs)

            if timeout is None:
                return await awaitable

            return await asyncio.wait_for(awaitable, timeout=timeout)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            if self._logger:
                self._logger.warning(f"task timed out: {label}")
        except Exception as e:
            if self._logger:
                self._logger.exception(f"task failed: {label}: {e}")

        return None

    def _to_awaitable(
        self,
        work: Awaitable[Any] | Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Awaitable[Any]:
        if inspect.isawaitable(work):
            if args or kwargs:
                raise TypeError("arguments can only be used when scheduling a callable")
            return work

        if not callable(work):
            raise TypeError("task manager expects an awaitable or callable")

        return self._run_sync(work, args, kwargs)

    async def _run_sync(
        self,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        result = await asyncio.to_thread(func, *args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        self.__tasks.discard(task)

        if task.cancelled():
            return

        try:
            task.exception()
        except asyncio.CancelledError:
            return
        except BaseException as e:
            if self._logger:
                self._logger.exception(f"task failed outside manager wrapper: {task.get_name()}: {e}")

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop

        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError as e:
            raise RuntimeError("task manager is not bound to a running event loop") from e

        return self._loop

    @staticmethod
    def _name_of(work: Awaitable[Any] | Callable[..., Any]) -> str | None:
        name = getattr(work, "__name__", None)
        if name:
            return name

        code = getattr(work, "cr_code", None) or getattr(work, "gi_code", None)
        return getattr(code, "co_name", None)
