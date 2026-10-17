"""
Dafny verification backend.

Provides the DafnyBackend class that interfaces with the Dafny verifier
to check generated code against formal specifications (preconditions,
postconditions, loop invariants). Includes safety guards to prevent
the LLM from weakening or removing specifications.
"""

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from src.schemas import (
    VerificationResult,
    VerificationStatus,
    TestResult,
    TestStatus,
)


class DafnyBackend:
    """Backend for Dafny formal verification and runtime testing.

    This backend:
    1. Verifies Dafny code against its specification using `dafny verify`.
    2. Runs runtime tests by compiling and executing Dafny test methods.
    3. Guards against spec tampering (ensures LLM doesn't weaken the spec).

    Attributes:
        dafny_path: Path to the Dafny executable.
        timeout: Maximum seconds for verification/compilation.
        z3_timeout: Z3 solver timeout in seconds.
    """

    def __init__(
        self,
        dafny_path: str = "dafny",
        timeout: int = 60,
        z3_timeout: int = 30,
    ):
        self.dafny_path = dafny_path
        self.timeout = timeout
        self.z3_timeout = z3_timeout

    def verify(self, code: str) -> VerificationResult:
        """Run Dafny formal verification on the given code.

        Args:
            code: Complete Dafny source code including specification.

        Returns:
            VerificationResult with status, errors, and timing.
        """
        start = time.time()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".dfy", delete=False
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [
                    self.dafny_path,
                    "verify",
                    "--verification-time-limit", str(self.z3_timeout),
                    tmp_path,
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            elapsed = time.time() - start
            stdout = result.stdout
            stderr = result.stderr
            output = stdout + "\n" + stderr

            # Parse Dafny output
            errors = self._parse_errors(output)
            warnings = self._parse_warnings(output)

            # Count verified vs total conditions
            verified, total = self._count_conditions(output)

            if result.returncode == 0 and not errors:
                status = VerificationStatus.VERIFIED
            else:
                status = VerificationStatus.FAILED

            return VerificationResult(
                status=status,
                errors=errors,
                warnings=warnings,
                time_seconds=elapsed,
                verified_conditions=verified,
                total_conditions=total,
            )

        except subprocess.TimeoutExpired:
            return VerificationResult(
                status=VerificationStatus.TIMEOUT,
                errors=["Verification timed out after {} seconds".format(self.timeout)],
                time_seconds=self.timeout,
            )
        except FileNotFoundError:
            return VerificationResult(
                status=VerificationStatus.ERROR,
                errors=[
                    "Dafny not found at '{}'. Install Dafny or set dafny_path.".format(
                        self.dafny_path
                    )
                ],
            )
        finally:
            os.unlink(tmp_path)

    def run_tests(self, code: str, test_code: str) -> TestResult:
        """Compile and run Dafny test methods.

        Args:
            code: The main Dafny implementation code.
            test_code: Dafny test methods (Main method with assertions).

        Returns:
            TestResult with pass/fail counts and failure details.
        """
        start = time.time()
        full_code = code + "\n\n" + test_code

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".dfy", delete=False
        ) as f:
            f.write(full_code)
            tmp_path = f.name

        try:
            # Compile to Python target (no .NET required)
            out_dir = tempfile.mkdtemp()
            compile_result = subprocess.run(
                [
                    self.dafny_path,
                    "run",
                    "--target", "py",
                    "--no-verify",
                    tmp_path,
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=out_dir,
            )

            elapsed = time.time() - start

            if compile_result.returncode == 0:
                return TestResult(
                    status=TestStatus.PASSED,
                    passed=1,
                    total=1,
                    time_seconds=elapsed,
                )
            else:
                error_msg = compile_result.stderr or compile_result.stdout
                return TestResult(
                    status=TestStatus.FAILED,
                    passed=0,
                    total=1,
                    failures=[error_msg.strip()],
                    time_seconds=elapsed,
                )

        except subprocess.TimeoutExpired:
            return TestResult(
                status=TestStatus.TIMEOUT,
                failures=["Test execution timed out"],
                time_seconds=self.timeout,
            )
        except FileNotFoundError:
            return TestResult(
                status=TestStatus.ERROR,
                failures=["Dafny not found"],
            )
        finally:
            os.unlink(tmp_path)

    def guard_spec_integrity(
        self, original_spec: str, generated_code: str
    ) -> tuple[bool, list[str]]:
        """Check that the LLM has not weakened or removed the specification.

        Compares the specification annotations (requires, ensures, invariant)
        in the generated code against the original specification.

        Args:
            original_spec: The original Dafny specification.
            generated_code: The LLM-generated code to check.

        Returns:
            Tuple of (spec_intact: bool, violations: list[str]).
        """
        violations = []

        # Extract specification clauses from both
        orig_clauses = self._extract_spec_clauses(original_spec)
        gen_clauses = self._extract_spec_clauses(generated_code)

        # Check that all original clauses are preserved
        for clause_type, clauses in orig_clauses.items():
            gen_set = set(gen_clauses.get(clause_type, []))
            for clause in clauses:
                normalized = self._normalize_whitespace(clause)
                found = any(
                    self._normalize_whitespace(g) == normalized
                    for g in gen_set
                )
                if not found:
                    violations.append(
                        "Missing {} clause: {}".format(clause_type, clause.strip())
                    )

        return (len(violations) == 0, violations)

    def _parse_errors(self, output: str) -> list[str]:
        """Extract error messages from Dafny output."""
        errors = []
        for line in output.splitlines():
            if "Error" in line or "error" in line:
                errors.append(line.strip())
        return errors

    def _parse_warnings(self, output: str) -> list[str]:
        """Extract warning messages from Dafny output."""
        warnings = []
        for line in output.splitlines():
            if "Warning" in line or "warning" in line:
                warnings.append(line.strip())
        return warnings

    def _count_conditions(self, output: str) -> tuple[int, int]:
        """Count verified and total conditions from Dafny output."""
        # Pattern: "Dafny program verifier finished with X verified, Y errors"
        match = re.search(
            r"(\d+)\s+verified,\s+(\d+)\s+error", output
        )
        if match:
            verified = int(match.group(1))
            error_count = int(match.group(2))
            return verified, verified + error_count

        return 0, 0

    def _extract_spec_clauses(self, code: str) -> dict[str, list[str]]:
        """Extract requires/ensures/invariant clauses from Dafny code."""
        clauses: dict[str, list[str]] = {
            "requires": [],
            "ensures": [],
            "invariant": [],
        }
        for keyword in clauses:
            pattern = rf"({keyword}\s+.+?)(?:\n|;)"
            matches = re.findall(pattern, code, re.MULTILINE)
            clauses[keyword] = matches
        return clauses

    @staticmethod
    def _normalize_whitespace(s: str) -> str:
        """Collapse whitespace for comparison."""
        return " ".join(s.split())
