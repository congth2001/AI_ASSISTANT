"""Dependency rules for the modular monolith, checked without importing adapters."""
import ast
import importlib.util
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[2]
SRC = BACKEND / "src"
LAYERS = {"domain", "application", "infrastructure", "presentation"}
ADAPTER_LIBRARIES = {
    "fastapi", "starlette", "sqlalchemy", "asyncpg", "pymilvus", "redis",
    "openai", "anthropic", "bcrypt", "jwt", "dependency_injector", "openpyxl",
}
# Only read-side adapters may join another module's persisted models.
READ_MODEL_IMPORTS = {
    ("analytics", "src.modules.sales.infrastructure.models"),
    ("conversations", "src.modules.auth.infrastructure.models"),
}


def imports(source: Path):
    module = ".".join(source.relative_to(BACKEND).with_suffix("").parts)
    package = module.rsplit(".", 1)[0]
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            target = node.module or ""
            if node.level:
                target = importlib.util.resolve_name("." * node.level + target, package)
            yield target
            # Include imported submodules to catch package-level boundary bypasses.
            if target.startswith("src"):
                yield from (target + "." + alias.name for alias in node.names)


def test_layers_only_depend_inward():
    violations = []
    for source in SRC.rglob("*.py"):
        parts = source.relative_to(SRC).parts
        layer = next((part for part in parts[:-1] if part in LAYERS), None)
        if layer is None:
            continue  # Module containers compose all of their own layers.
        for target in imports(source):
            targets = target.split(".")
            target_layer = next((part for part in targets if part in LAYERS), None)
            reason = None
            if layer == "domain":
                common_error = targets[:3] == ["src", "common", "errors"]
                if targets[0] == "src" and target_layer != "domain" and not common_error:
                    reason = "domain imports an outer layer"
                elif targets[0] != "src" and targets[0] not in sys.stdlib_module_names:
                    reason = "domain imports a framework or SDK"
            elif layer == "application":
                if target_layer in {"presentation", "infrastructure"} or targets[0] in ADAPTER_LIBRARIES:
                    reason = "application imports an adapter"
            elif layer == "presentation" and target_layer == "infrastructure":
                reason = "presentation bypasses the application port"
            elif layer == "infrastructure" and target_layer == "presentation":
                reason = "infrastructure imports HTTP concerns"
            if layer in {"domain", "application", "infrastructure"} and targets[0] in {"config"}:
                reason = "inner layer imports the composition root"
            if targets[:2] == ["src", "bootstrap"]:
                reason = "module imports the composition root"
            if reason:
                violations.append(f"{source.relative_to(BACKEND)} -> {target}: {reason}")
    assert not violations, "\n".join(violations)


def test_cross_module_dependencies_are_explicit_and_acyclic():
    edges = {p.name: set() for p in (SRC / "modules").iterdir() if p.is_dir() and not p.name.startswith("_")}
    violations = []
    for source in (SRC / "modules").rglob("*.py"):
        owner = source.relative_to(SRC / "modules").parts[0]
        layer = next((p for p in source.parts if p in LAYERS), None)
        for target in imports(source):
            parts = target.split(".")
            if parts[:2] != ["src", "modules"] or len(parts) < 4 or parts[2] == owner:
                continue
            edges[owner].add(parts[2])
            if source.name == "container.py":
                violations.append(f"{owner}: cross-module wiring belongs in config/container.py")
            if layer in {"domain", "application"} and parts[3] != "domain":
                violations.append(f"{owner}: inner layer must use another module's domain contracts: {target}")
            if parts[3] == "infrastructure" and not any(
                owner == module and (target == allowed or target.startswith(allowed + "."))
                for module, allowed in READ_MODEL_IMPORTS
            ):
                violations.append(f"{owner}: unapproved cross-module infrastructure dependency: {target}")
    assert not violations, "\n".join(violations)

    def visit(module, ancestors):
        assert module not in ancestors, f"Module dependency cycle: {ancestors + [module]}"
        for dependency in edges[module]:
            visit(dependency, ancestors + [module])

    for module in edges:
        visit(module, [])


def test_common_code_never_depends_on_a_business_module():
    violations = [
        f"{source.relative_to(BACKEND)} -> {target}"
        for source in (SRC / "common").rglob("*.py")
        for target in imports(source)
        if target.startswith(("src.modules", "src.bootstrap", "config"))
    ]
    assert not violations, "\n".join(violations)


def test_common_errors_are_framework_independent():
    violations = [
        f"{source.relative_to(BACKEND)} -> {target}"
        for source in (SRC / "common/errors").rglob("*.py")
        for target in imports(source)
        if target.split(".")[0] not in sys.stdlib_module_names
        and target.split(".")[:3] != ["src", "common", "errors"]
    ]
    assert not violations, "\n".join(violations)


def test_all_local_imports_resolve_after_moves():
    violations = []
    entry_points = [BACKEND / name for name in ("main.py", "create_admin.py", "sync_business_data.py", "run_business_etl.py")]
    for directory in ("src", "config", "tests", "scripts", "evals", "etl_business", "migrations"):
        entry_points.extend((BACKEND / directory).rglob("*.py"))
    for source in entry_points:
        for target in imports(source):
            if not target.startswith("src."):
                continue
            # An imported name may be a class/function. Its parent must exist.
            candidate = BACKEND.joinpath(*target.split("."))
            if not candidate.is_dir() and not candidate.with_suffix(".py").is_file():
                candidate = candidate.parent
                if not candidate.is_dir() and not candidate.with_suffix(".py").is_file():
                    violations.append(f"{source.relative_to(BACKEND)} -> {target}")
    assert not violations, "\n".join(violations)
