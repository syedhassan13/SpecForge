"""
Python iContract + CrossHair verification backend.

Provides the PythonContractBackend class that uses iContract for
runtime contract checking and CrossHair for static contract analysis.
This represents the mainstream-language contract approach compared
to Dafny's purpose-built verification language.
"""

import importlib
import io
import os
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Optional

from src.schemas import (
    VerificationResult,
    VerificationStatus,
    TestResult,
    TestStatus,
)


class PythonContractBackend:
    """Backend for Python contract-based verification using iContract + CrossHair.

    This backend provides two verification modes:
    1. Static analysis via CrossHair (attempts to find counterexamples).
    2. Runtime contract checking via iContract (design-by-contract decorators).

    Attributes:
        crosshair_timeout: Seconds for CrossHair analysis per function.
        test_timeout: Seconds for runtime test execution.
    """

    def __init__(
        self,
        crosshair_timeout: int = 30,
        test_timeout: int = 30,
    ):
        self.crosshair_timeout = crosshair_timeout
        self.test_timeout = test_timeout

    def verify(self, code: str) -> VerificationResult:
        """Run CrossHair static analysis on Python code with iContract specs.

        CrossHair uses symbolic execution to find counterexamples that
        violate iContract preconditions, postconditions, or invariants.

        Args:
            code: Python source code with iContract decorators.

        Returns:
            VerificationResult with status and any counterexamples found.
        """
        start = time.time()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir="."
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "crosshair",
                    "check",
                    "--analysis_kind", "icontract",
                    "--per_condition_timeout", str(self.crosshair_timeout),
                    tmp_path,
                ],
                capture_output=True,
                text=True,
                timeout=self.crosshair_timeout * 3,
            )

            elapsed = time.time() - start
            output = result.stdout + "\n" + result.stderr

            errors = []
            warnings = []

            if result.returncode != 0:
                # Parse CrossHair counterexamples
                for line in output.splitlines():
                    line = line.strip()
                    if line and "error" in line.lower():
                        errors.append(line)
                    elif line and ("counterexample" in line.lower() or "fail" in line.lower()):
                        errors.append(line)
                    elif line and "warning" in line.lower():
                        warnings.append(line)

                if not errors:
                    errors = [output.strip()] if output.strip() else ["CrossHair analysis failed"]

            status = (
                VerificationStatus.VERIFIED
                if result.returncode == 0 and not errors
                else VerificationStatus.FAILED
            )

            return VerificationResult(
                status=status,
                errors=errors,
                warnings=warnings,
                time_seconds=elapsed,
                verified_conditions=1 if status == VerificationStatus.VERIFIED else 0,
                total_conditions=1,
            )

        except subprocess.TimeoutExpired:
            return VerificationResult(
                status=VerificationStatus.TIMEOUT,
                errors=["CrossHair timed out after {} seconds".format(
                    self.crosshair_timeout * 3
                )],
                time_seconds=time.time() - start,
            )
        except Exception as e:
            return VerificationResult(
                status=VerificationStatus.ERROR,
                errors=["CrossHair error: {}".format(str(e))],
                time_seconds=time.time() - start,
            )
        finally:
            os.unlink(tmp_path)

    def run_tests(self, code: str, test_code: str) -> TestResult:
        """Execute Python tests with iContract runtime checking enabled.

        iContract decorators (@icontract.require, @icontract.ensure) are
        enforced at runtime, so any contract violation raises an exception
        during test execution.

        Args:
            code: Python source with iContract decorators.
            test_code: Python test functions (using assert statements).

        Returns:
            TestResult with pass/fail details.
        """
        start = time.time()
        full_code = code + "\n\n" + test_code

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(full_code)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=self.test_timeout,
            )

            elapsed = time.time() - start

            if result.returncode == 0:
                return TestResult(
                    status=TestStatus.PASSED,
                    passed=1,
                    total=1,
                    time_seconds=elapsed,
                )
            else:
                error = result.stderr or result.stdout
                failures = []

                # Check for iContract violations
                if "icontract" in error.lower():
                    failures.append("Contract violation: " + error.strip())
                else:
                    failures.append(error.strip())

                return TestResult(
                    status=TestStatus.FAILED,
                    passed=0,
                    total=1,
                    failures=failures,
                    time_seconds=elapsed,
                )

        except subprocess.TimeoutExpired:
            return TestResult(
                status=TestStatus.TIMEOUT,
                failures=["Test execution timed out"],
                time_seconds=self.test_timeout,
            )
        finally:
            os.unlink(tmp_path)

    def guard_spec_integrity(
        self, original_spec: str, generated_code: str
    ) -> tuple[bool, list[str]]:
        """Check that iContract decorators have not been weakened or removed.

        Verifies that all @icontract.require and @icontract.ensure decorators
        from the original specification are present in the generated code.

        Args:
            original_spec: Original Python code with iContract decorators.
            generated_code: LLM-generated code to check.

        Returns:
            Tuple of (spec_intact: bool, violations: list[str]).
        """
        violations = []

        orig_requires = self._extract_contracts(original_spec, "require")
        orig_ensures = self._extract_contracts(original_spec, "ensure")

        gen_requires = self._extract_contracts(generated_code, "require")
        gen_ensures = self._extract_contracts(generated_code, "ensure")

        for req in orig_requires:
            normalized = self._normalize(req)
            if not any(self._normalize(g) == normalized for g in gen_requires):
                violations.append("Missing precondition: {}".format(req.strip()))

        for ens in orig_ensures:
            normalized = self._normalize(ens)
            if not any(self._normalize(g) == normalized for g in gen_ensures):
                violations.append("Missing postcondition: {}".format(ens.strip()))

        return (len(violations) == 0, violations)

    @staticmethod
    def _extract_contracts(code: str, kind: str) -> list[str]:
        """Extract iContract decorator lambda expressions."""
        import re
        pattern = rf"@icontract\.{kind}\(lambda\s+.*?:.*?\)"
        return re.findall(pattern, code, re.DOTALL)

    @staticmethod
    def _normalize(s: str) -> str:
        return " ".join(s.split())
