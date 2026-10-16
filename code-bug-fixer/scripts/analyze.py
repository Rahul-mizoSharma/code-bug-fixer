#!/usr/bin/env python3
"""
analyze.py - static bug finder for Python, FastAPI, JavaScript, React and C#.

Usage:
    python3 analyze.py --file path/to/code.py [--lang auto] [--format text|json] [--compile]
    cat code.js | python3 analyze.py --stdin --lang javascript

Exit codes: 0 = no errors found, 1 = error-level findings, 2 = no code provided / bad input.
Needs only the standard library. Uses `node` / `dotnet` when they are installed.
"""
import argparse
import ast
import builtins
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

FINDINGS = []


def add(line, severity, category, rule, message, fix_hint=""):
    FINDINGS.append({"line": line, "severity": severity, "category": category,
                     "rule": rule, "message": message, "fix_hint": fix_hint})


# ---------------------------------------------------------------- language detection
def detect_language(code, filename=""):
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".cs":
        return "csharp"
    if ext in (".jsx", ".tsx"):
        return "react"
    if ext == ".py":
        return "fastapi" if re.search(r"\bfrom\s+fastapi\b|\bimport\s+fastapi\b", code) else "python"
    if ext in (".js", ".mjs", ".cjs", ".ts"):
        return "react" if _looks_react(code) else "javascript"
    # No useful extension: look at the content.
    if re.search(r"\bfrom\s+fastapi\b|\bimport\s+fastapi\b|FastAPI\(", code):
        return "fastapi"
    if re.search(r"^\s*using\s+System|\bnamespace\s+\w+|\bpublic\s+(static\s+)?(class|void|async)\b|Console\.Write", code, re.M):
        return "csharp"
    if _looks_react(code):
        return "react"
    if re.search(r"^\s*(def|class)\s+\w+.*:\s*$|^\s*import\s+\w+\s*$|^\s*from\s+\w+\s+import\b|print\(", code, re.M) \
            and not re.search(r"[{};]\s*$", code, re.M):
        return "python"
    if re.search(r"\b(function|const|let|var|=>|console\.log|require\()", code):
        return "javascript"
    return "python"


def _looks_react(code):
    return bool(re.search(r"from\s+['\"]react['\"]|\buse(State|Effect|Memo|Callback|Ref|Context)\s*\(|return\s*\(?\s*<[A-Za-z]|</\w+>", code))


# ---------------------------------------------------------------- shared helpers
def strip_c_like(code):
    """Blank out comments and string contents (keeping newlines) so regexes only see code."""
    out, i, n = [], 0, len(code)
    while i < n:
        c, nx = code[i], code[i + 1] if i + 1 < n else ""
        if c == "/" and nx == "/":
            while i < n and code[i] != "\n":
                out.append(" "); i += 1
        elif c == "/" and nx == "*":
            out.append("  "); i += 2
            while i < n and not (code[i] == "*" and i + 1 < n and code[i + 1] == "/"):
                out.append("\n" if code[i] == "\n" else " "); i += 1
            out.append("  "); i += 2
        elif c in "\"'`":
            q = c; out.append(q); i += 1
            while i < n and code[i] != q:
                if code[i] == "\\":
                    out.append("  "); i += 2; continue
                if code[i] == "\n" and q != "`":
                    break
                out.append("\n" if code[i] == "\n" else " "); i += 1
            if i < n and code[i] == q:
                out.append(q); i += 1
        else:
            out.append(c); i += 1
    return "".join(out)


