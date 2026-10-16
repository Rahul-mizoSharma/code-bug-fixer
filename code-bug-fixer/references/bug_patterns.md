# Common Bug Patterns: Review Checklist

## Python
| Bug | Symptom | Fix |
|---|---|---|
| Missing colon / bad indentation | `SyntaxError` / `IndentationError` | Add `:`; use 4 spaces consistently |
| Mutable default argument `def f(x=[])` | Data leaks between calls | `x=None`, then `x = x or []` inside |
| Undefined / misspelled name | `NameError` | Define, import or fix the spelling |
| `None` attribute access | `AttributeError: 'NoneType'...` | Guard with `if obj is not None` |
| Missing dict key | `KeyError` | `d.get(k, default)` or `if k in d` |
| Index past the end | `IndexError` | Check `len()`; use `range(len(x))` correctly |
| `str + int` | `TypeError` | `str(n)` or f-string |
| Modifying a list while iterating | Skipped items | Iterate over a copy or use a comprehension |
| Bare `except:` / `except: pass` | Hidden errors | Catch specific exceptions; log them |
| `is` with literals | Wrong comparison results | Use `==` |
| Integer vs float division | Wrong math (`//` vs `/`) | Use the correct operator |
| Infinite recursion | `RecursionError` | Add or fix the base case |

## FastAPI
| Bug | Symptom | Fix |
|---|---|---|
| `return HTTPException(...)` | Client gets 200 with an error body | `raise HTTPException(...)` |
| Path param missing from the signature | 422 / startup error | Add the param with a type annotation |
| `time.sleep` / `requests` inside `async def` | Server stalls under load | `await asyncio.sleep`, `httpx.AsyncClient`, or use `def` |
| Calling an async function without `await` | Coroutine returned / "never awaited" warning | Add `await` |
| Body model on GET | Clients can't send a body | Use query params or POST |
| Pydantic v1/v2 API mixing (`.dict()` vs `.model_dump()`) | `AttributeError` | Use the API for the installed version |
| DB session not closed | Connection pool exhausted | Dependency with `yield` + `finally: db.close()` |
| Route order (`/items/me` after `/items/{id}`) | Wrong handler matched | Declare static routes first |
| Missing CORS middleware | Browser CORS errors | `app.add_middleware(CORSMiddleware, ...)` |

## JavaScript
| Bug | Symptom | Fix |
|---|---|---|
| Missing `await` | `Promise {<pending>}`, `.json is not a function` | `await` inside an `async` function |
| `this` lost in a callback | `Cannot read properties of undefined` | Arrow function or `.bind(this)` |
| `undefined`/`null` property access | `TypeError: Cannot read properties of undefined` | Optional chaining `?.`, default values |
| `==` coercion | `'' == 0` is true | `===` |
| `var` in a loop with a closure | All callbacks see the last value | `let` |
| `forEach(async ...)` | Code continues before the work finishes | `for...of` + `await` or `Promise.all` |
| Unhandled promise rejection | Crash / silent failure | `try/catch` around `await`, `.catch()` |
| `x === NaN` | Always false | `Number.isNaN(x)` |
| `<= arr.length` loop | Reads `undefined` | `< arr.length` |
| Floating-point equality | `0.1 + 0.2 !== 0.3` | Compare with an epsilon |

## React
| Bug | Symptom | Fix |
|---|---|---|
| Hook inside if/loop | "Rendered more hooks than during the previous render" | Call hooks at the top level only |
| `useEffect` with no deps that sets state | Infinite render loop | Add a dependency array |
| Missing or wrong effect deps | Stale values | Include every value the effect uses |
| `useEffect(async () => ...)` | Warning; cleanup broken | Inner async function |
| `onClick={fn()}` | Runs on render / "Too many re-renders" | `onClick={() => fn()}` |
| Mutating state (`arr.push` then `setArr(arr)`) | UI doesn't update | Copy: `setArr([...arr, x])` |
| Stale state in updater | Lost increments | `setCount(c => c + 1)` |
| Missing `key` in `.map` | Warning; wrong item reused | `key={item.id}` (not the index, if the list changes) |
| `class` / `for` attributes | Warnings | `className` / `htmlFor` |
| Rendering an object `{obj}` | "Objects are not valid as a React child" | Render fields or use `JSON.stringify` |
| setState after unmount / race | Stale data shown | AbortController / ignore flag in cleanup |

## C#
| Bug | Symptom | Fix |
|---|---|---|
| Missing `;` / brace | CS1002 / CS1513 | Add it |
| Null dereference | `NullReferenceException` | Null checks, `?.`, `??`, nullable reference types |
| `FirstOrDefault().Prop` | `NullReferenceException` | Check for null first |
| `<= array.Length` | `IndexOutOfRangeException` | `<` |
| `.Result` / `.Wait()` | Deadlock | `await` all the way up |
| `async void` | Unobserved exceptions crash the app | `async Task` |
| `throw ex;` | Stack trace lost | `throw;` |
| Empty `catch {}` | Hidden failures | Log or rethrow |
| `int.Parse` on user input | `FormatException` | `int.TryParse` |
| IDisposable without `using` | Resource and connection leaks | `using var x = ...` |
| `new HttpClient()` per request | Socket exhaustion | `IHttpClientFactory` / static instance |
| Collection modified in `foreach` | `InvalidOperationException` | Iterate over `.ToList()` or use a `for` loop going backwards |
| String `+=` in a loop | Slow, allocates a lot | `StringBuilder` |
