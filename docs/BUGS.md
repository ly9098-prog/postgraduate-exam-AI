2026-05-30 15:09:51 | ERROR   | uvicorn.error | Traceback (most recent call last):
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/engine/base.py", line 1967, in _exec_single_context
    self.dialect.do_execute(
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/engine/default.py", line 924, in do_execute
    cursor.execute(statement, parameters)
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/dialects/sqlite/aiosqlite.py", line 146, in execute
    self._adapt_connection._handle_exception(error)
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/dialects/sqlite/aiosqlite.py", line 298, in _handle_exception
    raise error
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/dialects/sqlite/aiosqlite.py", line 128, in execute
    self.await_(_cursor.execute(operation, parameters))
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/util/_concurrency_py3k.py", line 131, in await_only
    return current.driver.switch(awaitable)  # type: ignore[no-any-return]
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/util/_concurrency_py3k.py", line 196, in greenlet_spawn
    value = await result
            ^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/aiosqlite/cursor.py", line 48, in execute
    await self._execute(self._cursor.execute, sql, parameters)
  File "/home/lmh/.local/lib/python3.12/site-packages/aiosqlite/cursor.py", line 40, in _execute
    return await self._conn._execute(fn, *args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/aiosqlite/core.py", line 132, in _execute
    return await future
           ^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/aiosqlite/core.py", line 115, in run
    result = function()
             ^^^^^^^^^^
sqlite3.OperationalError: index ix_question_versions_question_id already exists

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/lmh/.local/lib/python3.12/site-packages/starlette/routing.py", line 732, in lifespan
    async with self.lifespan_context(app) as maybe_state:
  File "/usr/lib/python3.12/contextlib.py", line 210, in __aenter__
    return await anext(self.gen)
           ^^^^^^^^^^^^^^^^^^^^^
  File "/home/lmh/projects/postgraduate-ai/backend/app/main.py", line 49, in lifespan
    await init_db()
  File "/home/lmh/projects/postgraduate-ai/backend/app/core/database.py", line 77, in init_db
    await conn.run_sync(_repair_sqlite_admin_pk_tables)
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/ext/asyncio/engine.py", line 886, in run_sync
    return await greenlet_spawn(
           ^^^^^^^^^^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/util/_concurrency_py3k.py", line 201, in greenlet_spawn
    result = context.throw(*sys.exc_info())
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/lmh/projects/postgraduate-ai/backend/app/core/database.py", line 62, in _repair_sqlite_admin_pk_tables
    table.create(conn)
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/sql/schema.py", line 1288, in create
    bind._run_ddl_visitor(ddl.SchemaGenerator, self, checkfirst=checkfirst)
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/engine/base.py", line 2457, in _run_ddl_visitor
    visitorcallable(self.dialect, self, **kwargs).traverse_single(element)
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/sql/visitors.py", line 664, in traverse_single
    return meth(obj, **kw)
           ^^^^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/sql/ddl.py", line 960, in visit_table
    self.traverse_single(index, create_ok=True)
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/sql/visitors.py", line 664, in traverse_single
    return meth(obj, **kw)
           ^^^^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/sql/ddl.py", line 997, in visit_index
    CreateIndex(index)._invoke_with(self.connection)
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/sql/ddl.py", line 314, in _invoke_with
    return bind.execute(self)
           ^^^^^^^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/engine/base.py", line 1418, in execute
    return meth(
           ^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/sql/ddl.py", line 180, in _execute_on_connection
    return connection._execute_ddl(
           ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/engine/base.py", line 1529, in _execute_ddl
    ret = self._execute_context(
          ^^^^^^^^^^^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/engine/base.py", line 1846, in _execute_context
    return self._exec_single_context(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/engine/base.py", line 1986, in _exec_single_context
    self._handle_dbapi_exception(
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/engine/base.py", line 2353, in _handle_dbapi_exception
    raise sqlalchemy_exception.with_traceback(exc_info[2]) from e
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/engine/base.py", line 1967, in _exec_single_context
    self.dialect.do_execute(
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/engine/default.py", line 924, in do_execute
    cursor.execute(statement, parameters)
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/dialects/sqlite/aiosqlite.py", line 146, in execute
    self._adapt_connection._handle_exception(error)
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/dialects/sqlite/aiosqlite.py", line 298, in _handle_exception
    raise error
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/dialects/sqlite/aiosqlite.py", line 128, in execute
    self.await_(_cursor.execute(operation, parameters))
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/util/_concurrency_py3k.py", line 131, in await_only
    return current.driver.switch(awaitable)  # type: ignore[no-any-return]
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/sqlalchemy/util/_concurrency_py3k.py", line 196, in greenlet_spawn
    value = await result
            ^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/aiosqlite/cursor.py", line 48, in execute
    await self._execute(self._cursor.execute, sql, parameters)
  File "/home/lmh/.local/lib/python3.12/site-packages/aiosqlite/cursor.py", line 40, in _execute
    return await self._conn._execute(fn, *args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/aiosqlite/core.py", line 132, in _execute
    return await future
           ^^^^^^^^^^^^
  File "/home/lmh/.local/lib/python3.12/site-packages/aiosqlite/core.py", line 115, in run
    result = function()
             ^^^^^^^^^^
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) index ix_question_versions_question_id already exists
[SQL: CREATE INDEX ix_question_versions_question_id ON question_versions (question_id)]
(Background on this error at: https://sqlalche.me/e/20/e3q8)

2026-05-30 15:09:51 | ERROR   | uvicorn.error | Application startup failed. Exiting.