def check_brackets(clean, check_jsx=False):
    pairs, stack = {")": "(", "]": "[", "}": "{"}, []
    for ln, line in enumerate(clean.split("\n"), 1):
        for col, ch in enumerate(line, 1):
            if ch in "([{":
                stack.append((ch, ln, col))
            elif ch in ")]}":
                if not stack:
                    add(ln, "error", "syntax", "unmatched-bracket", f"Unexpected closing '{ch}' at col {col}.",
                        "Remove it or add the matching opening bracket.")
                    return
                op, oln, ocol = stack.pop()
                if op != pairs[ch]:
                    add(ln, "error", "syntax", "mismatched-bracket",
                        f"'{ch}' at col {col} closes '{op}' opened on line {oln}.",
                        "Check the nesting; a bracket is missing or in the wrong order.")
                    return
    for op, oln, ocol in stack[-3:]:
        add(oln, "error", "syntax", "unclosed-bracket", f"'{op}' opened at col {ocol} is never closed.",
            "Add the missing closing bracket.")
    if check_jsx:
        _check_jsx_tags(clean)


def _check_jsx_tags(clean):
    stack = []
    for m in re.finditer(r"<(/?)([A-Za-z][\w.]*)?([^<>]*?)(/?)>", clean):
        closing, name, attrs, selfclose = m.group(1), m.group(2) or "", m.group(3), m.group(4)
        ln = clean.count("\n", 0, m.start()) + 1
        prev = clean[max(0, m.start() - 1):m.start()]
        if re.match(r"[\w)\]]", prev) and not closing:  # probably a comparison or a generic
            continue
        if selfclose or name.lower() in ("br", "img", "input", "hr", "meta", "link"):
            continue
        if closing:
            if stack and stack[-1][0] == name:
                stack.pop()
            elif any(s[0] == name for s in stack):
                while stack and stack[-1][0] != name:
                    n2, l2 = stack.pop()
                    add(l2, "error", "syntax", "unclosed-jsx-tag", f"JSX tag <{n2 or '>'}> is not closed.",
                        f"Add </{n2}> or make it self-closing <{n2} />.")
                stack.pop()
        else:
            stack.append((name, ln))


def line_of(code, idx):
    return code.count("\n", 0, idx) + 1


def regex_rules(clean, rules):
    for pattern, sev, cat, rule, msg, hint in rules:
        for m in re.finditer(pattern, clean, re.M):
            add(line_of(clean, m.start()), sev, cat, rule, msg, hint)


# ---------------------------------------------------------------- Python / FastAPI
BUILTIN_NAMES = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__builtins__", "self", "cls"}


