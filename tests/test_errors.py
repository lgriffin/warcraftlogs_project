"""Tests for the error hierarchy and error-handling utilities."""

import pytest

from warcraftlogs_client.common.errors import (
    ApiError,
    ConfigurationError,
    DataProcessingError,
    ErrorSeverity,
    ReportGenerationError,
    WarcraftLogsError,
    error_handler,
    format_error_message,
    safe_api_call,
    safe_data_processing,
    validate_api_response,
)


class TestErrorHierarchy:
    def test_all_inherit_from_base(self):
        for cls in (ConfigurationError, ApiError, DataProcessingError, ReportGenerationError):
            assert issubclass(cls, WarcraftLogsError)
            assert issubclass(cls, Exception)

    def test_configuration_error_is_critical(self):
        err = ConfigurationError("bad config")
        assert err.severity == ErrorSeverity.CRITICAL

    def test_api_error_default_severity(self):
        err = ApiError("failed")
        assert err.severity == ErrorSeverity.ERROR

    def test_api_error_custom_severity(self):
        err = ApiError("timeout", severity=ErrorSeverity.WARNING)
        assert err.severity == ErrorSeverity.WARNING

    def test_api_error_response_data(self):
        err = ApiError("failed", response_data={"error": "bad"})
        assert err.response_data == {"error": "bad"}
        assert "API Response" in err.details

    def test_data_processing_error_is_warning(self):
        err = DataProcessingError("oops")
        assert err.severity == ErrorSeverity.WARNING

    def test_data_processing_error_actor_name(self):
        err = DataProcessingError("oops", actor_name="Player1")
        assert err.actor_name == "Player1"
        assert "Player1" in err.details

    def test_report_generation_error_defaults(self):
        err = ReportGenerationError("fail")
        assert err.severity == ErrorSeverity.ERROR


class TestFormatErrorMessage:
    def test_warning_icon(self):
        err = DataProcessingError("minor issue")
        msg = format_error_message(err)
        assert "minor issue" in msg

    def test_critical_icon(self):
        err = ConfigurationError("missing file")
        msg = format_error_message(err)
        assert "missing file" in msg

    def test_details_included(self):
        err = ConfigurationError("bad", details="extra info")
        msg = format_error_message(err)
        assert "extra info" in msg

    def test_no_details(self):
        err = WarcraftLogsError("plain")
        msg = format_error_message(err)
        assert "Details" not in msg


class TestSafeApiCall:
    def test_success_returns_value(self):
        result = safe_api_call(lambda x: x * 2, 5)
        assert result == 10

    def test_failure_returns_none(self):
        def boom():
            raise RuntimeError("network error")
        result = safe_api_call(boom)
        assert result is None

    def test_kwargs_forwarded(self):
        def fn(a, b=10):
            return a + b
        assert safe_api_call(fn, 3, b=7) == 10


class TestSafeDataProcessing:
    def test_success_returns_value(self):
        result = safe_data_processing(lambda: 42)
        assert result == 42

    def test_failure_returns_none(self):
        def boom():
            raise ValueError("parse error")
        result = safe_data_processing(boom)
        assert result is None


class TestValidateApiResponse:
    def test_valid_response(self):
        resp = {"data": {"reportData": {"report": {}}}}
        assert validate_api_response(resp, ["data", "reportData", "report"]) is True

    def test_missing_key_raises(self):
        resp = {"data": {}}
        with pytest.raises(ApiError):
            validate_api_response(resp, ["data", "reportData", "report"])

    def test_non_dict_raises(self):
        with pytest.raises(ApiError):
            validate_api_response("not a dict", ["key"])


class TestErrorHandlerDecorator:
    def test_passthrough_on_success(self):
        @error_handler("test op")
        def fn(x):
            return x + 1
        assert fn(5) == 6

    def test_reraises_custom_errors(self):
        @error_handler("test op")
        def fn():
            raise ConfigurationError("bad")
        with pytest.raises(ConfigurationError):
            fn()

    def test_wraps_generic_exception(self):
        @error_handler("test op")
        def fn():
            raise ValueError("raw")
        with pytest.raises(DataProcessingError):
            fn()

    def test_api_named_function_raises_api_error(self):
        @error_handler("api call")
        def query_api():
            raise RuntimeError("timeout")
        with pytest.raises(ApiError):
            query_api()
