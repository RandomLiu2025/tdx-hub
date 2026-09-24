"""Install and test the wheel outside the checkout, without external TDX packages."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    assert wheel.is_file(), wheel
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}

    def run(*command, cwd):
        subprocess.run(command, cwd=cwd, env=env, check=True)

    with tempfile.TemporaryDirectory(prefix="tdxhub-wheel-") as directory:
        work = Path(directory)
        venv = work / "venv"
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run("uv", "venv", "--python", sys.executable, str(venv), cwd=work)
        # The wheel supplies the project itself; its dependencies use the checked-in lock.
        requirements = work / "requirements.txt"
        run(
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--extra",
            "test",
            "--no-emit-project",
            "--output-file",
            str(requirements),
            cwd=ROOT,
        )
        run("uv", "pip", "install", "--python", str(python), "-r", str(requirements), str(wheel), cwd=work)
        run("uv", "pip", "check", "--python", str(python), cwd=work)
        tests = work / "tests"
        for package in ("", "tdx", "quotes"):
            target = tests / package
            target.mkdir(parents=True, exist_ok=True)
            (target / "__init__.py").touch()
        for relative in (
            "tdx/test_protocol.py",
            "tdx/test_transport.py",
            "tdx/test_volume.py",
            "tdx/test_price_decoding.py",
            "tdx/test_transaction_precision.py",
            "tdx/test_finance_info.py",
            "quotes/test_data_accuracy.py",
            "test_minute.py",
            "tdx/test_module_contract.py",
            "tdx/test_financial_download.py",
            "quotes/test_quotes_batch.py",
            "quotes/test_failover.py",
            "quotes/test_capabilities.py",
        ):
            shutil.copy2(ROOT / "tests" / relative, tests / relative)
        shutil.copytree(ROOT / "tests/tdx/fixtures", tests / "tdx/fixtures")
        (tests / "test_install.py").write_text("""
import importlib.util
import importlib.abc
import pkgutil
import sys
from pathlib import Path
import tdxhub

def test_import_is_installed_and_external_dependencies_absent():
    assert Path(tdxhub.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    for name in ("tdxpy", "pytdx", "Cython"):
        assert importlib.util.find_spec(name) is None, name

def test_every_tdx_module_loads_without_external_packages():
    class RejectExternal(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0].lower() in {"tdxpy", "pytdx", "cython"}:
                raise ModuleNotFoundError(fullname)

    guard = RejectExternal()
    sys.meta_path.insert(0, guard)
    try:
        import tdxhub.tdx as tdx
        for module in pkgutil.walk_packages(tdx.__path__, tdx.__name__ + "."):
            loaded = importlib.import_module(module.name)
            assert Path(loaded.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
        for name in ("tdxhub.parse", "tdxhub.reader", "tdxhub.financial.financial",
                     "tdxhub.tools.customize", "tdxhub.contrib.compat", "tdxhub.__main__"):
            importlib.import_module(name)
    finally:
        sys.meta_path.remove(guard)
    assert not any(name.split(".")[0].lower() in {"tdx", "tdxpy", "pytdx", "cython"} for name in sys.modules)
""")
        prefix = ("uv", "run", "--no-project", "--python", str(python), "python", "-I")
        run(*prefix, "-m", "pytest", "-q", str(tests), cwd=work)
        run(*prefix, "-m", "tdxhub", "--help", cwd=work)
    print("Independent wheel installation, protocol tests and CLI smoke passed")


if __name__ == "__main__":
    main()