class PyVisitor(ast.NodeVisitor):
    def __init__(self, fastapi=False):
        self.fastapi = fastapi
        self.defined, self.used = set(BUILTIN_NAMES), []
        self.func_stack = []
        self.routes = {}

    # Collect names defined anywhere (an approximation that ignores scope).
    def _def(self, name):
        self.defined.add(name)

    def visit_Import(self, node):
        for a in node.names:
            self._def((a.asname or a.name).split(".")[0])

    def visit_ImportFrom(self, node):
        for a in node.names:
            self._def(a.asname or a.name)

    def visit_ClassDef(self, node):
        self._def(node.name); self.generic_visit(node)

    def visit_Global(self, node):
        for n in node.names: self._def(n)

    def visit_arg(self, node):
        self._def(node.arg)

    def visit_ExceptHandler(self, node):
        if node.name: self._def(node.name)
        if node.type is None:
            add(node.lineno, "warning", "runtime", "bare-except",
                "Bare 'except:' also catches KeyboardInterrupt/SystemExit and hides real errors.",
                "Use 'except Exception as e:' or a specific exception type.")
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            add(node.lineno, "warning", "logic", "swallowed-exception", "Exception is silently ignored (except: pass).",
                "Log or re-raise the exception.")
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self._def(node.id)
        else:
            self.used.append((node.id, node.lineno))

    def visit_FunctionDef(self, node, is_async=False):
        self._def(node.name)
        for d in node.args.defaults + node.args.kw_defaults:
            if isinstance(d, (ast.List, ast.Dict, ast.Set)) or (
                    isinstance(d, ast.Call) and getattr(d.func, "id", "") in ("list", "dict", "set")):
                add(node.lineno, "warning", "runtime", "mutable-default-arg",
                    f"Function '{node.name}' uses a mutable default argument; it is shared between calls.",
                    "Use None as default and create the object inside the function.")
        if self.fastapi:
            self._fastapi_route(node, is_async)
        self.func_stack.append((node, is_async))
        self.generic_visit(node)
        self.func_stack.pop()

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node, is_async=True)

    def visit_Lambda(self, node):
        self.generic_visit(node)

    def visit_Compare(self, node):
        for op, right in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(right, ast.Constant) and right.value is None:
                add(node.lineno, "info", "style", "none-comparison", "Comparison to None with ==/!=.",
                    "Use 'is None' / 'is not None'.")
            if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(right, ast.Constant) \
                    and isinstance(right.value, (str, int, float)) and not isinstance(right.value, bool):
                add(node.lineno, "warning", "logic", "is-literal",
                    "'is' compares identity, not value; the result with literals is unreliable.", "Use == / !=.")
        self.generic_visit(node)

    def visit_For(self, node):
        if isinstance(node.iter, ast.Name):
            target = node.iter.id
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                        and isinstance(sub.func.value, ast.Name) and sub.func.value.id == target \
                        and sub.func.attr in ("remove", "append", "pop", "insert", "clear"):
                    add(sub.lineno, "warning", "runtime", "mutate-while-iterating",
                        f"'{target}' is modified while being iterated; items get skipped or the loop never ends.",
                        f"Iterate over a copy (for x in {target}[:]) or build a new list.")
                    break
        self.generic_visit(node)

    def visit_Call(self, node):
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else ""
        dotted = _dotted(fn)
        if name == "open" and not self._inside_with(node):
            add(node.lineno, "info", "runtime", "open-without-with",
                "File is opened without a context manager; it may not be closed on error.",
                "Use 'with open(...) as f:'.")
        if name == "eval" or name == "exec":
            add(node.lineno, "warning", "security", "eval-usage", f"'{name}' runs arbitrary code.",
                "Use ast.literal_eval or explicit parsing.")
        if self.func_stack and self.func_stack[-1][1]:  # inside async def
            if dotted in ("time.sleep",) or dotted.startswith("requests."):
                add(node.lineno, "warning", "performance", "blocking-call-in-async",
                    f"Blocking call '{dotted}' inside async function blocks the event loop.",
                    "Use 'await asyncio.sleep()' / httpx.AsyncClient, or make the function sync (def).")
        self.generic_visit(node)

    def visit_Return(self, node):
        if self.fastapi and isinstance(node.value, ast.Call) and _dotted(node.value.func).endswith("HTTPException"):
            add(node.lineno, "error", "logic", "return-httpexception",
                "HTTPException is returned instead of raised; the client gets 200 with the error serialized.",
                "Use 'raise HTTPException(...)'.")
        self.generic_visit(node)

    def visit_With(self, node):
        for item in node.items:
            item.context_expr._in_with = True
        self.generic_visit(node)
    visit_AsyncWith = visit_With

    def _inside_with(self, node):
        return getattr(node, "_in_with", False)

    def _fastapi_route(self, node, is_async):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) \
                    and dec.func.attr in ("get", "post", "put", "delete", "patch") and dec.args \
                    and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                path, method = dec.args[0].value, dec.func.attr.upper()
                key = (method, path)
                if key in self.routes:
                    add(node.lineno, "warning", "logic", "duplicate-route",
                        f"{method} {path} is already defined on line {self.routes[key]}; this handler is never reached.",
                        "Rename the path or merge the handlers.")
                self.routes[key] = node.lineno
                params = {a.arg for a in node.args.args + node.args.kwonlyargs}
                for p in re.findall(r"{(\w+)(?::\w+)?}", path):
                    if p not in params:
                        add(node.lineno, "error", "runtime", "missing-path-param",
                            f"Path parameter '{p}' in '{path}' is not a parameter of '{node.name}'.",
                            f"Add '{p}' to the function signature with a type annotation.")


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr); node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def analyze_python(code, fastapi=False):
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        add(e.lineno or 0, "error", "syntax", "syntax-error",
            f"{e.msg} (col {e.offset})" + (f": {e.text.strip()}" if e.text else ""),
            "Fix this first; nothing after a syntax error is analyzed.")
        return
    v = PyVisitor(fastapi)
    v.visit(tree)
    reported = set()
    for name, ln in v.used:
        if name not in v.defined and name not in reported:
            reported.add(name)
            add(ln, "error", "runtime", "undefined-name", f"Name '{name}' is used but never defined or imported (NameError).",
                "Define/import it or fix the spelling.")
    for i, line in enumerate(code.split("\n"), 1):
        if "\t" in line[:len(line) - len(line.lstrip())] and "    " in code:
            add(i, "warning", "syntax", "mixed-indentation", "Tabs and spaces are mixed in indentation.",
                "Use 4 spaces consistently.")
            break


