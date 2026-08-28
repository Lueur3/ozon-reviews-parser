"""Мягкая остановка по Ctrl+C.

Штатный обработчик отменяет корутину прямо посреди вызова к драйверу браузера.
Patchright в этот момент остаётся с незабранными ошибками («Future exception was
never retrieved»), а браузер закрывается аварийно. Поэтому первый Ctrl+C только
просит остановиться: сбор доходит до ближайшей границы (конец страницы или
товара) и выходит сам, штатно закрыв браузер. Второй Ctrl+C прерывает сразу.
"""
import contextlib
import signal

_requested = False


def requested() -> bool:
    """Просил ли пользователь остановиться."""
    return _requested


@contextlib.contextmanager
def graceful(notice: str = "\nОстанавливаюсь после текущего запроса… "
                           "(ещё раз Ctrl+C — прервать сразу)"):
    """На время работы перехватывает SIGINT, возвращая прежний обработчик после."""
    global _requested
    _requested = False
    previous = signal.getsignal(signal.SIGINT)

    def handler(signum, frame):
        global _requested
        if _requested:                       # второй раз — как обычно
            signal.signal(signal.SIGINT, previous)
            raise KeyboardInterrupt
        _requested = True
        print(notice)

    try:
        signal.signal(signal.SIGINT, handler)
    except ValueError:
        # не главный поток — обработчик не поставить, работаем как раньше
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
        _requested = False
