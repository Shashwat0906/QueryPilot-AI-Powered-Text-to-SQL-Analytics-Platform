"""Bounded self-correction loop.

    question -> generate SQL -> validate -> execute -> success
                     ^              |          |
                     |   recoverable error (syntax / unknown column / parse)
                     +---- correct (max `max_corrections` times) ----+

Rules:
* At most 1 initial generation + `max_corrections` corrections (default 2),
  so at most 3 SQL-generating LLM calls per request. Never unbounded.
* Only RECOVERABLE errors are retried. SECURITY violations (e.g. the model
  wrote DELETE) stop immediately with status "rejected"; asking the model
  to "fix" a destructive query would just invite it to try another route.
  RESOURCE errors (timeouts) and provider outages also stop.
* The model only sees the short sanitized error message (e.g.
  "Unknown column 'o.amount'..."), never stack traces or file paths.
* Every corrected query is validated again from scratch.
* Every attempt is recorded for the SQL viewer and history.
* Before execution, `result_checks.check_revenue_rule` enforces the revenue
  business rule (cancelled / refunded orders excluded) instead of only
  asking for it in the prompt.
* After a successful execution, `result_checks.check_row_count` compares the
  result shape with the question ("top five" -> at most 5 rows). A mismatch is
  corrected like any recoverable error; on the last attempt the result is kept
  and a warning is returned instead of failing the whole request.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.errors import (
    ErrorCategory,
    LLMProviderError,
    LLMResponseParseError,
    QueryExecutionError,
    SQLValidationError,
)
from app.services.llm_service import LLMResult
from app.services.query_executor import ExecutionResult, QueryExecutor
from app.services.result_checks import check_revenue_rule, check_row_count
from app.services.schema_service import DatabaseSchema
from app.services.sql_generator import GeneratedSQL, SQLGenerator, parse_generation
from app.services.sql_validator import ValidatedSQL, validate_sql


@dataclass
class Attempt:
    number: int
    kind: str  # "generation" | "correction"
    sql: str | None = None  # SQL as written by the model
    status: str = "pending"  # success | validation_error | execution_error | security_violation
    #                          | result_check_failed | parse_error | unanswerable | timeout
    #                          | provider_error
    error_code: str | None = None
    error_message: str | None = None
    error_category: str | None = None
    llm_latency_ms: float | None = None
    db_latency_ms: float | None = None


@dataclass
class PipelineError:
    code: str
    message: str
    category: str


@dataclass
class PipelineResult:
    status: str  # success | failed | rejected | unanswerable
    attempts: list[Attempt] = field(default_factory=list)
    llm_calls: list[LLMResult] = field(default_factory=list)
    generated: GeneratedSQL | None = None
    validated: ValidatedSQL | None = None
    execution: ExecutionResult | None = None
    error: PipelineError | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def retry_count(self) -> int:
        return sum(1 for a in self.attempts if a.kind == "correction")

    @property
    def generation_ms(self) -> float:
        return round(sum(c.latency_ms for c in self.llm_calls), 2)

    @property
    def db_ms(self) -> float:
        return round(sum(a.db_latency_ms or 0 for a in self.attempts), 2)


class RetryService:
    def __init__(
        self,
        generator: SQLGenerator,
        executor: QueryExecutor,
        *,
        max_corrections: int,
        max_rows: int,
        timeout_seconds: float,
    ):
        self.generator = generator
        self.executor = executor
        self.max_corrections = max_corrections
        self.max_rows = max_rows
        self.timeout_seconds = timeout_seconds

    def run(self, question: str, schema: DatabaseSchema) -> PipelineResult:
        context = schema.to_prompt_context()
        result = PipelineResult(status="failed")
        previous_sql: str | None = None
        last_error: str | None = None

        for i in range(self.max_corrections + 1):
            attempt = Attempt(number=i + 1, kind="generation" if i == 0 else "correction")
            result.attempts.append(attempt)

            # --- 1. Ask the LLM -------------------------------------------
            try:
                if i == 0:
                    call = self.generator.generate(question, context)
                else:
                    call = self.generator.correct(
                        question, context, previous_sql or "(no valid SQL was produced)",
                        last_error or "unknown error",
                    )
            except LLMResponseParseError as exc:
                last_error = self._mark(attempt, "parse_error", exc.code, exc.message,
                                        ErrorCategory.RECOVERABLE)
                continue
            except LLMProviderError as exc:
                self._mark(attempt, "provider_error", exc.code, exc.message, ErrorCategory.PROVIDER)
                result.error = PipelineError(exc.code, exc.message, ErrorCategory.PROVIDER.value)
                return result
            result.llm_calls.append(call)
            attempt.llm_latency_ms = round(call.latency_ms, 2)

            try:
                generated = parse_generation(call.data)
            except LLMResponseParseError as exc:
                last_error = self._mark(
                    attempt, "parse_error", exc.code,
                    "Your previous reply did not match the required JSON format.",
                    ErrorCategory.RECOVERABLE,
                )
                continue
            result.generated = generated
            attempt.sql = generated.sql

            if not generated.answerable:
                message = generated.clarification or "The question cannot be answered from this schema."
                self._mark(attempt, "unanswerable", "unanswerable", message, ErrorCategory.UNANSWERABLE)
                result.status = "unanswerable"
                result.error = PipelineError("unanswerable", message, ErrorCategory.UNANSWERABLE.value)
                return result

            # --- 2. Validate ------------------------------------------------
            try:
                validated = validate_sql(generated.sql or "", schema, self.executor.dialect)
            except SQLValidationError as exc:
                if exc.category == ErrorCategory.SECURITY:
                    return self._reject(result, attempt, exc.code, exc.message)
                previous_sql = generated.sql
                last_error = self._mark(attempt, "validation_error", exc.code, exc.message,
                                        exc.category)
                continue

            # --- 2b. Business rules the SQL must follow ----------------------
            rule_problem = check_revenue_rule(question, validated.sql)
            if rule_problem:
                previous_sql = validated.sql
                last_error = self._mark(attempt, "validation_error", "business_rule_violation",
                                        rule_problem, ErrorCategory.RECOVERABLE)
                continue

            # --- 3. Execute -------------------------------------------------
            try:
                execution = self.executor.execute(
                    validated.sql, max_rows=self.max_rows,
                    timeout_seconds=self.timeout_seconds, cte_names=validated.cte_names,
                )
            except QueryExecutionError as exc:
                if exc.category == ErrorCategory.SECURITY:
                    return self._reject(result, attempt, exc.code, exc.message)
                if exc.category == ErrorCategory.RESOURCE:
                    self._mark(attempt, "timeout", exc.code, exc.message, exc.category)
                    result.error = PipelineError(exc.code, exc.message, exc.category.value)
                    return result
                previous_sql = validated.sql
                last_error = self._mark(attempt, "execution_error", exc.code, exc.message,
                                        exc.category)
                continue

            attempt.db_latency_ms = execution.duration_ms

            # --- 4. Does the result's shape match the question? ------------
            problem = check_row_count(question, execution.row_count)
            if problem and i < self.max_corrections:
                previous_sql = validated.sql
                last_error = self._mark(attempt, "result_check_failed", "row_count_mismatch",
                                        problem, ErrorCategory.RECOVERABLE)
                continue
            if problem:
                result.warnings.append(problem)

            attempt.status = "success"
            result.status = "success"
            result.validated = validated
            result.execution = execution
            return result

        total = self.max_corrections + 1
        result.error = PipelineError(
            "retries_exhausted",
            f"Could not produce a working query after {total} attempt(s). Last error: {last_error}",
            ErrorCategory.RECOVERABLE.value,
        )
        return result

    @staticmethod
    def _mark(attempt: Attempt, status: str, code: str, message: str, category: ErrorCategory) -> str:
        attempt.status = status
        attempt.error_code = code
        attempt.error_message = message
        attempt.error_category = category.value
        return message

    def _reject(self, result: PipelineResult, attempt: Attempt, code: str, message: str) -> PipelineResult:
        self._mark(attempt, "security_violation", code, message, ErrorCategory.SECURITY)
        result.status = "rejected"
        result.error = PipelineError(code, f"Query blocked for safety: {message}",
                                     ErrorCategory.SECURITY.value)
        return result