# ---------------------------------------------------------------- JavaScript / React
JS_RULES = [
    (r"\b(if|while)\s*\([^=!<>()]*[^=!<>]=[^=>][^)]*\)", "warning", "logic", "assignment-in-condition",
     "Assignment '=' inside a condition; this is almost always meant to be a comparison.", "Use === for comparison."),
    (r"[^=!]==[^=]|!=[^=]", "info", "logic", "loose-equality",
     "Loose equality (==/!=) does type coercion ('' == 0 is true).", "Use === / !==."),
    (r"[=!]==?\s*NaN\b", "error", "logic", "nan-comparison", "Comparisons with NaN are always false.",
     "Use Number.isNaN(x)."),
    (r"\.forEach\(\s*async\b", "warning", "runtime", "async-foreach",
     "forEach does not wait for async callbacks; code after it runs before they finish.",
     "Use for...of with await, or await Promise.all(arr.map(async ...))."),
    (r"(?<!await )(?<!return )\bfetch\([^)]*\)\s*\.\s*json\(", "error", "runtime", "fetch-json-without-await",
     "fetch() returns a Promise; calling .json() on it directly fails.", "const res = await fetch(url); const data = await res.json();"),
    (r"(?:const|let|var)\s+\w+\s*=\s*fetch\(", "warning", "runtime", "missing-await-fetch",
     "fetch() result stored without await; the variable holds a Promise, not a Response.", "Add await (inside an async function)."),
    (r"\bparseInt\(\s*[^,()]+\)", "info", "logic", "parseint-radix", "parseInt without radix.", "Use parseInt(x, 10)."),
    (r"for\s*\(\s*var\s+\w+[^)]*\)\s*\{?[^}]*setTimeout", "warning", "logic", "var-closure-loop",
     "'var' in a loop with async callback: all callbacks see the final value.", "Use 'let' instead of 'var'."),
    (r"\bvar\s+", "info", "style", "var-usage", "'var' is function-scoped and hoisted.", "Use let/const."),
    (r"\beval\s*\(", "warning", "security", "eval-usage", "eval executes arbitrary code.", "Avoid eval; use JSON.parse or explicit logic."),
    (r"JSON\.parse\(", "info", "runtime", "json-parse-unguarded",
     "JSON.parse throws on invalid input.", "Wrap in try/catch if the input is untrusted."),
    (r"\.length\s*<=\s*\w+\s*;[^)]*\)|<=\s*\w+\.length\s*;", "warning", "logic", "off-by-one",
     "Loop uses <= length; the last iteration reads index length (undefined).", "Use < length."),
]

