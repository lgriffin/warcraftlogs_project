"""
Standardized error handling for Warcraft Logs Analysis Tool.

This module provides consistent error handling, logging, and user-friendly
error messages across the entire application.
"""

import sys
import traceback
from typing import Optional, Any
from enum import Enum

class ErrorSeverity(Enum):
    """Error severity levels."""
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class WarcraftLogsError(Exception):
    """Base exception for all Warcraft Logs analysis errors."""
    
    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.ERROR, 
                 details: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.severity = severity
        self.details = details

class ConfigurationError(WarcraftLogsError):
    """Raised when configuration is invalid or missing."""
    
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message, ErrorSeverity.CRITICAL, details)

class ApiError(WarcraftLogsError):
    """Raised when API calls fail."""
    
    def __init__(self, message: str, response_data: Optional[Any] = None, 
                 severity: ErrorSeverity = ErrorSeverity.ERROR):
        details = None
        if response_data:
            details = f"API Response: {response_data}"
        super().__init__(message, severity, details)
        self.response_data = response_data

class DataProcessingError(WarcraftLogsError):
    """Raised when data processing fails."""
    
    def __init__(self, message: str, actor_name: Optional[str] = None):
        details = f"Actor: {actor_name}" if actor_name else None
        super().__init__(message, ErrorSeverity.WARNING, details)
        self.actor_name = actor_name

class ReportGenerationError(WarcraftLogsError):
    """Raised when report generation fails."""
    pass

def format_error_message(error: WarcraftLogsError) -> str:
    """Format error message with appropriate emoji and details."""
    severity_icons = {
        ErrorSeverity.WARNING: "⚠️",
        ErrorSeverity.ERROR: "❌", 
        ErrorSeverity.CRITICAL: "🚨"
    }
    
    icon = severity_icons.get(error.severity, "❌")
    message = f"{icon} {error.message}"
    
    if error.details:
        message += f"\n   Details: {error.details}"
    
    return message

def handle_error(error: Exception, context: Optional[str] = None, 
                 exit_on_critical: bool = True) -> bool:
    """
    Handle errors consistently across the application.
    
    Args:
        error: The exception that occurred
        context: Additional context about where the error occurred
        exit_on_critical: Whether to exit the application on critical errors
        
    Returns:
        bool: True if the error was handled and execution should continue,
              False if the error is critical and execution should stop
    """
    if isinstance(error, WarcraftLogsError):
        message = format_error_message(error)
        if context:
            message = f"{message}\n   Context: {context}"
        print(message)
        
        if error.severity == ErrorSeverity.CRITICAL and exit_on_critical:
            sys.exit(1)
            
        return error.severity != ErrorSeverity.CRITICAL
    
    else:
        # Handle unexpected errors
        print(f"❌ Unexpected error: {error}")
        if context:
            print(f"   Context: {context}")
        
        # In debug mode, show full traceback
        if __debug__:
            traceback.print_exc()
        
        if exit_on_critical:
            sys.exit(1)
        return False

def safe_api_call(func, *args, error_message: str = "API call failed", 
                  actor_name: Optional[str] = None, **kwargs):
    """
    Safely execute an API call with consistent error handling.
    
    Args:
        func: The function to call
        *args: Arguments for the function
        error_message: Error message to display on failure
        actor_name: Name of actor being processed (for context)
        **kwargs: Keyword arguments for the function
        
    Returns:
        The result of the function call, or None if it failed
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if "data" not in str(e).lower():
            # Generic API error
            api_error = ApiError(f"{error_message}: {e}")
        else:
            # Missing data error - likely invalid report ID or expired token
            api_error = ApiError(
                f"{error_message}: Invalid report ID or expired token",
                severity=ErrorSeverity.CRITICAL
            )
        
        if actor_name:
            api_error.details = f"Actor: {actor_name}"
            
        handle_error(api_error, exit_on_critical=False)
        return None

def safe_data_processing(func, *args, error_message: str = "Data processing failed",
                        actor_name: Optional[str] = None, **kwargs):
    """
    Safely execute data processing with consistent error handling.
    
    Args:
        func: The function to call
        *args: Arguments for the function  
        error_message: Error message to display on failure
        actor_name: Name of actor being processed (for context)
        **kwargs: Keyword arguments for the function
        
    Returns:
        The result of the function call, or None if it failed
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        processing_error = DataProcessingError(f"{error_message}: {e}", actor_name)
        handle_error(processing_error, exit_on_critical=False)
        return None

def validate_api_response(response: Any, expected_keys: list, 
                         context: str = "API response") -> bool:
    """
    Validate API response structure.
    
    Args:
        response: The API response to validate
        expected_keys: List of keys that should be present
        context: Context for error messages
        
    Returns:
        bool: True if response is valid, False otherwise
    """
    if not isinstance(response, dict):
        raise ApiError(f"Invalid {context}: Expected dict, got {type(response)}")
    
    missing_keys = []
    current = response
    
    for key in expected_keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            missing_keys.append(key)
            break
    
    if missing_keys:
        raise ApiError(
            f"Invalid {context}: Missing required data path",
            details=f"Missing: {' -> '.join(expected_keys[:len(expected_keys)-len(missing_keys)+1])}"
        )
    
    return True

# Decorator for consistent error handling
def error_handler(error_message: str = "Operation failed", 
                 actor_context: bool = False):
    """
    Decorator for consistent error handling across functions.
    
    Args:
        error_message: Base error message
        actor_context: Whether to extract actor name from function arguments
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except WarcraftLogsError:
                # Re-raise our custom errors
                raise
            except Exception as e:
                actor_name = None
                if actor_context and len(args) > 0:
                    # Try to extract actor name from arguments
                    if hasattr(args[0], 'get'):
                        actor_name = args[0].get('name')
                    elif len(args) > 1 and hasattr(args[1], 'get'):
                        actor_name = args[1].get('name')
                
                if "api" in func.__name__.lower() or "query" in func.__name__.lower():
                    raise ApiError(f"{error_message}: {e}")
                else:
                    raise DataProcessingError(f"{error_message}: {e}", actor_name)
        
        return wrapper
    return decorator 