REACT_RULES = [
    (r"useEffect\(\s*async\b", "error", "runtime", "async-effect",
     "useEffect callback must not be async (it returns a Promise instead of a cleanup function).",
     "Define an async function inside the effect and call it."),
    (r"<[a-z][^>]*\sclass=", "warning", "runtime", "jsx-class", "'class' attribute in JSX.", "Use className."),
    (r"<[a-z][^>]*\sfor=", "warning", "runtime", "jsx-for", "'for' attribute in JSX.", "Use htmlFor."),
    (r"\bon[A-Z]\w*=\{\s*\w+(\.\w+)*\([^)]*\)\s*\}", "error", "runtime", "handler-invoked",
     "Event handler is called during render instead of passed; this can cause an infinite re-render loop.",
     "Pass a function: onClick={() => fn(arg)} or onClick={fn}."),
    (r"this\.state\.\w+\s*=[^=]", "error", "logic", "direct-state-mutation",
     "Direct this.state mutation does not re-render.", "Use this.setState(...)."),
    (r"\b(\w+)\.(push|pop|splice|sort|reverse|shift|unshift)\([^)]*\)\s*;?\s*\n\s*set\w+\(\s*\1\s*\)", "error", "logic",
     "state-mutation", "State array is mutated then set with the same reference; React may skip the re-render.",
     "Create a new array: setItems([...items, x])."),
]


def analyze_js(code, react=False, filename=""):
    clean = strip_c_like(code)
    node = shutil.which("node")
    syntax_done = False
    if node and not react and not _looks_react(code):
        ext = ".mjs" if re.search(r"^\s*(import|export)\b", code, re.M) else ".js"
        with tempfile.NamedTemporaryFile("w", suffix=ext, delete=False) as tf:
            tf.write(code); path = tf.name
        try:
            r = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=20)
            syntax_done = True
            if r.returncode != 0:
                m = re.search(r":(\d+)\n", r.stderr)
                msg = next((l for l in r.stderr.splitlines() if "Error" in l), r.stderr.strip()[:200])
                add(int(m.group(1)) if m else 0, "error", "syntax", "syntax-error", msg,
                    "Fix this first; it prevents the file from running.")
        except Exception:
            syntax_done = False
        finally:
            os.unlink(path)
    if not syntax_done or react:
        check_brackets(clean, check_jsx=react)
    regex_rules(clean, JS_RULES)
    if react:
        regex_rules(clean, REACT_RULES)
        _react_structural(clean)


def _react_structural(clean):
    lines = clean.split("\n")
    # Hooks inside conditions/loops: track blocks opened by if/for/while.
    stack = []
    for ln, line in enumerate(lines, 1):
        opener = bool(re.search(r"\b(if|for|while|switch)\b\s*\(.*\)\s*\{\s*$|\belse\s*\{\s*$", line))
        if re.search(r"\buse[A-Z]\w*\s*\(", line) and any(stack):
            add(ln, "error", "runtime", "conditional-hook",
                "Hook called inside a condition or loop; this breaks the Rules of Hooks (hook order changes between renders).",
                "Call hooks unconditionally at the top level of the component; put the condition inside the hook.")
        for ch in line:
            if ch == "{":
                stack.append(opener); opener = False
            elif ch == "}" and stack:
                stack.pop()
        if re.match(r"\s*(if|for|while)\b.*\)\s*$", line) and ln < len(lines) \
                and re.search(r"\buse[A-Z]\w*\s*\(", lines[ln]):
            add(ln + 1, "error", "runtime", "conditional-hook", "Hook called conditionally.", "Move the hook to the top level.")
    # .map rendering JSX without key
    for m in re.finditer(r"\.map\(\s*\(?[\w\s,{}]*\)?\s*=>\s*\(?\s*<(\w+)([^>]*)>", clean):
        if "key=" not in m.group(2):
            add(line_of(clean, m.start()), "warning", "runtime", "missing-key",
                "List items rendered with .map() have no 'key' prop.", "Add a stable unique key, e.g. key={item.id}.")
    # useEffect without deps that sets state, which causes an infinite loop
    for m in re.finditer(r"useEffect\(", clean):
        depth, i = 0, m.end() - 1
        while i < len(clean):
            depth += clean[i] == "("; depth -= clean[i] == ")"
            if depth == 0:
                break
            i += 1
        body = clean[m.end():i]
        top = re.sub(r"\{[^{}]*\}", "", re.sub(r"\{[^{}]*\}", "", body))
        has_deps = bool(re.search(r",\s*\[[^\]]*\]\s*$", body.strip()))
        if not has_deps and re.search(r"\bset[A-Z]\w*\(", body):
            add(line_of(clean, m.start()), "error", "runtime", "effect-infinite-loop",
                "useEffect has no dependency array and sets state; it re-runs every render and loops forever.",
                "Add a dependency array, e.g. useEffect(() => {...}, []).")
        elif not has_deps and not top.strip().endswith("]"):
            add(line_of(clean, m.start()), "info", "performance", "effect-no-deps",
                "useEffect has no dependency array; it runs after every render.", "Add the correct dependency array.")


# ---------------------------------------------------------------- C#
CS_RULES = [
    (r"\basync\s+void\s+(?!\w+\s*\(\s*object\b)", "warning", "runtime", "async-void",
     "async void methods can't be awaited and their exceptions crash the process.", "Return Task (except event handlers)."),
    (r"\.Result\b|\.Wait\(\)|\.GetAwaiter\(\)\.GetResult\(\)", "warning", "runtime", "sync-over-async",
     "Blocking on a Task (.Result/.Wait) can deadlock (UI/ASP.NET contexts) and wastes threads.", "Use await."),
    (r"catch\s*(\([^)]*\))?\s*\{\s*\}", "warning", "logic", "empty-catch", "Empty catch block swallows exceptions.",
     "Log, handle or rethrow the exception."),
    (r"\bthrow\s+\w+\s*;", "warning", "logic", "throw-ex", "'throw ex;' resets the stack trace.", "Use 'throw;'."),
    (r"new\s+HttpClient\s*\(", "warning", "performance", "httpclient-new",
     "Creating HttpClient per call can exhaust sockets.", "Reuse a static instance or use IHttpClientFactory."),
    (r"^(?!\s*using\b).*\bnew\s+(SqlConnection|SqlCommand|StreamReader|StreamWriter|FileStream)\s*\(",
     "warning", "runtime", "undisposed-resource", "IDisposable resource is created without a 'using'.",
     "Wrap it: using var conn = new SqlConnection(...);"),
    (r"(FirstOrDefault|SingleOrDefault|Find)\([^)]*\)\s*\.\s*\w+", "warning", "runtime", "null-deref-ordefault",
     "Member accessed directly on a *OrDefault()/Find() result; it may be null (NullReferenceException).",
     "Check for null or use ?. ."),
    (r"\bint\.Parse\(|Convert\.ToInt32\(", "info", "runtime", "parse-unchecked",
     "int.Parse throws FormatException on invalid input.", "Use int.TryParse."),
    (r"\bfor\s*\([^;]*;\s*\w+\s*<=\s*\w+\.(Length|Count)\b", "error", "runtime", "off-by-one",
     "Loop uses <= Length/Count; the last iteration throws IndexOutOfRangeException.", "Use < ."),
]


def analyze_csharp(code, compile_=False):
    clean = strip_c_like(code)
    check_brackets(clean)
    lines = clean.split("\n")
    stmt_start = re.compile(r"^\s*(?:var|int|string|bool|double|decimal|return|await|throw|[\w<>\[\].]+\s+\w+\s*=|\w+(\.\w+)*\s*(\(|=|\+\+|--))")
    no_semi = re.compile(r"^\s*(if|else|for|foreach|while|switch|case|default|try|catch|finally|using\s*\(|namespace|class|struct|interface|enum|public|private|protected|internal|static|\[|#|//|get|set|=>|\.|\?|:)")
    for i, line in enumerate(lines):
        s = line.rstrip()
        if not s.strip() or no_semi.match(s) or not stmt_start.match(s):
            continue
        if s.endswith((";", "{", "}", ",", "(", "[", "=>", "+", "-", "*", "/", "&&", "||", "?", ":", "=")):
            continue
        nxt = next((l.strip() for l in lines[i + 1:] if l.strip()), "")
        if nxt.startswith(("{", ".", "?", ":", "+", "&&", "||", ")", "=>")):
            continue
        add(i + 1, "error", "syntax", "missing-semicolon", "Statement appears to be missing a ';'.", "Add ';' at the end of the line.")
    regex_rules(clean, CS_RULES)
    m = re.search(r"\b(for|foreach|while)\b[^{]*\{[^{}]*\b\w+\s*\+=\s*\"", clean)
    if m:
        add(line_of(clean, m.start()), "info", "performance", "string-concat-loop",
            "String concatenation in a loop allocates a new string each iteration.", "Use StringBuilder.")
    if compile_ and shutil.which("dotnet"):
        _dotnet_compile(code)


def _dotnet_compile(code):
    d = tempfile.mkdtemp()
    try:
        subprocess.run(["dotnet", "new", "console", "-o", d, "--force"], capture_output=True, timeout=120)
        with open(os.path.join(d, "Program.cs"), "w") as f:
            f.write(code)
        r = subprocess.run(["dotnet", "build", d, "-nologo", "-v", "q"], capture_output=True, text=True, timeout=300)
        for m in re.finditer(r"Program\.cs\((\d+),(\d+)\): error (\w+): (.+?) \[", r.stdout):
            add(int(m.group(1)), "error", "syntax", m.group(3), m.group(4), "Compiler error from dotnet build.")
    except Exception as e:
        add(0, "info", "style", "compile-skipped", f"dotnet build failed to run: {e}", "")
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Static bug finder (Python, FastAPI, JS, React, C#).")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--file", help="Path to the code file.")
    src.add_argument("--stdin", action="store_true", help="Read code from stdin.")
    ap.add_argument("--lang", default="auto", choices=["auto", "python", "fastapi", "javascript", "react", "csharp"])
    ap.add_argument("--format", default="text", choices=["text", "json"])
    ap.add_argument("--compile", action="store_true", help="C#: also run dotnet build when the SDK is installed.")
    a = ap.parse_args()

    code, filename = "", ""
    if a.file:
        if not os.path.isfile(a.file):
            print(f"NO_CODE_PROVIDED: file not found: {a.file}"); sys.exit(2)
        filename = a.file
        with open(a.file, encoding="utf-8", errors="replace") as f:
            code = f.read()
    elif a.stdin and not sys.stdin.isatty():
        code = sys.stdin.read()
    if not code.strip():
        print("NO_CODE_PROVIDED: no code to analyze. Ask the user to paste or upload their code first.")
        sys.exit(2)

    lang = a.lang if a.lang != "auto" else detect_language(code, filename)
    if lang in ("python", "fastapi"):
        analyze_python(code, fastapi=(lang == "fastapi"))
    elif lang in ("javascript", "react"):
        analyze_js(code, react=(lang == "react"), filename=filename)
    else:
        analyze_csharp(code, compile_=a.compile)

    # Remove duplicates and sort
    seen, uniq = set(), []
    for f in sorted(FINDINGS, key=lambda x: (x["line"], {"error": 0, "warning": 1, "info": 2}[x["severity"]])):
        k = (f["line"], f["rule"])
        if k not in seen:
            seen.add(k); uniq.append(f)
    errors = sum(f["severity"] == "error" for f in uniq)

    if a.format == "json":
        print(json.dumps({"language": lang, "lines": code.count("\n") + 1, "errors": errors, "findings": uniq}, indent=2))
    else:
        print(f"Language: {lang} | Lines: {code.count(chr(10)) + 1} | Findings: {len(uniq)} ({errors} error(s))")
        print("-" * 72)
        if not uniq:
            print("No issues detected by static rules. Still review the logic manually.")
        for f in uniq:
            print(f"[{f['severity'].upper():7}] L{f['line']:<4} {f['category']:<11} {f['rule']}")
            print(f"          {f['message']}")
            if f["fix_hint"]:
                print(f"          Fix: {f['fix_hint']}")
        print("-" * 72)
        print("Note: these are heuristic leads. Confirm each one and check for logic bugs the rules can't see.")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
